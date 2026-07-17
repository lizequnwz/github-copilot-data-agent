from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from data_agent.ask.analysis import analyze
from data_agent.ask.compiler import compile_plan
from data_agent.ask.validation import validate_result
from data_agent.config import Settings
from data_agent.io import ContractError
from data_agent.models import SemanticError, load_document
from data_agent.setup.competency import test_document
from data_agent.setup.diff import semantic_changes
from data_agent.snowflake import execute_readonly
from data_agent.sql_safety import SQLSafetyError, validate_sql

ROOT = Path(__file__).resolve().parents[1]


class AnalysisContractTests(unittest.TestCase):
    def test_semantic_exploration_uses_model_and_validation_is_optional(self) -> None:
        request = json.loads(
            (ROOT / "examples/ask-data/exploration.json").read_text()
        )
        response = analyze(request)
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["metric_source"], "promoted")
        self.assertFalse(response["unpromoted"])
        self.assertEqual(response["model"], "demo_sales")
        self.assertEqual(response["query_limit"], 101)
        self.assertEqual(response["result_validation"]["status"], "not_run")
        self.assertIn("orders.status = %s", response["sql"])
        self.assertEqual(response["referenced_objects"], ["DEMO.ANALYTICS.ORDERS"])

    def test_analysis_requires_a_promoted_model_and_plan(self) -> None:
        with self.assertRaisesRegex(ContractError, "model_path"):
            analyze({"request_id": "quick-look", "sql": "SELECT CURRENT_DATE()"})

    def test_analysis_mode_field_is_rejected_to_keep_one_core_workflow(self) -> None:
        request = json.loads(
            (ROOT / "examples/ask-data/exploration.json").read_text()
        )
        request["analysis_mode"] = "exploratory"
        with self.assertRaisesRegex(ContractError, "no longer a request field"):
            analyze(request)

    def test_default_result_grain_matches_returned_alias(self) -> None:
        request = json.loads((ROOT / "examples/ask-data/validated.json").read_text())
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
        request = json.loads((ROOT / "examples/ask-data/joined-analysis.json").read_text())
        response = analyze(request)
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["result_grain"], ["segment"])
        self.assertIn(
            "JOIN DEMO.ANALYTICS.CUSTOMERS AS customers ON orders.customer_id = customers.customer_id",
            response["sql"],
        )

    def test_live_snowflake_uppercase_columns_match_semantic_aliases(self) -> None:
        request = json.loads((ROOT / "examples/ask-data/validated.json").read_text())
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
            patch("data_agent.ask.analysis.load_settings", return_value=settings),
            patch("data_agent.snowflake.load_settings", return_value=settings),
            patch("data_agent.snowflake._connect", return_value=connection),
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
        with self.assertRaisesRegex(SemanticError, "selected dimensions, metrics, or calculations"):
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
        request = json.loads((ROOT / "examples/ask-data/validated.json").read_text())
        request["model_path"] = "workspaces/models/demo_sales.osi.yaml"
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
        self.assertEqual(compiled["metric_source"], "derived")
        self.assertTrue(compiled["metric_definitions"][0]["unpromoted"])
        self.assertIn("AS average_order_value", compiled["sql"])
        self.assertIn("LIMIT 11", compiled["sql"])

    def test_detail_query_richer_filters_and_time_grain(self) -> None:
        document = load_document(ROOT / "semantic/models/demo_sales.yaml")
        detail = compile_plan(
            document,
            {
                "semantic_model": "demo_sales",
                "metric_ids": [],
                "dimensions": ["orders.order_id", "orders.region"],
                "filters": [
                    {
                        "field": "orders.status",
                        "operator": "in",
                        "values": ["completed", "shipped"],
                    },
                    {
                        "field": "orders.region",
                        "operator": "is_not_null",
                    },
                ],
                "max_rows": 25,
            },
        )
        self.assertNotIn("GROUP BY", detail["sql"])
        self.assertIn("orders.status IN (%s, %s)", detail["sql"])
        self.assertIn("orders.region IS NOT NULL", detail["sql"])

        advanced = json.loads(
            (ROOT / "examples/ask-data/advanced-plan.json").read_text()
        )
        compiled = compile_plan(document, advanced["plan"])
        self.assertIn("DATE_TRUNC('month', orders.order_date)", compiled["sql"])
        self.assertIn("HAVING SUM(orders.gross_sales_amount) > %s", compiled["sql"])
        self.assertIn("AS sales_share", compiled["sql"])
        self.assertIn("AS sales_rank", compiled["sql"])
        self.assertEqual(compiled["parameters"], ["completed", "shipped", 0])

    def test_missing_semantics_return_structured_coverage_gap(self) -> None:
        request = json.loads(
            (ROOT / "examples/ask-data/coverage-gap.json").read_text()
        )
        response = analyze(request)
        self.assertEqual(response["status"], "coverage_gap")
        self.assertEqual(response["next_action"], "semantic_setup")
        self.assertIn(
            "customer_lifetime_value",
            response["coverage"]["missing"]["metrics"],
        )

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
                    patch("data_agent.snowflake.load_settings", return_value=settings),
                    patch("data_agent.snowflake._connect", return_value=connection),
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


if __name__ == "__main__":
    unittest.main()
