# GitHub Copilot Snowflake Data Agent

This repository provides one GitHub Copilot agent for answering scoped business questions with
shared semantic models and read-only Snowflake queries. It also includes an OSI semantic model
builder that converts exported Power BI, Tableau, JSON, YAML, neutral IR, or existing Apache
Ossie metadata into models the analysis agent can use.

## What it solves

A user may know the business question but not the correct table, join, or metric expression. The
agent uses a small OSI model to resolve those details, prepares inspectable Snowflake SQL, runs it
with browser SSO and a read-only role, checks the result shape, and returns a reproducible answer.

Typical request:

> Which regions drove gross sales last month? Use the shared gross sales definition and show the
> SQL.

The agent is designed to provide:

- consistent metric and dimension definitions from `semantic/models/`
- explicit, bounded, read-only Snowflake queries
- result checks before interpretation
- direct answers with query details and useful caveats
- optional charts and self-contained HTML reports
- BI-to-OSI conversion for building and refreshing semantic models

## Choose your journey

- **Ask Data**: select `data-analytics`, ask a scoped question, review the displayed interpretation,
  and receive a validated answer with reproducible SQL.
- **Import a Model**: provide Tableau, Power BI, generic, neutral IR, or existing Ossie metadata and
  request **Semantic Setup**.
- **Review Definitions**: open the guided workspace as a Business or Analyst reviewer; normal
  review does not require YAML or JSON editing.
- **Configure Snowflake**: fill in the non-secret local context and confirm it before browser SSO.

This is an analyst-led GitHub Copilot workflow in which business stakeholders can participate in
definition review. It is not a standalone business portal, hosted service, or MCP server.

## Prerequisites

- Git with submodule support.
- Python 3.11 or newer and [`uv`](https://docs.astral.sh/uv/).
- A GitHub Copilot surface that supports repository agents and skills.
- A local browser for semantic review and Snowflake browser SSO.
- For live analysis, Snowflake access through the configured read-only role and warehouse.

## How to use it

1. Open this repository in a GitHub Copilot-supported environment and select the
   `data-analytics` agent.
2. Ask a scoped business question with the metric, population, dimensions, filters, time range,
   and desired output.
3. Review the displayed metric, population, dimensions, filters, period, expected result grain,
   semantic model, and requested output. The agent proceeds when these are unambiguous.
4. Confirm the displayed non-secret Snowflake context before the first connection. The agent then
   uses browser SSO, validated read-only SQL, bounded execution, and result checks.
5. Ask for a chart or self-contained HTML report only after the analytical result is validated.

Example trigger:

> Compare gross sales by region for the last two complete calendar months. Use the shared
> definition, include only completed orders, explain any assumptions, and show the SQL.

If the required model is not yet in `semantic/models/`, first ask the agent to convert and review
the BI semantic export. For Tableau, the normal input is a `.tds` datasource like
`examples/tableau/world.tds`, together with a source map and, when needed, a field map.

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

Fill in the non-secret context in the local configuration file, select the `data-analytics`
Copilot agent, and ask a data question. The agent displays the connection context for confirmation
before the first connection and uses browser SSO.

## Build an OSI model from BI metadata

The `osi-semantic-model-builder` skill is the model onboarding path. Its normal command creates a
deterministic raw model and opens a local review workspace. Business users and analysts can edit
meaning, mappings, keys, relationships, expressions, descriptions, synonyms, examples, and
`ai_context` without editing YAML. **Apply and validate** compiles their decisions into an audited
patch, reruns the pinned official validator, and promotes only a clean model after confirmation.

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

The temporary server binds only to `127.0.0.1`; use `--no-open` for a headless launch. Draft,
decisions, audited patch, final model, review HTML, and manifest artifacts stay under
`semantic/generated/`. The static HTML can download decisions for later use with
`--review-decisions PATH`. Manual `--review-patch` remains an advanced audit/debugging path.
Snowflake verification is optional through `--verify-snowflake` after configuration confirmation.
The workspace provides Business and Analyst views, structured context and expression editors,
translation decisions, relationship/key controls, and selected bulk translation review. A matching
`semantic/tests/<model>.yaml` competency fixture runs before a clean model can promote.
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
available under `examples/`.

The Snowflake connector is optional for the offline examples. The implementation and its current
boundaries are described in [Design](docs/DESIGN.md).
