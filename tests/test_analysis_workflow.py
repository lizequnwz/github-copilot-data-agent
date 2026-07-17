from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from data_agent.analysis import analyze
from data_agent.config import Settings
from data_agent.security.sql import SQLSafetyError, validate_sql
from data_agent.semantic.competency import test_document
from data_agent.semantic.compiler import compile_plan
from data_agent.semantic.diff import semantic_changes
from data_agent.semantic.models import SemanticError, load_document
from data_agent.tools.snowflake import execute_readonly
from data_agent.tools.result_validation import validate_result

ROOT = Path(__file__).resolve().parents[1]


class AnalysisContractTests(unittest.TestCase):
    def test_exploratory_sql_is_flexible_and_validation_is_optional(self) -> None:
        request = json.loads(
            (ROOT / "examples/analysis/exploratory-sales.json").read_text()
        )
        response = analyze(request)
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["analysis_mode"], "exploratory")
        self.assertTrue(response["unpromoted"])
        self.assertIsNone(response["query_limit"])
        self.assertEqual(response["result_validation"]["status"], "not_run")
        self.assertIn("status = 'completed'", response["sql"])

    def test_sql_without_model_defaults_to_exploratory_mode(self) -> None:
        response = analyze(
            {
                "request_id": "quick-look",
                "sql": "SELECT CURRENT_DATE()",
            }
        )
        self.assertEqual(response["status"], "planned")
        self.assertEqual(response["analysis_mode"], "exploratory")

    def test_exploratory_mode_allows_projection_wildcards(self) -> None:
        response = analyze(
            {
                "request_id": "quick-look",
                "sql": "SELECT * FROM DEMO.ANALYTICS.ORDERS",
            }
        )
        self.assertEqual(response["status"], "planned")
        self.assertEqual(response["analysis_mode"], "exploratory")

    def test_default_result_grain_matches_returned_alias(self) -> None:
        request = json.loads((ROOT / "examples/analysis/sales-by-region.json").read_text())
        response = analyze(request)
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["grain"], ["orders.region"])
        self.assertEqual(response["result_grain"], ["region"])
        self.assertEqual(
            response["result_columns"], {"orders.region": "region", "gross_sales": "gross_sales"}
        )
        self.assertEqual(response["max_rows"], 10)
        self.assertEqual(response["query_limit"], 11)
        self.assertIn("ORDER BY gross_sales DESC", response["sql"])
        self.assertIn("LIMIT 11", response["sql"])
        self.assertEqual(response["parameters"], ["completed", "2026-05-01", "2026-07-01"])

    def test_relationship_scenario_compiles_and_validates(self) -> None:
        request = json.loads((ROOT / "examples/analysis/sales-by-segment.json").read_text())
        response = analyze(request)
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["result_grain"], ["segment"])
        self.assertIn(
            "JOIN DEMO.ANALYTICS.CUSTOMERS AS customers ON orders.customer_id = customers.customer_id",
            response["sql"],
        )

    def test_live_snowflake_uppercase_columns_match_semantic_aliases(self) -> None:
        request = json.loads((ROOT / "examples/analysis/sales-by-region.json").read_text())
        request.update(
            {
                "execute": True,
                "configuration_confirmed": True,
                "config_path": "snowflake_config.yaml",
            }
        )
        connection = _AnalysisConnection()
        settings = _settings()
        with (
            patch("data_agent.analysis.load_settings", return_value=settings),
            patch("data_agent.tools.snowflake.load_settings", return_value=settings),
            patch("data_agent.tools.snowflake._connect", return_value=connection),
        ):
            response = analyze(request)

        self.assertEqual(response["status"], "success")
        self.assertEqual(response["result"]["columns"], ["REGION", "GROSS_SALES"])
        self.assertEqual(response["result_validation"]["status"], "pass")

    def test_projection_collisions_receive_deterministic_aliases(self) -> None:
        document = {
            "semantic_model": [
                {
                    "name": "collision",
                    "datasets": [
                        {
                            "name": "orders",
                            "source": "DEMO.ANALYTICS.ORDERS",
                            "fields": [
                                {
                                    "name": "total",
                                    "expression": {
                                        "dialects": [
                                            {"dialect": "SNOWFLAKE", "expression": "orders.total"}
                                        ]
                                    },
                                }
                            ],
                        }
                    ],
                    "metrics": [
                        {
                            "name": "total",
                            "expression": {
                                "dialects": [
                                    {"dialect": "SNOWFLAKE", "expression": "SUM(orders.total)"}
                                ]
                            },
                        }
                    ],
                }
            ]
        }
        compiled = compile_plan(
            document,
            {
                "semantic_model": "collision",
                "metric_ids": ["total"],
                "dimensions": ["orders.total"],
                "max_rows": 5,
            },
        )
        self.assertEqual(
            compiled["result_columns"],
            {"orders.total": "orders__total", "total": "metric__total"},
        )
        self.assertEqual(compiled["result_grain"], ["orders__total"])

    def test_ordering_rejects_unselected_fields(self) -> None:
        with self.assertRaisesRegex(SemanticError, "selected dimensions or metrics"):
            compile_plan(
                load_document(ROOT / "semantic/models/demo_sales.yaml"),
                {
                    "semantic_model": "demo_sales",
                    "metric_ids": ["gross_sales"],
                    "dimensions": ["orders.region"],
                    "order_by": [{"field": "order_count", "direction": "desc"}],
                },
            )

    def test_analysis_rejects_unpromoted_model_paths(self) -> None:
        request = json.loads((ROOT / "examples/analysis/sales-by-region.json").read_text())
        request["model_path"] = "semantic/generated/demo_sales.osi.yaml"
        with self.assertRaisesRegex(SemanticError, "under semantic/models"):
            analyze(request)

    def test_derived_metric_compiles_from_promoted_fields(self) -> None:
        compiled = compile_plan(
            load_document(ROOT / "semantic/models/demo_sales.yaml"),
            {
                "semantic_model": "demo_sales",
                "metric_ids": [],
                "derived_metrics": [
                    {
                        "name": "average_order_value",
                        "description": "Gross sales divided by the number of orders.",
                        "expression": (
                            "SUM(orders.gross_sales_amount) / "
                            "NULLIF(COUNT(orders.order_id), 0)"
                        ),
                        "assumptions": ["Each order ID represents one order."],
                    }
                ],
                "dimensions": ["orders.region"],
                "max_rows": 10,
            },
        )
        self.assertEqual(compiled["analysis_mode"], "derived")
        self.assertTrue(compiled["metric_definitions"][0]["unpromoted"])
        self.assertIn("AS average_order_value", compiled["sql"])
        self.assertIn("LIMIT 11", compiled["sql"])

    def test_ad_hoc_sql_uses_approved_sources_and_is_labeled_unpromoted(self) -> None:
        request = _ad_hoc_request()
        with patch("data_agent.analysis.load_settings", return_value=_settings()):
            response = analyze(request)
        self.assertEqual(response["status"], "planned")
        self.assertEqual(response["analysis_mode"], "ad_hoc")
        self.assertTrue(response["unpromoted"])
        self.assertEqual(response["referenced_objects"], ["DEMO.ANALYTICS.ORDERS"])
        self.assertEqual(response["parameters"], ["completed"])

    def test_ad_hoc_sql_rejects_unparameterized_filter_values(self) -> None:
        request = _ad_hoc_request()
        request["sql"] = request["sql"].replace("status = %s", "status = 'completed'")
        request["parameters"] = []
        with (
            patch("data_agent.analysis.load_settings", return_value=_settings()),
            self.assertRaisesRegex(SQLSafetyError, "must use positional parameters"),
        ):
            analyze(request)

    def test_ad_hoc_sql_rejects_unapproved_sources(self) -> None:
        request = _ad_hoc_request()
        request["sql"] = request["sql"].replace(
            "DEMO.ANALYTICS.ORDERS", "DEMO.OTHER.UNAPPROVED"
        )
        with (
            patch("data_agent.analysis.load_settings", return_value=_settings()),
            self.assertRaisesRegex(SQLSafetyError, "not allowlisted"),
        ):
            analyze(request)

    def test_competency_fixture_passes(self) -> None:
        result = test_document(
            load_document(ROOT / "semantic/models/demo_sales.yaml"),
            ROOT / "semantic/tests/demo_sales.yaml",
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["case_count"], 2)


class RowLimitTests(unittest.TestCase):
    def test_exact_limit_is_not_truncated_and_extra_row_is_truncated(self) -> None:
        settings = _settings()
        for returned_rows, expected in ((10, False), (11, True)):
            with self.subTest(returned_rows=returned_rows):
                connection = _Connection(returned_rows)
                with (
                    patch("data_agent.tools.snowflake.load_settings", return_value=settings),
                    patch("data_agent.tools.snowflake._connect", return_value=connection),
                ):
                    result = execute_readonly(
                        {
                            "request_id": "limit",
                            "sql": "SELECT region FROM DEMO.ANALYTICS.ORDERS LIMIT 11",
                            "parameters": [],
                            "max_rows": 10,
                            "query_limit": 11,
                            "configuration_confirmed": True,
                        }
                    )
                self.assertEqual(result["truncated"], expected)
                self.assertEqual(result["row_count"], 10)
                self.assertEqual(result["max_rows"], 10)
                self.assertEqual(result["query_limit"], 11)


class SafetyAndResultContractTests(unittest.TestCase):
    def test_projection_star_is_blocked_but_count_star_is_allowed(self) -> None:
        with self.assertRaisesRegex(SQLSafetyError, "SELECT \\*"):
            validate_sql("SELECT * FROM DEMO.ANALYTICS.ORDERS")
        validation = validate_sql(
            "SELECT COUNT(*) AS order_count FROM DEMO.ANALYTICS.ORDERS LIMIT 2"
        )
        self.assertTrue(validation.valid)

    def test_empty_result_can_be_explicitly_allowed(self) -> None:
        base = {
            "request_id": "empty",
            "result": {"columns": ["region"], "rows": [], "truncated": False},
            "grain": ["region"],
            "required_columns": ["region"],
            "required_non_null": [],
            "numeric_ranges": {},
        }
        self.assertEqual(validate_result(base)["status"], "fail")
        self.assertEqual(validate_result({**base, "allow_empty": True})["status"], "pass")


class SemanticDiffTests(unittest.TestCase):
    def test_object_level_diff_classifies_impacts(self) -> None:
        before = load_document(ROOT / "semantic/models/demo_sales.yaml")
        after = json.loads(json.dumps(before))
        model = after["semantic_model"][0]
        model["description"] = "Updated description"
        model["metrics"][0]["expression"]["dialects"][0]["expression"] = "SUM(orders.net_sales)"
        model["datasets"][0]["source"] = "DEMO.ANALYTICS.NEW_ORDERS"
        diff = semantic_changes(before, after)
        impacts = {item["change_type"]: item["impact"] for item in diff["changes"]}
        self.assertEqual(impacts["description_changed"], "metadata")
        self.assertEqual(impacts["expression_changed"], "semantic")
        self.assertEqual(impacts["source_changed"], "breaking")


class _Cursor:
    description = [("REGION",)]
    sfqid = "query-id"

    def __init__(self, returned_rows: int) -> None:
        self.returned_rows = returned_rows

    def execute(self, sql: str, parameters: Any = None) -> None:
        return None

    def fetchmany(self, count: int) -> list[tuple[str]]:
        return [(f"region-{index}",) for index in range(min(self.returned_rows, count))]

    def close(self) -> None:
        return None


class _Connection:
    def __init__(self, returned_rows: int) -> None:
        self._cursor = _Cursor(returned_rows)

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> _Cursor:
        return self._cursor


class _AnalysisCursor:
    description = [("REGION",), ("GROSS_SALES",)]
    sfqid = "analysis-query-id"

    def execute(self, sql: str, parameters: Any = None) -> None:
        return None

    def fetchmany(self, count: int) -> list[tuple[str, int]]:
        return [("East", 120), ("West", 80)]

    def close(self) -> None:
        return None


class _AnalysisConnection:
    def __enter__(self) -> _AnalysisConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> _AnalysisCursor:
        return _AnalysisCursor()


def _settings() -> Settings:
    return Settings(
        account="account",
        user="user",
        authenticator="externalbrowser",
        role="READONLY",
        warehouse="WH",
        database="DEMO",
        schema="ANALYTICS",
        query_tag="test",
        max_rows=10,
        max_bytes=100_000,
        timeout_seconds=10,
        blocked_schemas=(),
        allowed_objects=(),
        allow_sensitive_sampling=False,
    )


def _ad_hoc_request() -> dict[str, Any]:
    return {
        "request_id": "ad-hoc-average-order-value",
        "analysis_mode": "ad_hoc",
        "sql": (
            "SELECT region, "
            "SUM(gross_sales_amount) / NULLIF(COUNT(order_id), 0) AS average_order_value "
            "FROM DEMO.ANALYTICS.ORDERS WHERE status = %s GROUP BY region "
            "ORDER BY average_order_value DESC LIMIT 11"
        ),
        "parameters": ["completed"],
        "max_rows": 10,
        "result_grain": ["region"],
        "metric": {
            "name": "average_order_value",
            "formula": "SUM(gross_sales_amount) / NULLIF(COUNT(order_id), 0)",
            "description": "Gross sales divided by the number of orders.",
            "assumptions": ["Each order ID represents one order."],
        },
        "interpretation": {
            "metric": "Average order value (ad hoc)",
            "formula": "Gross sales divided by order count",
            "population": "Completed orders",
            "dimensions": ["region"],
            "filters": ["status = completed"],
            "period": "All available dates",
            "expected_result_grain": "One row per region",
            "requested_output": "Table",
        },
    }


if __name__ == "__main__":
    unittest.main()
