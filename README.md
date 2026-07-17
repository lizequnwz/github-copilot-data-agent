# GitHub Copilot Snowflake Data Exploration Agent

This repository provides a local GitHub Copilot agent for exploring business questions with
shared OSI semantic models, compiler-generated read-only Snowflake SQL, editable Jupyter notebooks,
Markdown analysis records, optional result validation, and self-contained reports. It also includes
an OSI semantic model builder for adding or improving model coverage.

## What it solves

A user starts with a question or hypothesis. The agent resolves a promoted semantic model, builds a
small semantic plan, generates SQL from model-defined sources and relationships, and helps inspect,
chart, and refine the result in a notebook. Semantic consistency is always present; formal result
checks are added only when useful.

Typical request:

> Which regions drove gross sales last month? Use the shared gross sales definition and show the
> SQL.

The agent is designed to provide:

- semantic-model-backed exploration without heavyweight upfront ceremony
- visible model, plan, generated SQL, results, query details, and useful caveats
- generated `analysis.md` and editable `analysis.ipynb` workspaces
- quick Python charts and self-contained HTML reports
- optional result checks as the work matures
- request-scoped derived metrics over promoted fields when a shared metric is missing
- hard read-only, credential, timeout, and local result-size protections
- BI-to-OSI conversion for building and refreshing semantic models

## Choose your journey

- **Explore Data**: select `data-analytics`, ask a question, inspect the semantic plan, generated
  SQL, and result, then iterate in chat or a generated notebook.
- **Validate a Result**: add focused result checks when assurance becomes useful.
- **Import a Model**: provide Tableau, Power BI, generic, neutral IR, or existing Ossie metadata and
  request **Semantic Setup**.
- **Review Definitions**: use the description-first Catalog and guided metric builder as a Business
  or Analyst reviewer; normal review does not require YAML or JSON editing.
- **Configure Snowflake**: choose browser SSO or environment-token OAuth, then confirm the
  non-secret preferred context.

The product has two top-level routes: **Ask Data** and **Semantic Setup**. Ask Data has one
semantic-model-first analysis flow. Exploration and validation are assurance states within that
flow, not separate modes.

This is an analyst-led GitHub Copilot workflow in which business stakeholders can participate in
definition review. It is not a standalone business portal, hosted service, or MCP server.

## Prerequisites

- Git with submodule support.
- Python 3.11 or newer and [`uv`](https://docs.astral.sh/uv/).
- A GitHub Copilot surface that supports repository agents and skills.
- A local browser for semantic review and, when selected, Snowflake browser SSO.
- For live analysis, Snowflake access capable of running read-only queries.

## How to use it

1. Open this repository in a GitHub Copilot-supported environment and select the
   `data-analytics` agent.
2. Ask a business question or state a hypothesis.
3. Review the selected promoted model and lightweight semantic plan. The agent asks only for choices
   needed to make the next plan useful.
4. Confirm the displayed non-secret Snowflake context before the first live connection.
5. Inspect the generated SQL and result, then iterate by editing the plan, filters, dimensions, or
   request-scoped derived metric.
6. Ask for a Markdown/notebook workspace, chart, or HTML report at any point. Add result checks later
   if the analysis needs more assurance.

Example trigger:

> Explore completed-order sales by region using the shared model. Show the generated SQL and create
> a notebook where I can adjust the semantic plan.

Every analysis uses a promoted model in `semantic/models/`. When no model covers the question, use
Semantic Setup to import or enhance one before querying. When the model has the needed fields but no
shared metric, the analysis may use an explicitly unpromoted derived expression over those fields.

See [User workflow](docs/WORKFLOW.md) for first-time setup, trigger options, prompt templates, the
Tableau `.tds` onboarding path, and expected responses.

## Try the exploratory walkthrough

Install the base dependencies and run the example without Snowflake:

```bash
uv sync --extra dev
uv run python scripts/demo_exploration.py
```

The walkthrough compiles the promoted `demo_sales` model against synthetic regional sales rows and
writes an editable local workspace:

```text
reports/generated/exploratory-sales/
  analysis.md
  analysis.ipynb
  analysis.request.json
  analysis.response.json
```

Open the notebook in VS Code or Jupyter. To install the optional notebook environment:

```bash
uv sync --extra notebook
uv run jupyter lab reports/generated/exploratory-sales/analysis.ipynb
```

Generate the same workspace through the typed command:

```bash
uv run python -m data_agent render-workspace \
  --input examples/requests/render-workspace.json \
  --output /tmp/render-workspace.response.json
```

The same semantic flow with explicit result checks remains available with
`uv run python scripts/demo_analysis.py`.

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
data_agent/reporting/workspace.py   Markdown and Jupyter workspace generation
semantic/models/                    OSI models searched by the analysis agent
semantic/generated/                 Replaceable conversion output
semantic/tests/                     Per-model semantic competency questions
ossie-main/                         Pinned Apache Ossie submodule: schema, validator, examples
examples/                           Source mappings and walkthrough inputs
reports/generated/                  Local notebooks, Markdown analysis, charts, and reports
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
Runnable request files for search, compile, exploration, validation, reporting, and competency
tests are available under `examples/`, including promoted and request-scoped derived metrics.

The Snowflake connector is optional for the offline examples. The implementation and its current
boundaries are described in [Design](docs/DESIGN.md).
