---
name: snowflake-analysis
description: Analyze Snowflake questions through promoted OSI semantic models. Use for question interpretation, local connection setup, semantic planning, bounded read-only execution, result validation, metadata diagnosis, or evidence-backed interpretation.
allowed-tools: ["read", "search", "edit", "execute"]
---

# Snowflake analysis

Apply the semantic, connection, and validation gates from `AGENTS.md`. Run helpers from the
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
2. Search `semantic/models/` with `osi-search` and select a model only when its fields,
   relationships, and metric definitions cover the question.
3. Compile a structured plan with `osi-compile`. Treat compiler support as part of the semantic
   gate; on an unsupported operation, explain the gap and offer a narrower question or model
   enhancement.
4. Show the resolved metric, population, dimensions, filters, period, expected result grain,
   semantic model, and requested output. Ask one focused question only when a remaining ambiguity
   would materially change the result.

The interpretation gate passes only when all eight displayed fields are explicit and
`osi-compile` returns `status: success` with SQL, parameters, result columns, and result grain.

## Connection gate

1. If dependencies are missing, run `uv sync --extra dev --extra snowflake`.
2. If `snowflake_config.yaml` is missing, ask the user to copy
   `snowflake_config.example.yaml` and fill in its non-secret values.
3. Run `config-check`, display account, user, authenticator, role, warehouse, database, and schema,
   and ask the user to confirm them before the first connection in the session.
4. Reuse that confirmation until one of those values changes.
5. Run `connection-check` with the confirmed context.

The connection gate passes only when `config-check` returns `status: ready`, the displayed context
is confirmed for the current values, and `connection-check` returns `status: success` with an
effective role matching the configured role. Report SSO failure or `context_mismatch` as blocking
evidence.

## Execution gate

1. Use the SQL and parameters returned by `osi-compile`. Use metadata discovery only to diagnose a
   model mapping gap; raw metadata does not define an analytical metric.
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

Lead with the direct answer. Then include the metric definition, filters, period, semantic model,
query ID, role, SQL, and meaningful caveats. Mark any unavailable evidence explicitly. Return the
validated aggregate evidence to the custom agent when the requested output includes reporting.
