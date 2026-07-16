# Analytical renderer contracts

Run renderers from the repository root with one JSON request and one JSON response:

```bash
uv run python -m data_agent COMMAND --input REQUEST.json --output RESPONSE.json
```

Every request needs a stable `request_id`. The renderer accepts validated aggregate data only.

## SVG chart

Call `render-chart` with 1 to 100 aggregate points and a `bar` or `line` specification:

```json
{
  "request_id": "chart-sales",
  "spec": {
    "type": "bar",
    "title": "Completed-order gross sales by region",
    "unit": "USD",
    "alt_text": "East has the highest gross sales, followed by West and Central.",
    "value_format": {"style":"currency","currency":"USD","decimals":0,"compact":true},
    "data": [
      {"label":"East","value":128000},
      {"label":"West","value":104500},
      {"label":"Central","value":87250}
    ]
  }
}
```

Each point needs a string `label` and finite numeric `value`. Success is `status: success`; retain
`svg` and `content_sha256`. Use the returned SVG unchanged when passing it to `render-report`.

Number formats support `style` values `number`, `currency`, and `percentage`; `decimals` from 0 to
6; optional `compact`; and an optional currency code.

## HTML report

Call `render-report` with the passing `validate-result` response, complete table data, and an HTML
path under `reports/generated/`:

```json
{
  "request_id": "report-sales",
  "output_path": "reports/generated/sales-by-region.html",
  "metadata": {
    "title": "Completed-order gross sales by region",
    "semantic_model": "demo_sales",
    "period": "May through June 2026",
    "data_freshness": "2026-07-16",
    "query_id": "query-id",
    "role": "ANALYST_READONLY",
    "truncated": false
  },
  "validation": {"status":"pass","checks":{},"errors":[],"warnings":[]},
  "summary": "East recorded the highest completed-order gross sales.",
  "question": "Which region drove gross sales?",
  "columns": ["REGION","GROSS_SALES"],
  "rows": [["East",128000],["West",104500],["Central",87250]],
  "column_formats": {
    "GROSS_SALES": {"style":"currency","currency":"USD","decimals":0}
  },
  "definitions": {"Gross sales":"Sum of gross order amount before returns."},
  "methodology": "Compiled through the promoted OSI model and validated at region grain.",
  "caveats": [],
  "sql": "SELECT ...",
  "chart_heading": "Gross sales comparison",
  "chart_svg": "<svg returned by render-chart>",
  "interpretation": {"metric":"gross_sales","population":"completed orders"},
  "validation_summary": {"result":"pass","truncated":false},
  "plan": {"semantic_model":"demo_sales"}
}
```

`metadata.title`, `summary`, `validation.status: pass`, string `columns`, and matching row arrays are
required. Tables may contain at most 500 aggregate rows. `chart_svg` is optional; when present it
must replace the shown placeholder with the exact safe `svg` value returned by `render-chart`.

Success is `status: success`; retain `report_path` and `content_sha256`. Verify the file at
`report_path` contains the expected title and rows, viewport metadata, skip link, evidence fields,
and chart title and description when applicable.
