---
name: analytics-report-generation
description: Render an accessible SVG chart or self-contained responsive HTML report from exploratory or validated analytical results.
allowed-tools: ["read", "search", "edit", "execute"]
---

# Analytics report generation

Run `render-chart`, `render-report`, and `render-workspace` from the repository root:

```bash
uv run python -m data_agent COMMAND --input REQUEST.json --output RESPONSE.json
```

## Choose the artifact

- Use `render-workspace` for an editable Markdown and Jupyter analysis.
- Use an SVG line chart for time, a bar chart for category comparison, and a waterfall only when the
  values are an additive bridge.
- Use a self-contained HTML report when the user wants a polished, shareable narrative with charts,
  table, definitions, notes, and SQL.
- Prefer a table when exact values matter more than visual shape.

## Exploratory and validated reports

Reports may be created before formal result validation. When validation is absent or `not_run`, the
renderer labels the report **Exploratory · not validated**. A report with failed checks must not be
rendered until the failure is resolved or the user intentionally starts a new exploration.

When checks have passed, include their evidence and use the validated label. Do not invent
confidence, causality, freshness, or business definitions that the analysis did not establish.

## Narrative and visuals

Lead with the direct finding. Quantify useful ranks, shares, deltas, or trends supported by the
displayed rows. Keep insights non-redundant and distinguish observations from explanations.

Charts must have a title, text alternative, finite plotted values, and a complete underlying table.
HTML reports should include the question, SQL, useful context, data freshness when known, and
material caveats. The renderer owns accessibility, responsive behavior, light/dark and print styles,
interactive table controls, and exclusion of remote content.

Write generated artifacts under `reports/generated/`. Treat them as local analytical work unless
the user explicitly chooses to publish or commit them.
