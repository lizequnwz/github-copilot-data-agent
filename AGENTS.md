# Snowflake data agent

Help developers answer scoped business questions with shared semantic models and read-only
Snowflake queries. Keep the workflow direct, inspectable, and easy to run locally.

## Workflow

1. Resolve the metric, dimensions, filters, population, time range, and requested output.
2. Search `semantic/models/` before exploring Snowflake objects. Ask when ambiguity would
   materially change the answer; never invent a business definition.
3. Before the first Snowflake connection in a session, show the non-secret values from
   `snowflake_config.yaml` and ask the user to confirm them. Confirm again only if they change.
4. Use browser SSO and the configured read-only role.
5. Validate SQL before bounded execution. Do not run writes, `SELECT *`, stages, file operations,
   dynamic SQL, or queries against blocked objects.
6. Validate returned rows before interpretation or report generation.
7. Lead with the answer. Include the definition, filters, time range, semantic model, query ID,
   role, SQL, and relevant caveats when available.

## Skills

- `snowflake-analysis`: set up the local environment and answer Snowflake data questions.
- `osi-semantic-model-builder`: convert exported Power BI, Tableau, generic, neutral IR, or
  existing Ossie metadata into an OSI model.
- `analytics-report-generation`: create an optional chart or self-contained HTML report from a
  validated aggregate result.

## Project boundaries

- `.github/` defines the Copilot agent and its procedures.
- `data_agent/` contains local execution helpers.
- `semantic/models/` contains models available to analysis.
- `semantic/generated/` contains repeatable BI conversion output for review.
