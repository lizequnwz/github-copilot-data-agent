from __future__ import annotations

import json

from data_agent.reporting.render import render_chart, render_report


def main() -> int:
    rows = [["East", 128000], ["West", 104500], ["Central", 87250]]
    chart = render_chart(
        {
            "request_id": "report-demo-chart",
            "spec": {
                "type": "bar",
                "title": "Gross sales by region",
                "unit": "USD",
                "alt_text": "East leads gross sales, followed by West and Central.",
                "data": [{"label": row[0], "value": row[1]} for row in rows],
            },
        }
    )
    report = render_report(
        {
            "request_id": "report-demo",
            "output_path": "reports/generated/demo-sales-report.html",
            "validation": {"status": "pass"},
            "summary": "East leads the synthetic sales fixture at $128,000, 22% above West.",
            "columns": ["Region", "Gross sales (USD)"],
            "rows": rows,
            "chart_svg": chart["svg"],
            "definitions": {
                "Gross sales": "Sum of synthetic gross sales amount before returns.",
                "Region": "Synthetic sales territory attached to each order.",
            },
            "methodology": "Aggregate the certified demo gross_sales metric by orders.region.",
            "caveats": ["Synthetic fixture only; do not present as enterprise production data."],
            "sql": "SELECT orders.region, SUM(orders.gross_sales_amount) AS gross_sales FROM DEMO.ANALYTICS.ORDERS AS orders GROUP BY 1 ORDER BY 2 DESC LIMIT 100",
            "metadata": {
                "title": "Regional sales overview",
                "source_tier": "certified_osi_demo",
                "semantic_model": "demo_sales",
                "confidence": "high",
                "data_freshness": "2026-07-11",
                "query_id": "offline-demo",
                "role": "offline-fixture",
                "request_id": "report-demo",
            },
        }
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
