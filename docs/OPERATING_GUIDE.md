# Operating guide

## Convert a semantic model

Select the `data-analytics` Copilot agent and ask:

> Convert this Power BI, Tableau, or semantic metadata asset into a usable Ossie candidate. Show me the conversion summary and review issues.

The agent uses `osi-semantic-builder` to:

1. Identify the input and expected output name.
2. Detect PBIP/TMDL, Tableau `.twb`/`.tds`/`.tde` with sibling `.tds`, generic JSON/YAML, neutral IR, or existing Ossie.
3. Ask for a physical source map only when missing mappings would make the output unusable.
4. Extract neutral semantic IR with source expressions and a source hash.
5. Translate only supported expressions and label every assumption or loss.
6. Emit and validate `semantic/candidates/<name>.osi.yaml`.
7. Write `semantic/candidates/<name>.conversion.json`.
8. Summarize datasets, fields, relationships, metrics, blocking issues, and review items.

You can run the same workflow directly:

```bash
uv run python scripts/convert_semantic.py path/to/source --model-name model_name
```

See [Semantic conversion](SEMANTIC_CONVERSION.md) for source-specific behavior.

## Review and certify a candidate

Resolve physical source placeholders and blocking issues, review source expressions retained in custom extensions, verify key direction and metric meaning, then compile representative queries and compare them with the source BI model. A human moves the reviewed YAML into `semantic/certified/`; the conversion manifest remains evidence and is not itself a semantic model.

## Generate an analytical artifact

After result validation passes, ask the agent to use `analytics-report-generation`. It can produce:

- Python-rendered, accessible SVG bar or line charts.
- Self-contained responsive HTML reports with chart, table, definitions, methodology, caveats, provenance, and SQL appendix.

Generated output belongs under `reports/generated/` and uses no remote JavaScript, fonts, or assets.

## Set up Snowflake

Snowflake is not required for conversion or rendering. For live analysis, ask:

> Set up Snowflake for this project and guide me step by step.

The agent verifies Python 3.11+ and `uv`, runs `uv sync --extra dev --extra snowflake`, displays the non-secret context in `snowflake_config.yaml`, waits for confirmation, opens browser SSO, and verifies the effective configured role.

## Ask a data question

The agent resolves the requested metric, dimensions, filters, population, period, and output; searches certified Ossie first; creates a structured plan; validates and executes a bounded query; validates the result; and returns definitions, freshness, semantic source, query ID, role, confidence, and caveats.

## Memory

Memory is deliberately small. `memory/approved/` contains reviewed business notes; `memory/pending/` contains evidence-backed proposals. Semantic definitions belong in `semantic/`, not memory.
