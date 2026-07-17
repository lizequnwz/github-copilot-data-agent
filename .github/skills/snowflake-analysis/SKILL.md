---
name: snowflake-analysis
description: Explore Snowflake questions through promoted OSI semantic models, generated read-only SQL, editable plan-driven notebooks, optional result validation, and evidence-backed interpretation.
allowed-tools: ["read", "search", "edit", "execute"]
---

# Snowflake analysis

Apply the semantic-model and safety invariants from `AGENTS.md`. Run helpers from the repository
root with:

```bash
uv run python -m data_agent COMMAND --input REQUEST.json --output RESPONSE.json
```

Use `examples/analysis/exploratory-sales.json` for the minimal exploratory shape and
`examples/requests/render-workspace.json` for the Markdown/notebook workspace.

## One Ask Data workflow

There are no user-facing analysis modes. Every question follows one path:

1. Understand the immediate question well enough to form the next useful semantic plan. Ask only
   when a missing choice would materially change that plan.
2. Search `semantic/models/` and select a promoted model that covers the required fields and
   relationships.
3. Use a promoted metric when it fits. Otherwise define a request-scoped `derived_metrics`
   expression over qualified fields in the promoted model. Mark derived metrics unpromoted.
4. Compile `model_path + plan` through `analyze` or `osi-compile`. The compiler owns sources, joins,
   filter parameterization, output aliases, ordering, and SQL row limit.
5. Show the selected model, metric provenance, plan, generated SQL, parameters, expected result
   grain, and requested output. Do not require exhaustive business metadata for exploration.
6. Execute after displaying and confirming the non-secret Snowflake context. Show the table, query
   ID, role, truncation status, and useful observations.
7. Use `render-workspace` when iteration would help. The Markdown record and notebook must preserve
   the semantic plan and generated SQL.

If no promoted model covers the question, identify the exact missing field, relationship, or metric
and route to Semantic Setup. Do not answer by bypassing the semantic layer with arbitrary SQL.

## Notebook iteration

Users edit the question, `MODEL_PATH`, semantic `PLAN`, filters, dimensions, ordering, or a
request-scoped derived expression. Rerunning calls `analyze`, which regenerates SQL from the model.
The generated SQL is visible evidence, not an editable execution source.

`USE_SAVED_RESPONSE` keeps existing evidence visible by default. Live execution remains opt-in
through `RUN_LIVE` and `CONFIGURATION_CONFIRMED`.

## Optional result validation

Exploration does not require result checks. When the user asks for more assurance or the analysis
stabilizes, set `validate_result: true` and add only useful checks:

- empty or truncated results;
- required columns and non-null values;
- duplicate rows at the expected result grain;
- known numeric ranges.

When checks do not run, label the result and report exploratory. When checks fail, explain the
evidence and revise the semantic plan. Validation changes the assurance level, not the source path:
SQL still comes from the same promoted model.

## Connection and safety

Use `uv run python scripts/check_snowflake.py` for the first connection or when configuration
changes. Never display tokens. Execute only compiler-generated, parsed read-only SQL. Preserve
timeouts, cancellation, fetch limits, result-byte limits, and explicit connection confirmation.

## Respond

Lead with the useful finding or next experiment. Include the semantic model, promoted or derived
metric provenance, generated SQL, parameters when useful, returned-row and truncation information,
query ID and role for live work, validation status, and material limitations. Link the
Markdown/notebook workspace when generated.
