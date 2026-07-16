from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from data_agent.reporting.render import render_chart, render_report

ROOT = Path(__file__).resolve().parents[1]


class ReportingTests(unittest.TestCase):
    def test_runnable_request_examples(self) -> None:
        chart_request = json.loads(
            (ROOT / "examples/requests/render-chart.json").read_text(encoding="utf-8")
        )
        chart = render_chart(chart_request)
        self.assertEqual(chart["status"], "success")

        report_request = json.loads(
            (ROOT / "examples/requests/render-report.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory(prefix="reports-") as directory:
            output = Path(directory) / "reports" / "example.html"
            report_request["output_path"] = str(output)
            report_request["chart_svg"] = chart["svg"]
            report_request["chart_heading"] = "Regional comparison"
            report = render_report(report_request)

        self.assertEqual(report["status"], "success")
        self.assertTrue(report["content_sha256"])

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
            output = Path(directory) / "reports" / "sales.html"
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


if __name__ == "__main__":
    unittest.main()
