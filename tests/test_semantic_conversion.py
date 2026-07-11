from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from data_agent.bi.extract import extract_powerbi_ir, extract_tableau_ir
from data_agent.semantic.conversion import convert_semantic, detect_source_type
from data_agent.semantic.compiler import compile_plan
from data_agent.semantic.ingestion import build_osi_from_ir
from data_agent.semantic.models import validate_document

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
SCHEMA = ROOT / "semantic/schemas/osi-0.2.0.dev0.schema.json"


class SemanticConversionTests(unittest.TestCase):
    def test_detects_supported_source_types(self) -> None:
        self.assertEqual(detect_source_type(FIXTURES / "powerbi"), "powerbi")
        self.assertEqual(detect_source_type(FIXTURES / "tableau/sales.twb"), "tableau")
        self.assertEqual(detect_source_type(FIXTURES / "generic/sales.yaml"), "generic")

    def test_powerbi_extracts_fields_metric_and_relationship(self) -> None:
        ir = extract_powerbi_ir(
            {"request_id": "pbi", "source_path": str(FIXTURES / "powerbi")}
        )
        self.assertEqual(len(ir["datasets"]), 2)
        self.assertEqual(len(ir["relationships"]), 1)
        self.assertEqual(ir["metrics"][0]["normalized_expression"], "SUM(orders.sales_amount)")
        document, issues = build_osi_from_ir(ir, "powerbi_sales")
        self.assertEqual(validate_document(document, SCHEMA), [])
        self.assertFalse([issue for issue in issues if issue["severity"] == "blocking"])
        compiled = compile_plan(
            document,
            {
                "semantic_model": "powerbi_sales",
                "metric_ids": ["total_sales"],
                "dimensions": ["customers.region"],
                "max_rows": 100,
            },
        )
        self.assertIn(
            "JOIN DEMO.ANALYTICS.ORDERS AS orders ON orders.customer_id = customers.customer_id",
            compiled["sql"],
        )

    def test_tableau_extracts_simple_aggregate(self) -> None:
        ir = extract_tableau_ir(
            {"request_id": "tableau", "source_path": str(FIXTURES / "tableau/sales.twb")}
        )
        self.assertEqual(ir["datasets"][0]["physical_source"], "DEMO.ANALYTICS.ORDERS")
        self.assertEqual(ir["metrics"][0]["normalized_expression"], "SUM(sales.sales_amount)")
        document, _ = build_osi_from_ir(ir, "tableau_sales")
        self.assertEqual(validate_document(document, SCHEMA), [])

    def test_end_to_end_generic_conversion_writes_candidate_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/candidates") as directory:
            response = convert_semantic(
                {
                    "request_id": "generic",
                    "source_path": str(FIXTURES / "generic/sales.yaml"),
                    "source_type": "auto",
                    "model_name": "generic_sales",
                    "output_dir": directory,
                }
            )
            self.assertEqual(response["status"], "success")
            candidate = yaml.safe_load(Path(response["candidate_path"]).read_text())
            manifest = json.loads(Path(response["manifest_path"]).read_text())
            self.assertEqual(validate_document(candidate, SCHEMA), [])
            self.assertTrue(manifest["osi"]["schema_valid"])
            self.assertEqual(manifest["summary"]["metrics"], 1)


if __name__ == "__main__":
    unittest.main()
