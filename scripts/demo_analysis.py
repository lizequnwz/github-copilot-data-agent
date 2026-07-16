from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_agent.analysis import analyze
from data_agent.reporting.render import render_chart, render_report

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/analysis/sales-by-region.json"


def main() -> int:
    request = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    analysis = analyze(request)
    if analysis["status"] != "success":
        print(json.dumps(analysis, indent=2, sort_keys=True))
        return 2

    result = analysis["result"]
    columns = result["columns"]
    rows = result["rows"]
    region_index = columns.index("region")
    sales_index = columns.index("gross_sales")
    chart = render_chart(
        {
            "request_id": "offline-sales-chart",
            "spec": {
                "type": "bar",
                "title": "Completed-order gross sales by region",
                "unit": "USD, May–June 2026",
                "alt_text": (
                    "Completed-order gross sales by region for May and June 2026. "
                    "East leads at $128,000, followed by West at $104,500 and Central at $87,250."
                ),
                "value_format": {
                    "style": "currency",
                    "currency": "USD",
                    "decimals": 0,
                    "compact": True,
                },
                "data": [{"label": row[region_index], "value": row[sales_index]} for row in rows],
            },
        }
    )
    report = render_report(
        {
            "request_id": "offline-sales-report",
            "output_path": str(ROOT / "reports/generated/demo-sales-analysis.html"),
            "validation": analysis["result_validation"],
            "summary": request["answer"],
            "question": request["question"],
            "interpretation": {
                "metric": "Gross sales",
                "population": "Completed orders only",
                "dimensions": "Region",
                "filters": "Order status equals completed",
                "period": analysis["period"]["label"],
                "expected_result_grain": "One row per region",
                "semantic_model": analysis["model"],
                "requested_output": "Top regions, chart, table, and compiled SQL",
            },
            "validation_summary": {
                "semantic_grain": ", ".join(analysis["grain"]),
                "result_grain": ", ".join(analysis["result_grain"]),
                "rows_returned": len(rows),
                "logical_cap": analysis["max_rows"],
                "query_probe_limit": analysis["query_limit"],
                "truncated": "No" if not result["truncated"] else "Yes",
                "sql_validation": "Passed",
                "result_validation": "Passed",
            },
            "columns": ["Region", "Gross sales (USD)"],
            "rows": rows,
            "column_formats": {
                "Gross sales (USD)": {
                    "style": "currency",
                    "currency": "USD",
                    "decimals": 0,
                }
            },
            "chart_svg": chart["svg"],
            "chart_heading": "Regional contribution",
            "definitions": request["definitions"],
            "methodology": (
                "Resolve the shared gross_sales metric from demo_sales, filter to completed orders, "
                "apply an inclusive 2026-05-01 and exclusive 2026-07-01 time range, group by region, "
                "order by gross sales descending, fetch one row beyond the logical cap, then validate "
                "the returned region grain before interpretation."
            ),
            "caveats": request["notes"],
            "sql": analysis["sql"],
            "plan": analysis["normalized_plan"],
            "metadata": {
                "title": "Completed-order gross sales by region",
                "analysis_mode": "Ask Data",
                "semantic_model": analysis["model"],
                "period": analysis["period"]["label"],
                "semantic_grain": ", ".join(analysis["grain"]),
                "result_grain": ", ".join(analysis["result_grain"]),
                "rows_returned": len(rows),
                "max_rows": analysis["max_rows"],
                "query_limit": analysis["query_limit"],
                "truncated": result["truncated"],
                "query_id": "offline-synthetic-fixture",
                "role": "offline; no Snowflake connection",
                "data_freshness": "synthetic example",
            },
        }
    )
    _print_walkthrough(request, analysis, report)
    return 0


def _print_walkthrough(
    request: dict[str, Any], analysis: dict[str, Any], report: dict[str, Any]
) -> None:
    print(f"Question: {request['question']}")
    print(f"Answer: {request['answer']}")
    print(f"Model: {analysis['model']}")
    print(f"Period: {analysis['period']['label']}")
    print(f"Semantic grain: {', '.join(analysis['grain'])}")
    print(f"Result grain: {', '.join(analysis['result_grain'])}")
    print(f"Result limit: {analysis['max_rows']} rows (query limit {analysis['query_limit']})")
    print(f"Result validation: {analysis['result_validation']['status']}")
    print("SQL:")
    print(analysis["sql"])
    print(f"Report: {report['report_path']}")


if __name__ == "__main__":
    raise SystemExit(main())
