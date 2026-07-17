---
name: snowflake-analysis
description: Explore Snowflake questions with direct or model-assisted read-only SQL, editable notebooks, optional validation, and evidence-backed interpretation.
allowed-tools: ["read", "search", "edit", "execute"]
---

# Snowflake analysis

Apply the explore-first priorities and hard safety boundaries from `AGENTS.md`. Run helpers from the
repository root with:

```bash
uv run python -m data_agent COMMAND --input REQUEST.json --output RESPONSE.json
```

Use `examples/analysis/exploratory-sales.json` for the flexible SQL shape and
`examples/requests/render-workspace.json` for the Markdown/notebook workspace. Python handlers
remain authoritative for read-only execution and optional validation.

## Default: explore

1. Understand the immediate question well enough to write the next useful query. Ask only when a
   missing choice would make that query misleading.
2. Inspect promoted models when they are likely to help, but do not block exploration when the
   model is absent or incomplete.
3. Write explicit read-only Snowflake SQL. Literal filters, unpromoted calculations, queries without
   an explicit `LIMIT`, and incomplete business metadata are allowed in exploratory mode.
4. Use `analyze` with `analysis_mode: exploratory`. A request containing SQL and no model path also
   defaults to exploratory mode.
5. Execute after displaying and confirming the non-secret connection context. Show the returned
   table, query ID, effective context, truncation status, SQL, and useful observations.
6. Use `render-workspace` when the user wants to iterate, inspect code, adjust SQL, or chart results.
   The generated `analysis.md` is the readable record and `analysis.ipynb` is the editable workspace.

Exploratory output is explicitly unpromoted. Do not imply that a direct-SQL formula is a shared
business definition.

## Connection

Use `uv run python scripts/check_snowflake.py` for the first connection or when configuration
changes. It displays account, user, authentication mode, optional preferred context, OAuth
environment-variable availability, and effective context. Running it confirms the displayed
non-secret values for that check. Never display tokens.

For structured execution, use `config-check`, show the same values, and then connect with
`configuration_confirmed: true`. Browser SSO and environment-token OAuth are supported.

## Iterate in the notebook

The notebook starts from saved evidence and keeps live execution opt-in. Users may edit the
question, SQL, parameters, row-fetch target, table transformations, and charts. Rerun database work
through `analyze`; do not create a raw Snowflake connection in notebook cells.

Keep live queries read-only. Query timeouts, cancellation, fetch caps, and result-byte limits are
operational protections rather than analytical governance and remain active.

## Add assurance when it becomes valuable

Offer, but do not require, the following progression:

- Add `result_checks` or `validate_result: true` for emptiness, truncation, grain uniqueness, nulls,
  required columns, and numeric ranges.
- Replace repeated direct SQL with a promoted or request-scoped derived semantic plan.
- Use the legacy governed `ad_hoc` mode when a team explicitly wants allowlisted sources,
  parameterized predicates, declared formula and assumptions, and a bounded query contract.
- Promote a shared definition only through Semantic Setup.

When checks run, explain failures and rerun after correction. When checks do not run, label the
answer and report exploratory rather than withholding the analysis.

## Respond

Lead with the useful finding or next experiment. Include SQL, parameters when useful, returned-row
and truncation information, query ID and role for live work, and limitations that materially affect
interpretation. Link the Markdown/notebook workspace when generated. Avoid governance boilerplate
unless the user asks for validation or the work is moving toward a recurring or published metric.
