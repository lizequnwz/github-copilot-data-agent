# User workflow

## Ask a data question

Select the `data-analytics` Copilot agent and provide the business question in ordinary language:

> Compare gross sales by region for the last two complete months. Use the shared definition,
> explain any assumptions, and show the SQL.

The most useful request includes:

- metric or business outcome
- population or scope
- dimensions or comparison
- filters
- time range
- desired output, such as an answer, table, chart, or report

The agent searches `semantic/models/`, asks only material clarification questions, confirms the
Snowflake context before its first connection, validates and runs a bounded query, checks the
result, and leads with the answer.

For a live query, expect:

```text
Answer
Definition and grain
Filters and time range
Semantic model
Query ID and role
SQL
Caveats or follow-up questions
```

## First connection

Copy the example configuration and add the non-secret values:

```bash
cp snowflake_config.example.yaml snowflake_config.yaml
uv sync --extra dev --extra snowflake
```

Then ask:

> Check my Snowflake configuration and connect with browser SSO.

The agent displays account, user, authenticator, role, warehouse, database, and schema. After you
confirm them, browser SSO opens. The confirmation remains valid for the session unless the context
changes.

## Bring a semantic model from BI

Example prompts:

> Convert this unpacked Power BI TMDL directory into an OSI model and show me what needs review.

> Build an OSI model from this Tableau datasource. Use these source and field maps, then summarize
> translated and unsupported calculations.

> Refresh the generated model from this updated BI export and compare the manifest with the last
> conversion.

The `osi-semantic-model-builder` writes replaceable files to `semantic/generated/`. Review the
manifest, correct source maps when needed, and rerun the builder. Copy the reviewed OSI YAML into
`semantic/models/` to make it available to analysis.

## Request a report

Start with a validated analytical result, then ask:

> Turn this result into a bar chart and a self-contained HTML report.

Reports are written under `reports/generated/`. Query details are included when the result came
from Snowflake; offline examples use clearly labeled synthetic details.

