---
name: snowflake-analysis
description: Set up this repository's local Snowflake connection and answer scoped data questions with semantic models, validated read-only SQL, bounded execution, and result checks. Use for environment setup, metadata discovery, query planning, Snowflake analysis, or interpreting query results.
allowed-tools: ["read", "search", "edit", "execute"]
---

# Snowflake analysis

## Start with the question

1. Identify the metric, dimensions, filters, population, time range, and desired output.
2. Ask only about ambiguity that would materially change the result.
3. Search `semantic/models/` with `osi-search`. Prefer a matching model and compile a structured
   plan with `osi-compile` when its fields and relationships cover the question.
4. Show the resolved metric, population, dimensions, filters, period, expected result grain,
   semantic model, and requested output. Proceed when unambiguous; ask only when a material choice
   remains.

## Connect when needed

1. If dependencies are missing, run `uv sync --extra dev --extra snowflake`.
2. If `snowflake_config.yaml` is missing, ask the user to copy
   `snowflake_config.example.yaml` and fill in its non-secret values.
3. Run `config-check`, display account, user, authenticator, role, warehouse, database, and schema,
   and ask the user to confirm them before the first connection in the session.
4. Reuse that confirmation until one of those values changes.
5. Run `connection-check` and stop if browser SSO fails or the effective role differs.

## Analyze

1. Use metadata discovery only when the semantic model does not answer the source question.
2. Plan the query before writing SQL. Use explicit columns and joins, confirm the result grain,
   parameterize values, and set a useful limit.
   - Use `time_range` with `field`, inclusive `start`, exclusive `end_exclusive`, and `label`.
   - Use `order_by` only for selected dimensions or metrics.
   - Treat `grain` as qualified semantic identifiers and `result_grain` as returned column names.
3. Run `validate-sql`, then `execute-readonly`.
4. Run `validate-result` for emptiness, truncation, required columns, duplicate grain, required
   nulls, and any known numeric ranges.
5. If validation fails, explain the evidence and correct the query before interpreting it.

## Respond

Lead with the direct answer. Then include the metric definition, filters, period, semantic model,
query ID, role, SQL, and meaningful caveats. Create a chart or HTML report only when requested.

Never weaken read-only checks, bypass failed SSO, or invent a metric definition to continue.
Never bypass an unsupported semantic-plan operation with manually authored analytical SQL. Explain
the missing compiler or model capability and ask for a narrower question or model enhancement.
