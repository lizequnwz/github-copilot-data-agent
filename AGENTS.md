# Data analytics agent policy

Build a useful POC for governed Snowflake analysis. Prefer simple, reviewable behavior over unnecessary architecture.

## Required workflow

1. Understand the metric, dimensions, filters, population, time range, and requested output.
2. Search `semantic/certified/` for Open Semantic Interchange (OSI) definitions before exploring raw Snowflake objects.
3. Ask when ambiguity could materially change the answer. Never invent a business definition.
4. Before every Snowflake action, show the non-secret values from `snowflake_config.yaml` and ask the user to confirm them.
5. Use browser SSO and the configured read-only role. Invoke the setup skill if Python, `uv`, or the connector is unavailable.
6. Validate SQL before bounded execution. Never run write operations, `SELECT *`, stages, file operations, or blocked objects.
7. Validate the result before interpretation or report generation.
8. Return the answer with definitions, freshness, OSI source/model, Snowflake query ID, role, confidence, and caveats.

## Skills

- `snowflake-environment-setup`: prepare Python, `uv`, configuration, and browser SSO.
- `snowflake-readonly-query`: discover metadata and run validated, bounded queries.
- `osi-semantic-builder`: detect, extract, convert, validate, and review Power BI, Tableau, generic, neutral IR, or Apache Ossie semantic metadata.
- `result-validation`: check analytical results before use.
- `analytics-report-generation`: create accessible reports from validated results.

## Memory

- Search `memory/approved/` before proposing a new learning.
- New learnings go only to `memory/pending/` with evidence, source, scope, confidence, and likely owner.
- Never edit `memory/approved/` automatically. A human reviewer promotes or rejects proposals.
- Never store credentials, tokens, private configuration, or raw sensitive rows in memory.

## Trusted boundaries

- `AGENTS.md` and `.github/agents/` define behavior.
- `.github/skills/` defines procedures.
- `data_agent/` performs controlled actions.
- `semantic/` defines governed meaning.
- `memory/` stores reviewed or pending institutional learning.
