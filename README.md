# GitHub Copilot Snowflake Data Agent

This repository provides one GitHub Copilot agent for answering scoped business questions with
shared semantic models and read-only Snowflake queries. It also includes an OSI semantic model
builder that converts exported Power BI, Tableau, JSON, YAML, neutral IR, or existing Apache
Ossie metadata into models the analysis agent can use.

## What it solves

A user may know the business question but not the correct table, join, or metric expression. The
agent prefers a shared OSI definition, can calculate an explicitly unpromoted metric from promoted
fields, and can use validated text-to-SQL over promoted or explicitly allowlisted sources. It runs
inspectable SQL with browser SSO or environment-token OAuth, checks the result shape, and returns a
reproducible answer with the effective Snowflake context.

Typical request:

> Which regions drove gross sales last month? Use the shared gross sales definition and show the
> SQL.

The agent is designed to provide:

- consistent metric and dimension definitions from `semantic/models/` when available
- visibly labeled derived and ad hoc metrics when a shared metric does not cover the question
- explicit, bounded, read-only Snowflake queries
- result checks before interpretation
- direct answers with query details and useful caveats
- optional interactive charts and self-contained HTML reports with evidence-backed insights
- BI-to-OSI conversion for building and refreshing semantic models

## Choose your journey

- **Ask Data**: select `data-analytics`, ask a scoped question, review the displayed interpretation,
  and receive a validated answer with reproducible SQL.
- **Import a Model**: provide Tableau, Power BI, generic, neutral IR, or existing Ossie metadata and
  request **Semantic Setup**.
- **Review Definitions**: use the description-first Catalog and guided metric builder as a Business
  or Analyst reviewer; normal review does not require YAML or JSON editing.
- **Configure Snowflake**: choose browser SSO or environment-token OAuth, then confirm the
  non-secret preferred context.

This is an analyst-led GitHub Copilot workflow in which business stakeholders can participate in
definition review. It is not a standalone business portal, hosted service, or MCP server.

## Prerequisites

- Git with submodule support.
- Python 3.11 or newer and [`uv`](https://docs.astral.sh/uv/).
- A GitHub Copilot surface that supports repository agents and skills.
- A local browser for semantic review and, when selected, Snowflake browser SSO.
- For live analysis, Snowflake access capable of running the bounded read-only queries.

## How to use it

1. Open this repository in a GitHub Copilot-supported environment and select the
   `data-analytics` agent.
2. Ask a scoped business question with the metric, population, dimensions, filters, time range,
   and desired output.
3. Review the displayed metric or formula, population, dimensions, filters, period, expected result
   grain, source mode and sources, and requested output. The agent proceeds when these are
   unambiguous.
4. Confirm the displayed non-secret Snowflake authentication mode and preferred context before the
   first connection. The agent then uses browser SSO or OAuth, validated read-only SQL, bounded
   execution, and result checks.
5. Ask for a chart or self-contained HTML report only after the analytical result is validated.

Example trigger:

> Compare gross sales by region for the last two complete calendar months. Use the shared
> definition, include only completed orders, explain any assumptions, and show the SQL.

If the required model is not yet in `semantic/models/`, first ask the agent to convert and review
the BI semantic export. For Tableau, the normal input is a `.tds` datasource like
`examples/tableau/world.tds`, together with a source map and, when needed, a field map.

When a promoted model contains the needed fields but not the requested metric, the agent may use a
`derived_metrics` expression without changing the model. When other data is needed, add the fully
qualified Snowflake object to `access.allowed_objects`; the ad hoc result remains unpromoted and
must show its formula and assumptions.

See [User workflow](docs/WORKFLOW.md) for first-time setup, trigger options, prompt templates, the
Tableau `.tds` onboarding path, and expected responses.

## Try the offline walkthrough

Initialize the pinned Apache Ossie dependency, install the base dependencies, and run the complete
example without Snowflake:

```bash
git submodule update --init --recursive
uv sync --extra dev
uv run python scripts/demo_analysis.py
```

The walkthrough loads the two-table `semantic/models/demo_sales.yaml`, filters completed orders to
the fixed May-June 2026 acceptance period, orders regional gross sales, validates the SQL and
synthetic result rows, and writes
`reports/generated/demo-sales-analysis.html`.

The same example can be run through the typed command directly:

```bash
uv run python -m data_agent analyze \
  --input examples/analysis/sales-by-region.json \
  --output /tmp/sales-by-region.response.json
```

## Connect to Snowflake

```bash
cp snowflake_config.example.yaml snowflake_config.yaml
uv sync --extra dev --extra snowflake
```

Fill in account and user, choose `externalbrowser` or `oauth`, and optionally provide preferred
role, warehouse, database, and schema values. OAuth reads its access token from the environment
variable named by `oauth_token_env`; never put a token in YAML. The agent displays this non-secret
context for confirmation and reports effective-context differences as warnings.

Validate configuration and test the connection in one command. Running it explicitly confirms the
displayed non-secret context for that check:

```bash
uv run python scripts/check_snowflake.py
```

## Build an OSI model from BI metadata

The `osi-semantic-model-builder` skill is the model onboarding path. Its normal command creates a
deterministic raw model and opens a local review workspace. The Catalog keeps table and column
descriptions visible, provides per-table completeness and a next-missing queue, and saves related
edits directly from a persistent change bar. Navigation is limited to Catalog, Metrics, and
Advanced. The metric builder provides common aggregation templates while custom expressions and
business context stay collapsed until needed. The dismissible drawer contains mappings,
keys, relationships, expressions, synonyms, examples, and `ai_context` without requiring YAML.
**Apply and validate** compiles the saved draft into an in-memory audited patch, reruns the pinned
official validator, and promotes only a clean model after confirmation.

```bash
# Power BI TMDL
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py \
  tests/fixtures/powerbi --model-name demo_powerbi --review-ui

# Tableau .tds datasource (the normal Tableau semantic input)
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py \
  examples/tableau/world.tds --model-name world_indicators \
  --source-map examples/tableau/world-source-map.demo.json \
  --field-map examples/tableau/world-field-map.example.json --review-ui

# Generic semantic YAML
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py \
  tests/fixtures/generic/sales.yaml --model-name demo_generic --review-ui
```

The temporary server binds only to `127.0.0.1`; use `--no-open` for a headless launch. Interactive
review persists one draft plus the final model, review HTML, and conversion manifest under
`semantic/generated/`; intermediate decisions and patch files are not written. The static HTML can
download the draft for later use with `--review-decisions PATH`. Manual `--review-patch` remains an
advanced audit/debugging path.
Snowflake verification is optional through `--verify-snowflake` after configuration confirmation.
The workspace provides Business and Analyst views, structured context and expression editors,
translation decisions, relationship/key controls, and selected bulk translation review. A matching
`semantic/tests/<model>.yaml` competency fixture runs before a clean model can promote.
Key and relationship controls use physical source columns. Unsupported source constructs remain
excluded from executable OSI; an explicit **reviewed unsupported** decision preserves their
provenance while allowing the reviewed model to become promotion-ready.
See
[Semantic models](docs/SEMANTIC_MODELS.md) for the complete process.

## Project map

```text
.github/agents/                    Copilot data analytics agent
.github/skills/
  snowflake-analysis/              Question-to-answer workflow
  osi-semantic-model-builder/      BI export to OSI workflow and runnable builder
  analytics-report-generation/    Optional chart and HTML report workflow
data_agent/                         Local semantic, Snowflake, validation, and report helpers
semantic/models/                    OSI models searched by the analysis agent
semantic/generated/                 Replaceable conversion output
semantic/tests/                     Per-model semantic competency questions
ossie-main/                         Pinned Apache Ossie submodule: schema, validator, examples
examples/                           Source mappings and walkthrough inputs
reports/generated/                  Local generated output
scripts/                            Friendly example and conversion entry points
```

## Developer commands

```bash
uv run python scripts/validate_project.py
uv run python -m unittest discover -s tests -v
uv run ruff check .
uv run mypy data_agent
```

Complete typed-request examples are in
[User workflow](docs/WORKFLOW.md#typed-command-examples).
Runnable request files for search, compile, validation, analysis, and competency tests are also
available under `examples/`, including model-backed derived and allowlisted ad hoc metric examples.

The Snowflake connector is optional for the offline examples. The implementation and its current
boundaries are described in [Design](docs/DESIGN.md).
