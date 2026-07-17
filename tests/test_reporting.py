from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from data_agent.ask.service import ask_data
from data_agent.io import ContractError
from data_agent.ask.report import render_chart, render_report
from data_agent.ask.workspace import render_analysis_workspace

ROOT = Path(__file__).resolve().parents[1]


class ReportingTests(unittest.TestCase):
    def test_exploratory_workspace_contains_markdown_notebook_and_evidence(self) -> None:
        analysis_request = json.loads(
            (ROOT / "examples/ask-data/exploration.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory(prefix="workspace-") as directory:
            output = Path(directory) / "workspaces" / "analysis" / "exploration"
            result = render_analysis_workspace(
                {
                    "request_id": "workspace",
                    "output_dir": str(output),
                    "analysis_request": analysis_request,
                }
            )
            markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
            notebook = json.loads(Path(result["notebook_path"]).read_text(encoding="utf-8"))
            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "success")
        self.assertIn("Result validation: `not_run`", markdown)
        self.assertIn("Semantic model: `demo_sales`", markdown)
        self.assertIn("SUM(orders.gross_sales_amount)", markdown)
        self.assertEqual(notebook["nbformat"], 4)
        self.assertTrue(any(cell["cell_type"] == "code" for cell in notebook["cells"]))
        notebook_source = "".join(
            "".join(cell.get("source", [])) for cell in notebook["cells"]
        )
        self.assertIn("PLAN =", notebook_source)
        self.assertNotIn("SQL =", notebook_source)
        self.assertNotIn("USE_SAVED_RESPONSE", notebook_source)
        self.assertIn("PLAN_CHANGED", notebook_source)
        self.assertEqual(manifest["manifest_version"], "1.0")
        self.assertEqual(manifest["model"]["name"], "demo_sales")
        self.assertTrue(manifest["model"]["sha256"])
        self.assertTrue(manifest["plan"]["sha256"])

    def test_exploratory_report_is_allowed_and_clearly_labeled(self) -> None:
        with tempfile.TemporaryDirectory(prefix="reports-") as directory:
            output = Path(directory) / "workspaces" / "analysis" / "exploratory.html"
            result = render_report(
                {
                    "request_id": "exploratory-report",
                    "output_path": str(output),
                    "summary": "East leads in this exploratory result.",
                    "columns": ["region", "sales"],
                    "rows": [["East", 120], ["West", 90]],
                    "metadata": {"title": "Exploratory sales"},
                }
            )
            document = output.read_text(encoding="utf-8")

        self.assertEqual(result["status"], "success")
        self.assertIn("Exploratory · not validated", document)
        self.assertIn("Exploratory analysis · Ask Data", document)
        self.assertNotIn("Validated analysis · Ask Data", document)

    def test_runnable_request_examples(self) -> None:
        request = json.loads(
            (ROOT / "examples/ask-data/report.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory(prefix="workspaces-") as directory:
            request["workspace_dir"] = str(
                Path(directory) / "workspaces" / "analysis" / "report"
            )
            response = ask_data(request)
            report_path = Path(response["artifacts"]["report"])
            self.assertTrue(report_path.is_file())
            manifest_path = Path(response["artifacts"]["manifest"])
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["artifacts"]["report"], str(report_path))
            self.assertEqual(
                manifest["narrative"]["summary"],
                "East leads completed-order gross sales in the synthetic example.",
            )

        self.assertEqual(response["status"], "success")

    def test_planned_analysis_creates_an_editable_workspace_by_default(self) -> None:
        request = json.loads(
            (ROOT / "examples/ask-data/advanced-plan.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory(prefix="workspaces-") as directory:
            request["workspace_dir"] = str(
                Path(directory) / "workspaces" / "analysis" / "planned"
            )
            response = ask_data(request)
            notebook = Path(response["artifacts"]["notebook"])
            manifest = json.loads(
                Path(response["artifacts"]["manifest"]).read_text(encoding="utf-8")
            )

            self.assertTrue(notebook.is_file())
            self.assertEqual(response["status"], "planned")
            self.assertEqual(manifest["query"]["sql"], response["analysis"]["sql"])
            self.assertIsNone(manifest["result"])

    def test_chart_and_html_report(self) -> None:
        chart = render_chart(
            {
                "request_id": "chart",
                "spec": {
                    "type": "bar",
                    "title": "Sales by region",
                    "unit": "USD",
                    "value_format": {
                        "style": "currency",
                        "currency": "USD",
                        "decimals": 0,
                    },
                    "data": [
                        {"label": "East", "value": 120},
                        {"label": "West", "value": 90},
                    ],
                },
            }
        )
        self.assertIn("aria-labelledby", chart["svg"])
        with tempfile.TemporaryDirectory(prefix="reports-") as directory:
            output = Path(directory) / "workspaces" / "analysis" / "sales.html"
            result = render_report(
                {
                    "request_id": "report",
                    "output_path": str(output),
                    "validation": {"status": "pass"},
                    "summary": "East leads West in the fixture.",
                    "question": "Which region leads sales?",
                    "interpretation": {
                        "metric": "Sales",
                        "population": "All fixture orders",
                        "expected_result_grain": "One row per region",
                    },
                    "validation_summary": {
                        "semantic_grain": "orders.region",
                        "result_grain": "region",
                        "truncated": "No",
                    },
                    "columns": ["region", "sales"],
                    "rows": [["East", 120], ["West", 90]],
                    "column_formats": {
                        "sales": {
                            "style": "currency",
                            "currency": "USD",
                            "decimals": 0,
                        }
                    },
                    "chart_svg": chart["svg"],
                    "definitions": {"sales": "Fixture sales amount"},
                    "methodology": "Aggregate sales by region.",
                    "caveats": ["Synthetic data"],
                    "plan": {
                        "semantic_model": "demo_sales",
                        "metric_ids": ["gross_sales"],
                        "dimensions": ["orders.region"],
                    },
                    "metadata": {
                        "title": "Sales report",
                        "semantic_model": "demo_sales",
                        "data_freshness": "2026-07-11",
                        "period": "Last complete month",
                        "truncated": False,
                        "generated_at": "2026-07-15T12:00:00+00:00",
                        "query_id": "offline-fixture",
                        "role": "offline",
                        "request_id": "report",
                    },
                }
            )
            self.assertEqual(result["status"], "success")
            document = output.read_text(encoding="utf-8")
            self.assertIn("Skip to report", document)
            self.assertIn("prefers-color-scheme:dark", document)
            self.assertIn("$120", document)
            self.assertIn("Period: Last complete month", document)
            self.assertIn("Generated: 2026-07-15T12:00:00+00:00", document)
            self.assertIn("Resolved question", document)
            self.assertIn("Execution contract", document)
            self.assertIn("Which region leads sales?", document)
            self.assertIn("Show normalized semantic plan", document)
            self.assertIn("Complete result", document)
            self.assertNotIn('fill="#ffffff"', chart["svg"])

    def test_multi_series_and_waterfall_charts_are_accessible(self) -> None:
        line = render_chart(
            {
                "request_id": "series",
                "spec": {
                    "type": "line",
                    "title": "Actual and plan",
                    "series": [
                        {
                            "name": "Actual",
                            "data": [
                                {"label": "May", "value": 100},
                                {"label": "June", "value": 120},
                            ],
                        },
                        {
                            "name": "Plan",
                            "data": [
                                {"label": "May", "value": 95},
                                {"label": "June", "value": 110},
                            ],
                        },
                    ],
                },
            }
        )
        self.assertIn('data-series-toggle="0"', line["svg"])
        self.assertIn('data-chart-point', line["svg"])
        self.assertIn('tabindex="0"', line["svg"])
        self.assertIn('stroke-dasharray', line["svg"])

        waterfall = render_chart(
            {
                "request_id": "waterfall",
                "spec": {
                    "type": "waterfall",
                    "title": "Revenue bridge",
                    "data": [
                        {"label": "New", "value": 30},
                        {"label": "Churn", "value": -10},
                        {"label": "Expansion", "value": 8},
                    ],
                },
            }
        )
        self.assertIn("running total", waterfall["svg"])

    def test_structured_insights_charts_and_table_interactions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="reports-") as directory:
            output = Path(directory) / "workspaces" / "analysis" / "interactive.html"
            result = render_report(
                {
                    "request_id": "interactive",
                    "output_path": str(output),
                    "validation": {"status": "pass"},
                    "summary": "East leads the validated result.",
                    "columns": ["region", "sales"],
                    "rows": [["East", 120], ["West", 90]],
                    "insights": [
                        {
                            "title": "Concentration",
                            "finding": "East contributes the most sales.",
                            "evidence": "East is 33% above West ($120 versus $90).",
                            "why_it_matters": "Regional planning should account for the gap.",
                            "caveat": "The fixture contains two regions.",
                        }
                    ],
                    "charts": [
                        {
                            "heading": "Regional comparison",
                            "takeaway": "East leads West by $30.",
                            "spec": {
                                "type": "bar",
                                "title": "Sales by region",
                                "data": [
                                    {"label": "East", "value": 120},
                                    {"label": "West", "value": 90},
                                ],
                            },
                        }
                    ],
                    "metadata": {"title": "Interactive sales report", "truncated": False},
                }
            )
            document = output.read_text(encoding="utf-8")

        self.assertEqual(result["status"], "success")
        self.assertIn("What the evidence says", document)
        self.assertIn("Regional planning should account for the gap", document)
        self.assertIn('data-chart-container', document)
        self.assertIn('data-reset-chart', document)
        self.assertIn('id="tableFilter"', document)
        self.assertIn('aria-sort="none"', document)
        self.assertIn("toggleSeries", document)
        self.assertNotIn("https://", document)

    def test_rich_report_contract_rejects_unsupported_shapes(self) -> None:
        with self.assertRaisesRegex(ContractError, "exactly one series"):
            render_chart(
                {
                    "request_id": "invalid-waterfall",
                    "spec": {
                        "type": "waterfall",
                        "series": [
                            {"name": "A", "data": [{"label": "x", "value": 1}]},
                            {"name": "B", "data": [{"label": "x", "value": 2}]},
                        ],
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
