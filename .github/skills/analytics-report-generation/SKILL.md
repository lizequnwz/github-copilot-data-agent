---
name: analytics-report-generation
description: Render an accessible SVG chart or self-contained responsive HTML report from a validated aggregate result. Use only when the user explicitly requests one of those outputs.
allowed-tools: ["read", "search", "edit", "execute"]
---

# Analytics report generation

Apply the validation gate from `AGENTS.md`. Run `render-chart` and `render-report` from the
repository root with:

```bash
uv run python -m data_agent COMMAND --input REQUEST.json --output RESPONSE.json
```

Start from `examples/requests/render-chart.json` or `examples/requests/render-report.json`. The
Python renderers remain authoritative for request validation.

## Publication input gate

Require `validate-result` status `pass`, aggregate and non-restricted rows, `truncated: false`, and
finite values for every charted point. The publication input gate fails on row-level sensitive
data, an empty or truncated result, or a result whose grain was not validated.

## Choose the output branch

- **SVG chart**: use a line chart for an ordered time trend or a sorted bar chart for up to 15
  categories. When exact values matter more than shape, explain that a table or HTML report is the
  faithful output and use that branch with the user-requested format.
- **HTML report with chart**: complete the SVG chart branch, then pass the returned SVG and its
  complete underlying table to `render-report`.
- **HTML table report**: call `render-report` without `chart_svg` when a chart would misrepresent the
  result or exact values are primary.

## SVG chart branch

1. Set title, unit, period, labels, direct value labels, and a chart text alternative.
2. Set `value_format` before rendering when display formatting matters. Supported styles are
   number, currency, and percentage, with optional decimals, compact notation, and currency code.
3. Call `render-chart`; use its Python-rendered SVG as the chart artifact.
4. Return the SVG with the complete underlying aggregate table.

The chart publication gate passes only when `render-chart` returns `status: success`, the SVG has a
descriptive title and text alternative, every plotted point is represented in the underlying
table, and no active or remote content was introduced.

## HTML report branch

1. Set `column_formats` before rendering when table values need number, currency, or percentage
   formatting.
2. Include the direct finding, definitions, methodology, and useful caveats. Include semantic
   model, period, freshness, query ID, role, and SQL when available from a live query; mark missing
   evidence explicitly. For derived or ad hoc analysis, label the metric unpromoted and include its
   displayed formula, assumptions, source mode, and approved objects.
3. Write the HTML under `reports/generated/` with `render-report`.
4. Verify the generated file contains the expected title and rows, responsive viewport, skip link,
   query evidence, and chart title and text alternative when a chart is present.

The report publication gate passes only when `render-report` returns `status: success`, the output
path is under `reports/generated/`, every expected row is present, and all applicable verification
checks pass. The renderer owns semantic headings, keyboard focus, responsive tables, accessible
color and typography, light/dark and reduced-motion behavior, print styling, and exclusion of
remote or executable content; use the renderer rather than reimplementing those guarantees.
