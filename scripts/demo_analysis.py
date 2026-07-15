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
                "title": "Gross sales by region",
                "unit": "USD",
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
            "columns": ["Region", "Gross sales (USD)"],
            "rows": rows,
            "chart_svg": chart["svg"],
            "definitions": request["definitions"],
            "methodology": "Compile the shared gross_sales metric at region grain.",
            "caveats": request["notes"],
            "sql": analysis["sql"],
            "metadata": {
                "title": "Regional sales example",
                "semantic_model": analysis["model"],
                "period": analysis["period"]["label"],
                "result_grain": ", ".join(analysis["result_grain"]),
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
