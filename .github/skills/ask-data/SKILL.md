---
name: ask-data
description: Explore business questions through promoted OSI semantic models, compiler-generated read-only Snowflake SQL, default Markdown and Jupyter workspaces, charts, optional result validation, and evidence-backed HTML reports. Use for every Ask Data question, follow-up analysis, notebook, chart, or analytical report.
---

# Ask Data

Run the single Ask Data workflow from the repository root:

```bash
uv run data-agent ask --input REQUEST.json
```

## Workflow

1. Understand the immediate question well enough to form the next useful semantic plan. Ask only
   when a missing choice would materially change the analysis.
2. Diagnose coverage across `semantic/models/`. Select a promoted model that covers the required
   metrics, fields, and relationships.
3. If coverage is missing, return the structured gap and route to Semantic Setup. Never bypass the
   model with arbitrary SQL.
4. Use promoted metrics when they fit. Use request-scoped derived metrics, dimensions, time grains,
   or calculations over qualified promoted fields when exploration needs additional logic. Keep
   request-scoped logic visibly unpromoted.
5. Compile the semantic plan. The compiler owns sources, joins, parameterization, aliases, ordering,
   and the query limit.
6. Before live execution, display and confirm the non-secret Snowflake context. Execute only
   compiler-generated, parsed read-only SQL.
7. Lead with the useful finding or next experiment. Show the selected model, plan, generated SQL,
   result, provenance, truncation state, and whether result checks ran.
8. Create a Markdown/notebook workspace by default for every covered plan, including one that has
   not executed yet. Link the generated artifacts in the response.

Use `examples/ask-data/exploration.json` for the minimal runnable shape.

## Analysis flexibility

Plans may select promoted metrics and dimensions, run bounded detail queries, use richer filters,
group dates by a supported grain, apply aggregate filters, and add request-scoped percent-of-total,
rank, or running-total calculations. Prefer notebook-side transformations for experimental logic
that does not belong in generated SQL, and label those transformations clearly.

## Progressive details

- Read [references/notebook.md](references/notebook.md) when generating or revising a workspace.
- Read [references/validation.md](references/validation.md) when assurance is requested or useful.
- Read [references/reporting.md](references/reporting.md) before creating a chart or HTML report.

## Safety

Never display credentials or tokens. Preserve context confirmation, read-only SQL parsing,
model-bound sources, timeouts, cancellation, row-fetch limits, and result-byte limits. These are
runtime protections, not obstacles to exploratory iteration.
