# GitHub Copilot Data Analytics Agent POC

This repository contains one GitHub Copilot custom agent for semantic-first Snowflake analytics. Its most complete offline workflow converts Power BI, Tableau, neutral semantic IR, generic JSON/YAML, or existing Ossie metadata into validated candidate Apache Ossie models.

Apache Ossie was formerly named Open Semantic Interchange (OSI). The user-selected [`open-semantic-interchange/ossie`](https://github.com/open-semantic-interchange/ossie) repository now directs new work to [`apache/ossie`](https://github.com/apache/ossie). This project vendors the `0.2.0.dev0` core schema and records the upstream schema in every conversion manifest.

## Fastest useful demo

Convert one of the included fixtures:

```bash
uv run python scripts/convert_semantic.py tests/fixtures/powerbi --model-name demo_powerbi
uv run python scripts/convert_semantic.py tests/fixtures/tableau/sales.twb --model-name demo_tableau
uv run python scripts/convert_semantic.py tests/fixtures/generic/sales.yaml --model-name demo_generic
```

Each command writes two reviewable files under `semantic/candidates/`:

- `<name>.osi.yaml`: schema-valid candidate Ossie metadata.
- `<name>.conversion.json`: source hash, translation summary, issues, and review checklist.

For real PBIP/TMDL models whose physical tables cannot be inferred, provide a JSON source map:

```json
{
  "Orders": "PROD.ANALYTICS.ORDERS",
  "Customers": "PROD.ANALYTICS.CUSTOMERS"
}
```

```bash
uv run python scripts/convert_semantic.py path/to/model --source-map source-map.json
```

See [Semantic conversion](docs/SEMANTIC_CONVERSION.md) for supported constructs and review states.

Generate an offline HTML report preview:

```bash
uv run python scripts/render_report_demo.py
```

## Agent capabilities

- `osi-semantic-builder`: detect, extract, convert, validate, and review semantic assets.
- `analytics-report-generation`: generate accessible Python-rendered SVG charts and self-contained HTML reports.
- `snowflake-environment-setup`: prepare Python, `uv`, browser SSO, and configuration.
- `snowflake-readonly-query`: discover metadata and run bounded read-only analysis.
- `result-validation`: validate analytical result shape and grain before reporting.

GitHub Copilot discovers [.github/agents/data-analytics.agent.md](.github/agents/data-analytics.agent.md). Repository-wide instructions live in [.github/copilot-instructions.md](.github/copilot-instructions.md), and detailed procedures live in [.github/skills/](.github/skills/).

## Project layout

```text
.github/                         Copilot agent and five procedural skills
data_agent/
  bi/extract.py                  Power BI, Tableau, and generic extractors
  semantic/                      Ossie model IO, conversion, emission, search, compile
  reporting/render.py            Python SVG charts and self-contained HTML reports
  tools/                         Snowflake, result validation, and memory commands
  cli.py                         typed command dispatcher
semantic/
  schemas/                       vendored Ossie schema
  certified/                     reviewed models used for analysis
  candidates/                    generated model + manifest pairs
memory/
  approved/                      reviewed small business notes
  pending/                       proposed notes awaiting review
reports/generated/               local chart/report artifacts
scripts/                         project validation and semantic conversion entry points
tests/                           offline fixtures and behavior tests
```

[How `data_agent` works](docs/DATA_AGENT.md) describes the package and execution flow.

## Setup and validation

Use Python 3.11+ and `uv`:

```bash
uv sync --extra dev --extra snowflake
uv run python scripts/validate_project.py
uv run python -m unittest discover -s tests -v
uv run ruff check .
uv run mypy data_agent
```

Snowflake remains optional for semantic conversion and report rendering. When it is needed, fill in `snowflake_config.yaml`, retain `authenticator: externalbrowser`, and follow [the operating guide](docs/OPERATING_GUIDE.md).
