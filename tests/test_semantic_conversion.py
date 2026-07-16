from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from data_agent.bi.extract import extract_powerbi_ir, extract_tableau_ir
from data_agent.io import ContractError
from data_agent.semantic.conversion import convert_semantic, detect_source_type
from data_agent.semantic.compiler import compile_plan
from data_agent.semantic.ingestion import build_osi_from_ir
from data_agent.semantic.models import validate_document
from data_agent.semantic.ossie import SCHEMA

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
EXAMPLES = ROOT / "examples"


class SemanticConversionTests(unittest.TestCase):
    def test_detects_supported_source_types(self) -> None:
        self.assertEqual(detect_source_type(FIXTURES / "powerbi"), "powerbi")
        self.assertEqual(detect_source_type(FIXTURES / "tableau/sales.twb"), "tableau")
        self.assertEqual(detect_source_type(EXAMPLES / "tableau/world.tds"), "tableau")
        self.assertEqual(detect_source_type(FIXTURES / "generic/sales.yaml"), "generic")

    def test_powerbi_extracts_fields_metric_and_relationship(self) -> None:
        ir = extract_powerbi_ir({"request_id": "pbi", "source_path": str(FIXTURES / "powerbi")})
        self.assertEqual(len(ir["datasets"]), 2)
        self.assertEqual(len(ir["relationships"]), 1)
        self.assertEqual(ir["metrics"][0]["normalized_expression"], "SUM(orders.sales_amount)")
        orders = next(dataset for dataset in ir["datasets"] if dataset["name"] == "Orders")
        self.assertEqual(orders["description"], "Orders used for booked-sales analysis")
        sales_amount = next(field for field in orders["fields"] if field["name"] == "SalesAmount")
        self.assertEqual(sales_amount["description"], "Booked sales amount")
        self.assertEqual(sales_amount["label"], "Sales")
        margin = next(field for field in orders["fields"] if field["name"] == "Margin")
        self.assertEqual(
            margin["source_expression"],
            {"language": "DAX", "value": "[SalesAmount] * 0.1"},
        )
        document, issues = build_osi_from_ir(ir, "powerbi_sales")
        self.assertEqual(validate_document(document, SCHEMA), [])
        self.assertFalse([issue for issue in issues if issue["severity"] == "blocking"])
        emitted_orders = next(
            dataset
            for dataset in document["semantic_model"][0]["datasets"]
            if dataset["name"] == "orders"
        )
        self.assertNotIn("margin", {field["name"] for field in emitted_orders["fields"]})
        provenance = json.loads(document["semantic_model"][0]["custom_extensions"][0]["data"])
        self.assertTrue(
            any(
                item.get("field") == "Orders.Margin"
                and item.get("source_expression") == "[SalesAmount] * 0.1"
                for item in provenance["unsupported"]
            )
        )
        unsupported_review = json.loads(
            document["semantic_model"][0]["custom_extensions"][1]["data"]
        )
        self.assertEqual(unsupported_review["kind"], "unsupported_review")
        self.assertEqual(unsupported_review["translation_status"], "requires-human-review")
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
        fields = {
            field["name"]: field for field in document["semantic_model"][0]["datasets"][0]["fields"]
        }
        self.assertEqual(
            fields["total_sales"]["expression"]["dialects"],
            [{"dialect": "TABLEAU", "expression": "SUM([Sales Amount])"}],
        )
        metric_dialects = document["semantic_model"][0]["metrics"][0]["expression"]["dialects"]
        self.assertEqual([item["dialect"] for item in metric_dialects], ["ANSI_SQL", "TABLEAU"])

    def test_tableau_tds_extracts_default_aggregations_and_metadata_fields(self) -> None:
        ir = extract_tableau_ir(
            {
                "request_id": "world-tds",
                "source_path": str(EXAMPLES / "tableau/world.tds"),
                "source_map": {"World Indicators": "DEMO.ANALYTICS.WORLD_INDICATORS"},
                "field_map": {"World Indicators": {"CO2 Emissions": "co2_tonnes"}},
            }
        )
        self.assertEqual(ir["source_format"], "tds")
        self.assertEqual(ir["datasets"][0]["physical_source"], "DEMO.ANALYTICS.WORLD_INDICATORS")
        self.assertGreaterEqual(len(ir["datasets"][0]["fields"]), 27)
        metrics = {metric["name"]: metric for metric in ir["metrics"]}
        self.assertEqual(
            metrics["average_birth_rate"]["normalized_expression"],
            "AVG(world_indicators.birth_rate)",
        )
        self.assertEqual(metrics["number_of_records"]["normalized_expression"], "COUNT(1)")
        fields = {field["name"]: field for field in ir["datasets"][0]["fields"]}
        self.assertEqual(
            fields["CO2 Emissions"]["normalized_expression"], "world_indicators.co2_tonnes"
        )
        document, issues = build_osi_from_ir(ir, "world_indicators")
        self.assertEqual(validate_document(document, SCHEMA), [])
        self.assertFalse([issue for issue in issues if issue["severity"] == "blocking"])
        emitted_fields = {
            field["name"]: field for field in document["semantic_model"][0]["datasets"][0]["fields"]
        }
        self.assertEqual(emitted_fields["birth_rate"]["description"], "% of population")
        self.assertEqual(emitted_fields["birth_rate"]["label"], "Population")
        self.assertEqual(emitted_fields["birth_rate"]["ai_context"]["synonyms"], ["Birth Rate"])
        all_dialects = {
            dialect["dialect"]
            for item in emitted_fields.values()
            for dialect in item["expression"]["dialects"]
        }
        self.assertNotIn("SNOWFLAKE", all_dialects)
        compiled = compile_plan(
            document,
            {
                "semantic_model": "world_indicators",
                "metric_ids": ["average_birth_rate"],
                "dimensions": ["world_indicators.country"],
                "max_rows": 100,
            },
        )
        self.assertIn("AVG(world_indicators.birth_rate)", compiled["sql"])
        self.assertIn("world_indicators.country", compiled["sql"])

    def test_tableau_tde_uses_sibling_tds_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tds = root / "world.tds"
            tde = root / "world.tde"
            shutil.copy(EXAMPLES / "tableau/world.tds", tds)
            tde.write_bytes(b"TableauDataExtractPlaceholder")
            ir = extract_tableau_ir(
                {
                    "request_id": "world-tde",
                    "source_path": str(tde),
                    "source_map": {"World Indicators": "DEMO.ANALYTICS.WORLD_INDICATORS"},
                }
            )
            self.assertEqual(ir["source_format"], "tde-with-tds")
            self.assertEqual(len(ir["source_files"]), 2)

    def test_tableau_tde_accepts_explicit_descriptor_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tds = root / "world-metadata.tds"
            tde = root / "extract-2026.TDE"
            shutil.copy(EXAMPLES / "tableau/world.tds", tds)
            tde.write_bytes(b"TableauDataExtractPlaceholder")
            ir = extract_tableau_ir(
                {
                    "request_id": "explicit-descriptor",
                    "source_path": str(tde),
                    "descriptor_path": str(tds),
                    "source_map": {"World Indicators": "DEMO.ANALYTICS.WORLD_INDICATORS"},
                }
            )
            self.assertEqual(ir["source_format"], "tde-with-tds")

    def test_tableau_utf16_descriptor_is_supported(self) -> None:
        xml = """<?xml version='1.0'?>
<datasource formatted-name='UTF16 Scores'>
  <connection class='textscan'><relation table='[DEMO].[ANALYTICS].[SCORES]' /></connection>
  <column name='[Score]' role='measure' aggregation='Sum' datatype='integer' />
</datasource>"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "scores.tds"
            source.write_bytes(xml.encode("utf-16"))
            ir = extract_tableau_ir({"request_id": "utf16", "source_path": str(source)})
        self.assertEqual(ir["metrics"][0]["normalized_expression"], "SUM(utf16_scores.score)")

    def test_world_tds_converts_to_schema_valid_candidate(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            response = convert_semantic(
                {
                    "request_id": "world-convert",
                    "source_path": str(EXAMPLES / "tableau/world.tds"),
                    "model_name": "world_indicators",
                    "source_map": {"World Indicators": "DEMO.ANALYTICS.WORLD_INDICATORS"},
                    "field_map": {"World Indicators": {"CO2 Emissions": "co2_tonnes"}},
                    "output_dir": directory,
                }
            )
            self.assertEqual(response["status"], "success")
            generated = yaml.safe_load(Path(response["model_path"]).read_text())
            manifest = json.loads(Path(response["manifest_path"]).read_text())
            self.assertEqual(validate_document(generated, SCHEMA), [])
            self.assertTrue(manifest["osi"]["schema_valid"])
            self.assertEqual(manifest["summary"]["metrics"], 24)
            self.assertEqual(
                generated["semantic_model"][0]["metrics"][0]["name"], "average_birth_rate"
            )

    def test_tableau_placeholder_source_map_remains_blocking(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            response = convert_semantic(
                {
                    "request_id": "world-placeholder",
                    "source_path": str(EXAMPLES / "tableau/world.tds"),
                    "source_map": {
                        "World Indicators": "REPLACE_WITH_DATABASE.SCHEMA.WORLD_INDICATORS"
                    },
                    "output_dir": directory,
                }
            )
            manifest = json.loads(Path(response["manifest_path"]).read_text())
            self.assertGreater(response["blocking_issue_count"], 0)
            self.assertEqual(manifest["status"], "review_required")

    def test_tableau_field_map_requires_unquoted_aliases(self) -> None:
        with self.assertRaisesRegex(ContractError, "unquoted SQL identifiers"):
            extract_tableau_ir(
                {
                    "request_id": "invalid-field-map",
                    "source_path": str(EXAMPLES / "tableau/world.tds"),
                    "field_map": {"Birth Rate": '"Birth Rate"'},
                }
            )

    def test_tableau_tde_requires_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            extract = Path(directory) / "orphan.tde"
            extract.write_bytes(b"TableauDataExtractPlaceholder")
            with self.assertRaisesRegex(ContractError, "same-named .tds"):
                extract_tableau_ir({"request_id": "orphan", "source_path": str(extract)})

    def test_tableau_namespaced_datasource_is_supported(self) -> None:
        xml = """<?xml version='1.0'?>
<t:datasource xmlns:t='urn:tableau' formatted-name='Namespaced Scores'>
  <t:connection class='textscan'>
    <t:relation name='scores' table='[DEMO].[ANALYTICS].[SCORES]' type='table' />
  </t:connection>
  <t:column name='[Score]' role='measure' aggregation='Sum' datatype='integer' />
  <t:column name='[Year]' role='dimension' datatype='date' />
</t:datasource>"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "scores.tds"
            source.write_text(xml, encoding="utf-8")
            ir = extract_tableau_ir({"request_id": "namespaced", "source_path": str(source)})
        self.assertEqual(ir["datasets"][0]["physical_source"], "DEMO.ANALYTICS.SCORES")
        self.assertEqual(ir["metrics"][0]["normalized_expression"], "SUM(namespaced_scores.score)")

    def test_end_to_end_generic_conversion_writes_candidate_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
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
            generated = yaml.safe_load(Path(response["model_path"]).read_text())
            manifest = json.loads(Path(response["manifest_path"]).read_text())
            self.assertEqual(validate_document(generated, SCHEMA), [])
            self.assertTrue(manifest["osi"]["schema_valid"])
            self.assertEqual(manifest["summary"]["metrics"], 1)
            self.assertEqual(manifest["refresh"]["status"], "new_model")
            self.assertGreater(manifest["refresh"]["summary"]["added"], 0)


if __name__ == "__main__":
    unittest.main()
