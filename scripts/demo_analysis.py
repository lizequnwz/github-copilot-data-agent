from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_agent.analysis import analyze
from data_agent.reporting.render import render_report

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
    chart_data = [{"label": row[region_index], "value": row[sales_index]} for row in rows]
    report = render_report(
        {
            "request_id": "offline-sales-report",
            "output_path": str(ROOT / "reports/generated/demo-sales-analysis.html"),
            "validation": analysis["result_validation"],
            "summary": request["answer"],
            "insights": [
                {
                    "title": "East leads the period",
                    "finding": "East is the largest completed-order gross-sales region.",
                    "evidence": "$128,000 in East versus $104,500 in West and $87,250 in Central.",
                    "why_it_matters": "East contributes 40% of the displayed regional total.",
                    "caveat": "This is an offline synthetic fixture, not a live commercial result.",
                },
                {
                    "title": "The lead is meaningful",
                    "finding": "East is 22.5% above the next-ranked region.",
                    "evidence": "The East–West gap is $23,500 on a West base of $104,500.",
                    "why_it_matters": "A ranking alone understates the size of the regional gap.",
                },
            ],
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
            "charts": [
                {
                    "heading": "Regional comparison",
                    "takeaway": "East leads West by $23,500 and Central by $40,750.",
                    "spec": {
                        "type": "bar",
                        "title": "Completed-order gross sales by region",
                        "unit": "USD, May–June 2026",
                        "value_format": {
                            "style": "currency",
                            "currency": "USD",
                            "decimals": 0,
                            "compact": True,
                        },
                        "data": chart_data,
                    },
                },
                {
                    "heading": "Contribution to total",
                    "takeaway": "The three regions add to $319,750, with East contributing first.",
                    "spec": {
                        "type": "waterfall",
                        "title": "Regional contributions to completed-order gross sales",
                        "unit": "USD, May–June 2026",
                        "value_format": {
                            "style": "currency",
                            "currency": "USD",
                            "decimals": 0,
                            "compact": True,
                        },
                        "data": chart_data,
                    },
                },
            ],
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
                "workflow": "Ask Data",
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
