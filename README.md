# GitHub Copilot Snowflake Data Agent

A local GitHub Copilot data agent with one semantic-model-first analysis workflow:

```text
Question → promoted model → semantic plan → generated SQL → result
         → Markdown + notebook → optional validation → optional HTML report
```

The product has two routes:

- **Ask Data** explores business questions and creates inspectable analytical workspaces.
- **Semantic Setup** creates or improves promoted Apache Ossie semantic models.

Exploratory and validated are assurance states inside Ask Data, not separate modes. Every analytical
query uses a promoted model; result checks are optional until additional assurance is useful.

## Quick start

```bash
git submodule update --init --recursive
uv sync --extra dev --extra notebook
uv run data-agent ask --input examples/ask-data/exploration.json
```

The command uses the promoted `demo_sales` model and synthetic rows, then writes:

```text
workspaces/analysis/sales-exploration/
  analysis.json
  analysis.md
  analysis.ipynb
```

Open the notebook in VS Code or Jupyter:

```bash
uv run jupyter lab workspaces/analysis/sales-exploration/analysis.ipynb
```

The notebook exposes simple semantic inputs, regenerates SQL when the plan changes, displays a
pandas result and chart, and keeps live Snowflake execution explicit.

## Ask Data

Select the repository's `data-analytics` Copilot agent and ask a normal business question:

> Explore completed-order sales by region. Show the semantic plan and generated SQL, and create a
> notebook I can refine.

The agent diagnoses model coverage, selects a promoted model, generates SQL, and creates a workspace
for substantive results. Plans support:

- promoted and request-scoped derived metrics;
- dimensions and request-scoped derived dimensions;
- bounded detail queries;
- comparison, list, null, and text filters;
- day, week, month, quarter, and year time grains;
- aggregate filters;
- percent-of-total, rank, and running-total calculations;
- optional grain, completeness, null, and range checks.

Run a richer offline plan:

```bash
uv run data-agent ask --input examples/ask-data/advanced-plan.json --no-workspace
```

Diagnose missing coverage:

```bash
uv run data-agent model coverage --input examples/ask-data/coverage-gap.json
```

Coverage gaps identify missing metrics, fields, or relationships and route to Semantic Setup. Ask
Data never bypasses the semantic model with arbitrary SQL.

See [Ask Data](docs/ASK_DATA.md).

## Connect to Snowflake

```bash
cp snowflake_config.example.yaml snowflake_config.yaml
uv sync --extra snowflake
uv run data-agent doctor
uv run data-agent doctor --connect
```

`doctor` displays only non-secret configuration. The explicit `--connect` command confirms that
displayed context for the diagnostic. Browser SSO and environment-token OAuth are supported; tokens
never belong in YAML or output.

Live Ask Data requests set `execute: true` and confirm the displayed context. Runtime protections
include parsed read-only SQL, model-bound sources, timeouts, cancellation, fetch limits, and result
byte limits.

## Semantic Setup

The normal setup command converts a supported source and opens guided review:

```bash
uv run data-agent model setup SOURCE --model-name MODEL
```

Supported sources include unpacked Power BI TMDL, Tableau `.tds`/`.twb`, generic semantic JSON or
YAML, neutral semantic IR, and existing Ossie documents. Generated model work stays under
`workspaces/models/`; clean reviewed models promote to `semantic/models/` only after destination
confirmation and validation.

Example Tableau setup:

```bash
uv run data-agent model setup examples/semantic-setup/tableau/world.tds \
  --model-name world_indicators \
  --source-map examples/semantic-setup/tableau/world-source-map.demo.json \
  --field-map examples/semantic-setup/tableau/world-field-map.example.json
```

See [Semantic Setup](docs/SEMANTIC_SETUP.md).

## Public commands

```text
data-agent ask       Run semantic analysis and create artifacts
data-agent doctor    Check Snowflake configuration and connection
data-agent model     Diagnose coverage or set up semantic models
```

Low-level deterministic operations remain available under `data-agent advanced` for automation and
debugging, but skills and normal users should use the three product commands.

## Repository structure

```text
.github/agents/                Copilot route selection
.github/skills/
  ask-data/                    Analysis, notebook, validation, and reporting behavior
  semantic-setup/              Model import, review, validation, and promotion behavior
data_agent/
  ask/                         Ask Data compiler, execution, workspace, and reports
  setup/                       Source conversion, review, verification, and promotion
  models.py                    Shared promoted-model loading and search
  snowflake.py                 Connection and read-only execution
  sql_safety.py                SQL parsing and safety
semantic/models/               Promoted models
semantic/tests/                Semantic competency plans
workspaces/                    Ignored local analysis and model work
examples/
  ask-data/
  semantic-setup/
docs/                          One guide per product route plus architecture
ossie-main/                    Pinned Apache Ossie submodule
```

The pinned Ossie submodule remains at the repository root because changing a Git submodule path
would add migration friction without improving the user workflow.

## Development

```bash
uv run ruff check .
uv run mypy data_agent
uv run python -m unittest discover -s tests -v
uv run python scripts/validate_project.py
```

See [Architecture](docs/ARCHITECTURE.md) for boundaries and advanced internals.
