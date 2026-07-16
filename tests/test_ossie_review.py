from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from data_agent.io import ContractError
from data_agent.semantic.conversion import convert_semantic
from data_agent.semantic.ossie import official_validation_errors, validate_osi_document
from data_agent.semantic.review import _resolves_translation_issue, review_semantic, sha256_text
from data_agent.semantic.verification import verify_semantic_model

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/generic/sales.yaml"


class OssieValidationTests(unittest.TestCase):
    def test_official_validator_accepts_structured_ai_context_and_bigquery(self) -> None:
        document = _document()
        document["semantic_model"][0]["ai_context"] = {
            "synonyms": ["sales"],
            "examples": ["Show sales"],
        }
        document["semantic_model"][0]["datasets"][0]["fields"][0]["expression"]["dialects"].append(
            {"dialect": "BIGQUERY", "expression": "orders.order_id"}
        )
        self.assertEqual(official_validation_errors(document), [])

    def test_official_validator_reports_duplicates_references_and_sql(self) -> None:
        document = _document()
        model = document["semantic_model"][0]
        model["datasets"].append(dict(model["datasets"][0]))
        model["relationships"] = [
            {
                "name": "bad_relationship",
                "from": "orders",
                "to": "missing",
                "from_columns": ["order_id"],
                "to_columns": ["id"],
            }
        ]
        model["metrics"][0]["expression"]["dialects"][0]["expression"] = "SUM("
        errors = official_validation_errors(document)
        self.assertTrue(any("[Unique]" in error for error in errors))
        self.assertTrue(any("[Reference]" in error for error in errors))
        self.assertTrue(any("[SQL]" in error for error in errors))

    def test_readiness_rejects_names_that_only_differ_after_normalization(self) -> None:
        document = _document()
        duplicate = dict(document["semantic_model"][0]["datasets"][0])  # type: ignore[index]
        duplicate["name"] = "Orders"
        duplicate["source"] = "DEMO.ANALYTICS.OTHER_ORDERS"
        document["semantic_model"][0]["datasets"].append(duplicate)  # type: ignore[index]
        validation = validate_osi_document(document)
        self.assertTrue(validation["official_valid"])
        self.assertTrue(
            any(
                issue["code"] == "DUPLICATE_NORMALIZED_NAME"
                for issue in validation["readiness_issues"]
            )
        )


class SemanticReviewTests(unittest.TestCase):
    def _build(self, directory: str) -> dict[str, object]:
        return convert_semantic(
            {
                "request_id": "review-test",
                "source_path": str(FIXTURE),
                "model_name": "review_sales",
                "output_dir": directory,
            }
        )

    def test_translation_resolution_is_a_semantic_logic_change(self) -> None:
        before = [
            {
                "name": "COMMON",
                "data": json.dumps(
                    {
                        "kind": "source_metadata",
                        "translation_status": "requires-human-review",
                    }
                ),
            }
        ]
        after = [
            {
                "name": "COMMON",
                "data": json.dumps({"kind": "source_metadata", "translation_status": "exact"}),
            }
        ]
        self.assertTrue(_resolves_translation_issue(before, after))
        self.assertFalse(_resolves_translation_issue(after, after))

    def test_reviewed_unsupported_disposition_is_promotion_ready(self) -> None:
        document = _document()
        model = document["semantic_model"][0]
        model["custom_extensions"] = [
            {
                "vendor_name": "COMMON",
                "data": json.dumps(
                    {
                        "kind": "conversion_provenance",
                        "unsupported": [{"field": "Orders.Margin", "construct": "DAX"}],
                    },
                    sort_keys=True,
                ),
            },
            {
                "vendor_name": "COMMON",
                "data": json.dumps(
                    {
                        "kind": "unsupported_review",
                        "source_expression": "One DAX calculation was excluded.",
                        "translation_status": "requires-human-review",
                    },
                    sort_keys=True,
                ),
            },
        ]
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            raw_path = Path(directory) / "reviewed_unsupported.raw.osi.yaml"
            raw_text = json.dumps(document)
            raw_path.write_text(raw_text)
            raw_sha = sha256_text(raw_text)
            manifest_path = Path(directory) / "reviewed_unsupported.conversion.json"
            manifest_path.write_text(
                json.dumps({"osi": {"raw_model_sha256": raw_sha}, "issues": []})
            )
            reviewed_extension = dict(model["custom_extensions"][1])
            reviewed_data = json.loads(reviewed_extension["data"])
            reviewed_data["translation_status"] = "reviewed-unsupported"
            reviewed_extension["data"] = json.dumps(reviewed_data, sort_keys=True)
            patch_path = Path(directory) / "reviewed_unsupported.review.patch.json"
            patch_path.write_text(
                json.dumps(
                    {
                        "patch_version": "1.0",
                        "base_model_sha256": raw_sha,
                        "operations": [
                            {
                                "base_model_sha256": raw_sha,
                                "op": "replace",
                                "path": "/semantic_model/0/custom_extensions/1",
                                "value": reviewed_extension,
                                "rationale": "The owner accepted exclusion of the unsupported DAX.",
                                "evidence": [
                                    {"type": "user", "reference": "Definition owner decision"}
                                ],
                                "confidence": "high",
                                "assumptions": [],
                            }
                        ],
                    }
                )
            )
            promotion_root = Path(directory) / "promotion-root"
            with patch("data_agent.semantic.review.ROOT", promotion_root):
                result = review_semantic(
                    {
                        "request_id": "reviewed-unsupported",
                        "raw_model_path": str(raw_path),
                        "manifest_path": str(manifest_path),
                        "patch_path": str(patch_path),
                        "promote_if_clean": True,
                    }
                )

        self.assertTrue(result["analysis_ready"])
        self.assertTrue(result["clean"])
        self.assertTrue(result["promoted"])

    def test_empty_audited_review_is_clean_and_offline(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            built = self._build(directory)
            raw_path = Path(str(built["raw_model_path"]))
            manifest_path = Path(str(built["manifest_path"]))
            manifest = json.loads(manifest_path.read_text())
            patch_path = Path(directory) / "review.patch.json"
            patch_path.write_text(
                json.dumps(
                    {
                        "patch_version": "1.0",
                        "base_model_sha256": manifest["osi"]["raw_model_sha256"],
                        "operations": [],
                    }
                )
            )
            promotion_root = Path(directory) / "promotion-root"
            with (
                patch("data_agent.semantic.verification._connect") as connect,
                patch("data_agent.semantic.review.ROOT", promotion_root),
            ):
                result = review_semantic(
                    {
                        "request_id": "review",
                        "raw_model_path": str(raw_path),
                        "manifest_path": str(manifest_path),
                        "patch_path": str(patch_path),
                        "verify_snowflake": False,
                        "promote_if_clean": True,
                    }
                )
                repeated = review_semantic(
                    {
                        "request_id": "review-repeat",
                        "raw_model_path": str(raw_path),
                        "manifest_path": str(manifest_path),
                        "patch_path": str(patch_path),
                        "verify_snowflake": False,
                        "promote_if_clean": True,
                    }
                )
            connect.assert_not_called()
            self.assertTrue(result["clean"])
            self.assertTrue(result["promoted"])
            self.assertEqual(result["warehouse_verification"]["status"], "not_requested")
            self.assertTrue(Path(result["final_model_path"]).is_file())
            self.assertTrue(Path(str(result["promoted_model_path"])).is_file())
            self.assertEqual(result["final_model_sha256"], repeated["final_model_sha256"])

    def test_patch_hash_mismatch_and_protected_version_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            built = self._build(directory)
            patch_path = Path(directory) / "review.patch.json"
            patch_path.write_text(
                json.dumps(
                    {
                        "patch_version": "1.0",
                        "base_model_sha256": "0" * 64,
                        "operations": [],
                    }
                )
            )
            request = {
                "request_id": "review",
                "raw_model_path": built["raw_model_path"],
                "manifest_path": built["manifest_path"],
                "patch_path": str(patch_path),
            }
            with self.assertRaisesRegex(ContractError, "base_model_sha256"):
                review_semantic(request)

            manifest = json.loads(Path(str(built["manifest_path"])).read_text())
            patch_path.write_text(
                json.dumps(
                    {
                        "patch_version": "1.0",
                        "base_model_sha256": manifest["osi"]["raw_model_sha256"],
                        "operations": [
                            {
                                "op": "replace",
                                "path": "/version",
                                "value": "9.9",
                                "rationale": "test",
                                "evidence": [{"type": "official_spec", "reference": "test"}],
                                "confidence": "high",
                                "assumptions": [],
                            }
                        ],
                    }
                )
            )
            with self.assertRaisesRegex(ContractError, "operation 0 base_model_sha256"):
                review_semantic(request)

            patch_path.write_text(
                json.dumps(
                    {
                        "patch_version": "1.0",
                        "base_model_sha256": manifest["osi"]["raw_model_sha256"],
                        "operations": [
                            {
                                "base_model_sha256": manifest["osi"]["raw_model_sha256"],
                                "op": "replace",
                                "path": "/version",
                                "value": "9.9",
                                "rationale": "test",
                                "evidence": [{"type": "official_spec", "reference": "test"}],
                                "confidence": "high",
                                "assumptions": [],
                            }
                        ],
                    }
                )
            )
            with self.assertRaisesRegex(ContractError, "Ossie version"):
                review_semantic(request)

    def test_assumptions_prevent_clean_promotion(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            built = self._build(directory)
            manifest = json.loads(Path(str(built["manifest_path"])).read_text())
            patch_path = Path(directory) / "review.patch.json"
            patch_path.write_text(
                json.dumps(
                    {
                        "patch_version": "1.0",
                        "base_model_sha256": manifest["osi"]["raw_model_sha256"],
                        "operations": [
                            {
                                "base_model_sha256": manifest["osi"]["raw_model_sha256"],
                                "op": "replace",
                                "path": "/semantic_model/0/description",
                                "value": "Reviewed sales model.",
                                "rationale": "Clarify scope.",
                                "evidence": [{"type": "inference", "reference": "field names"}],
                                "confidence": "medium",
                                "assumptions": ["Sales means booked revenue."],
                            }
                        ],
                    }
                )
            )
            result = review_semantic(
                {
                    "request_id": "review",
                    "raw_model_path": built["raw_model_path"],
                    "manifest_path": built["manifest_path"],
                    "patch_path": str(patch_path),
                    "promote_if_clean": True,
                }
            )
            self.assertFalse(result["clean"])
            self.assertFalse(result["promoted"])
            self.assertTrue(result["unresolved_assumptions"])

    def test_failed_competency_preserves_previously_promoted_model(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            built = self._build(directory)
            manifest = json.loads(Path(str(built["manifest_path"])).read_text())
            patch_path = Path(directory) / "review.patch.json"
            patch_path.write_text(
                json.dumps(
                    {
                        "patch_version": "1.0",
                        "base_model_sha256": manifest["osi"]["raw_model_sha256"],
                        "operations": [],
                    }
                )
            )
            promotion_root = Path(directory) / "promotion-root"
            tests_dir = promotion_root / "semantic/tests"
            models_dir = promotion_root / "semantic/models"
            tests_dir.mkdir(parents=True)
            models_dir.mkdir(parents=True)
            tests_dir.joinpath("review_sales.yaml").write_text(
                """model: review_sales
cases:
  - id: incompatible_refresh
    question: Use a removed field.
    plan:
      semantic_model: review_sales
      metric_ids: [gross_sales]
      dimensions: [sales.removed_field]
    expected: {}
"""
            )
            promoted_path = models_dir / "review_sales.yaml"
            previous = "previous promoted model\n"
            promoted_path.write_text(previous)

            with patch("data_agent.semantic.review.ROOT", promotion_root):
                result = review_semantic(
                    {
                        "request_id": "review-failed-competency",
                        "raw_model_path": built["raw_model_path"],
                        "manifest_path": built["manifest_path"],
                        "patch_path": str(patch_path),
                        "promote_if_clean": True,
                    }
                )

            self.assertFalse(result["clean"])
            self.assertFalse(result["promoted"])
            self.assertEqual(result["competency_tests"]["status"], "failed")
            self.assertEqual(promoted_path.read_text(), previous)

    def test_add_replace_remove_and_path_guardrails(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            built = self._build(directory)
            manifest = json.loads(Path(str(built["manifest_path"])).read_text())
            raw_sha = manifest["osi"]["raw_model_sha256"]
            patch_path = Path(directory) / "review.patch.json"

            def operation(op: str, path: str, **values: object) -> dict[str, object]:
                return {
                    "base_model_sha256": raw_sha,
                    "op": op,
                    "path": path,
                    "rationale": "Exercise deterministic JSON patch behavior.",
                    "evidence": [{"type": "source_metadata", "reference": "fixture"}],
                    "confidence": "high",
                    "assumptions": [],
                    **values,
                }

            patch_path.write_text(
                json.dumps(
                    {
                        "patch_version": "1.0",
                        "base_model_sha256": raw_sha,
                        "operations": [
                            operation(
                                "add",
                                "/semantic_model/0/ai_context",
                                value={"instructions": "Use documented booked sales."},
                            ),
                            operation(
                                "replace",
                                "/semantic_model/0/description",
                                value="Reviewed sales model.",
                            ),
                            operation("remove", "/semantic_model/0/ai_context"),
                        ],
                    }
                )
            )
            result = review_semantic(
                {
                    "request_id": "review-operations",
                    "raw_model_path": built["raw_model_path"],
                    "manifest_path": built["manifest_path"],
                    "patch_path": str(patch_path),
                    "promote_if_clean": False,
                }
            )
            self.assertTrue(result["clean"])
            audited = json.loads(Path(str(built["manifest_path"])).read_text())["review"]
            self.assertEqual(
                [item["op"] for item in audited["operations"]], ["add", "replace", "remove"]
            )
            self.assertIsNone(audited["operations"][-1]["after"])

            for guarded_path, message in (
                ("/semantic_model/0/custom_extensions/0", "converter provenance"),
                ("/semantic_model/0/missing", "does not exist"),
            ):
                patch_path.write_text(
                    json.dumps(
                        {
                            "patch_version": "1.0",
                            "base_model_sha256": raw_sha,
                            "operations": [operation("remove", guarded_path)],
                        }
                    )
                )
                with self.assertRaisesRegex(ContractError, message):
                    review_semantic(
                        {
                            "request_id": "review-guardrail",
                            "raw_model_path": built["raw_model_path"],
                            "manifest_path": built["manifest_path"],
                            "patch_path": str(patch_path),
                        }
                    )

    def test_logic_change_requires_high_confidence_direct_evidence(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            built = self._build(directory)
            manifest = json.loads(Path(str(built["manifest_path"])).read_text())
            raw_sha = manifest["osi"]["raw_model_sha256"]
            patch_path = Path(directory) / "review.patch.json"
            patch_path.write_text(
                json.dumps(
                    {
                        "patch_version": "1.0",
                        "base_model_sha256": raw_sha,
                        "operations": [
                            {
                                "base_model_sha256": raw_sha,
                                "op": "replace",
                                "path": "/semantic_model/0/metrics/0/expression/dialects/0/expression",
                                "value": "SUM(sales.net_amount)",
                                "rationale": "Infer a net-sales definition.",
                                "evidence": [{"type": "inference", "reference": "metric name"}],
                                "confidence": "medium",
                                "assumptions": [],
                            }
                        ],
                    }
                )
            )
            result = review_semantic(
                {
                    "request_id": "review-logic",
                    "raw_model_path": built["raw_model_path"],
                    "manifest_path": built["manifest_path"],
                    "patch_path": str(patch_path),
                    "promote_if_clean": True,
                }
            )
            self.assertFalse(result["clean"])
            self.assertTrue(
                any("semantic logic" in item for item in result["unresolved_assumptions"])
            )


class SnowflakeVerificationTests(unittest.TestCase):
    def test_confirmation_is_required_when_verification_is_requested(self) -> None:
        settings = SimpleNamespace(
            readiness_errors=lambda: [],
            authenticator="externalbrowser",
            role="READONLY",
        )
        with patch("data_agent.semantic.verification.load_settings", return_value=settings):
            with self.assertRaisesRegex(ContractError, "configuration_confirmed"):
                verify_semantic_model(
                    {
                        "request_id": "verify",
                        "document": _document(),
                        "configuration_confirmed": False,
                    }
                )

    def test_metadata_and_expressions_are_described_without_execution(self) -> None:
        cursor = _FakeCursor()
        settings = SimpleNamespace(
            database="DEMO",
            blocked_schemas=(),
            allowed_objects=(),
            role="READONLY",
        )
        with (
            patch("data_agent.semantic.verification.load_settings", return_value=settings),
            patch(
                "data_agent.semantic.verification._connect",
                return_value=_FakeConnection(cursor),
            ),
        ):
            result = verify_semantic_model(
                {
                    "request_id": "verify",
                    "document": _document(),
                    "configuration_confirmed": True,
                }
            )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(result["checked_objects"]), 1)
        self.assertEqual(len(result["checked_expressions"]), 2)
        self.assertEqual(cursor.describe_calls, 2)

    def test_information_schema_detects_missing_mapped_column(self) -> None:
        cursor = _FakeCursor()
        cursor.fetchall = lambda: [("OTHER_COLUMN", "NUMBER", "YES", None)]  # type: ignore[method-assign]
        settings = SimpleNamespace(
            database="DEMO",
            blocked_schemas=(),
            allowed_objects=(),
            role="READONLY",
        )
        with (
            patch("data_agent.semantic.verification.load_settings", return_value=settings),
            patch(
                "data_agent.semantic.verification._connect",
                return_value=_FakeConnection(cursor),
            ),
        ):
            result = verify_semantic_model(
                {
                    "request_id": "verify",
                    "document": _document(),
                    "configuration_confirmed": True,
                }
            )
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any(error["kind"] == "column" for error in result["errors"]))


def _document() -> dict[str, object]:
    return {
        "version": "0.2.0.dev0",
        "semantic_model": [
            {
                "name": "sales",
                "description": "Sales model.",
                "datasets": [
                    {
                        "name": "orders",
                        "source": "DEMO.ANALYTICS.ORDERS",
                        "fields": [
                            {
                                "name": "order_id",
                                "expression": {
                                    "dialects": [
                                        {
                                            "dialect": "ANSI_SQL",
                                            "expression": "orders.order_id",
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                ],
                "relationships": [],
                "metrics": [
                    {
                        "name": "order_count",
                        "expression": {
                            "dialects": [
                                {"dialect": "ANSI_SQL", "expression": "COUNT(orders.order_id)"}
                            ]
                        },
                    }
                ],
            }
        ],
    }


class _FakeCursor:
    def __init__(self) -> None:
        self.sfqid = "query-context"
        self.describe_calls = 0
        self._metadata = False

    def execute(self, sql: str, parameters: object = None) -> None:
        self._metadata = "INFORMATION_SCHEMA.COLUMNS" in sql
        self.sfqid = "query-metadata" if self._metadata else "query-context"

    def fetchone(self) -> tuple[str, str, str, str, str]:
        return ("USER", "READONLY", "WH", "DEMO", "ANALYTICS")

    def fetchall(self) -> list[tuple[str, str, str, str]]:
        return [("ORDER_ID", "NUMBER", "NO", "Order identifier")]

    def describe(self, sql: str) -> list[SimpleNamespace]:
        self.describe_calls += 1
        return [SimpleNamespace(name="CHECK_0")]

    def close(self) -> None:
        return None


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self._cursor


if __name__ == "__main__":
    unittest.main()
