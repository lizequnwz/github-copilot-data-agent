---
name: snowflake-analysis
description: Analyze Snowflake questions through promoted OSI semantic models. Use for question interpretation, local connection setup, semantic planning, bounded read-only execution, result validation, metadata diagnosis, or evidence-backed interpretation.
allowed-tools: ["read", "search", "edit", "execute"]
---

# Snowflake analysis

Apply the source and metric, connection, and validation gates from `AGENTS.md`. Run helpers from the
repository root with:

```bash
uv run python -m data_agent COMMAND --input REQUEST.json --output RESPONSE.json
```

Start semantic requests from `examples/requests/osi-search.json` and
`examples/requests/osi-compile.json`; use `examples/analysis/sales-by-region.json` for the complete
offline analysis shape. The Python handlers remain authoritative for request validation.

## Choose the branch

- **Answer a question**: complete every gate below.
- **Set up or test the connection**: complete the connection gate, report its evidence, and stop.
- **Diagnose model coverage**: complete semantic search and bounded metadata discovery, identify the
  exact model gap, and stop without answering the business question from raw metadata.

## Interpretation gate

1. Identify the metric, dimensions, filters, population, time range, and desired output.
2. Search `semantic/models/` with `osi-search`, then choose the first applicable source mode:
   - **Promoted**: use a promoted metric and the model compiler.
   - **Derived**: when promoted fields and relationships cover the question, define an explicitly
     unpromoted `derived_metrics` expression with a description and assumptions, then use the model
     compiler.
   - **Ad hoc**: when the question needs other approved data, generate explicit text-to-SQL and
     validate it through `analyze` with `analysis_mode: ad_hoc`. Sources must be either physical
     sources from promoted models or configured `access.allowed_objects`.
3. For promoted or derived mode, compile a structured plan with `osi-compile`. For ad hoc mode,
   require an explicit metric name, formula, description, assumptions, result grain, positional
   parameters, and all eight interpretation fields before validating the proposed SQL.
4. Show the resolved metric or formula, population, dimensions, filters, period, expected result
   grain, source mode and sources, and requested output. Mark derived and ad hoc metrics as
   unpromoted. Ask one focused question only when a remaining ambiguity would materially change the
   result.

The interpretation gate passes only when all eight displayed fields are explicit and
either `osi-compile` returns `status: success` for promoted/derived mode or `analyze` returns
`status: planned` for ad hoc mode, with SQL, parameters, result columns, and result grain.

## Connection gate

1. If dependencies are missing, run `uv sync --extra dev --extra snowflake`.
2. If `snowflake_config.yaml` is missing, ask the user to copy
   `snowflake_config.example.yaml` and fill in its non-secret values. Use `externalbrowser` for
   browser SSO or `oauth` with `oauth_token_env`; never place the token itself in YAML.
3. Prefer the one-command diagnostic: `uv run python scripts/check_snowflake.py`. It displays
   account, user, authentication mode, optional preferred context, OAuth environment-variable
   availability, and the effective connected context. Running this explicit command confirms the
   displayed non-secret context for the check. Never display the token value.
4. For structured automation, use `config-check` followed by `connection-check` with
   `configuration_confirmed: true` after displaying the same values. Reuse confirmation until one
   of those values changes.

The connection gate passes when the diagnostic reports `Status: connected`, or when `config-check`
returns `status: ready` and `connection-check` returns `status: success` for confirmed values. Configured
role, warehouse, database, and schema are preferred defaults: report effective-context differences
as warnings instead of rejecting a valid connection. Authentication failures remain blocking.

## Execution gate

1. Use the SQL and parameters returned by `osi-compile` or validated by the ad hoc `analyze` plan.
   Metadata may support an explicitly unpromoted calculation but does not create a shared business
   definition.
2. Confirm explicit projections and joins, the compiled result grain, parameterized values, and a
   numeric `max_rows` no greater than the configured cap.
   - Use `time_range` with `field`, inclusive `start`, exclusive `end_exclusive`, and `label`.
   - Use `order_by` only for selected dimensions or metrics.
   - Treat `grain` as qualified semantic identifiers and `result_grain` as returned column names.
3. Run `validate-sql`, then `execute-readonly`.
4. Run `validate-result` for emptiness, truncation, required columns, duplicate grain, required
   nulls, and any known numeric ranges. Snowflake normally returns unquoted column names in
   uppercase; validation matches those names case-insensitively to the semantic compiler's
   lowercase aliases while preserving the returned names in query evidence.
5. On a validation failure, explain the evidence, correct the plan or query through the owning
   semantic path, and rerun the failed checks.

The execution gate passes only when `validate-sql` reports valid read-only SQL,
`execute-readonly` returns `status: success` with `truncated: false`, and `validate-result` returns
`status: pass` for every requested check.

## Respond

Lead with the direct answer. Then include the metric definition or ad hoc formula, source mode,
filters, period, semantic model or approved objects, assumptions, query ID, role, SQL, and meaningful
caveats. Mark derived and ad hoc metrics as unpromoted and mark unavailable evidence explicitly.
Return the validated aggregate evidence to the custom agent when the requested output includes
reporting.
