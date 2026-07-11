---
name: snowflake-readonly-query
description: Discover Snowflake metadata and execute a validated, bounded, read-only analytical query. Use for Snowflake data questions after configuration is ready.
---

# Procedure

1. Resolve the requested metric, dimensions, filters, population, time range, and grain. Ask about material ambiguity.
2. Search certified OSI models before raw metadata. Label raw exploration as exploratory.
3. Read `snowflake_config.yaml`, show the non-secret context, and ask the user to confirm it for this action.
4. Use `search-objects`, `describe-object`, `sample-values`, or `profile-table` only when needed. Sensitive-looking sampling requires explicit policy and authorization.
5. Create a structured query plan before SQL. Prefer deterministic `osi-compile` when OSI coverage exists.
6. Use explicit columns and joins, confirm grain and join cardinality, and apply a bounded result.
7. Run `validate-sql`, then `execute-readonly` using JSON request and response files. Never put SQL in a shell argument.
8. Invoke `result-validation` before interpreting the output.

# Stop conditions

Stop on unconfirmed configuration, failed browser SSO, wrong role, ambiguous semantics, unsafe SQL, blocked objects, truncation, or result-validation failure. Never weaken controls to continue.

# Output

Return the direct answer, definitions, filters, date range, data freshness, OSI model/source tier, query ID, role, confidence, and caveats.
