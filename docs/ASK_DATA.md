# Ask Data

Ask Data has one semantic-model-first workflow:

```text
question
  → model coverage
  → promoted semantic model
  → editable semantic plan
  → compiler-generated read-only SQL
  → result and finding
  → analysis workspace
  → optional validation
  → optional HTML report
```

## Run an analysis

```bash
uv run data-agent ask --input examples/ask-data/exploration.json
```

An Ask Data input needs a question, a promoted `model_path`, and a semantic `plan`. Live requests
also set `execute: true` after the non-secret Snowflake context is confirmed. Offline examples may
provide a clearly labeled `example_result`.

Every covered Ask Data request creates a workspace by default, including a plan that has not yet
executed. Use `--no-workspace` for an inline or automation-only response.

## Semantic plan

Minimal aggregate plan:

```json
{
  "semantic_model": "demo_sales",
  "metric_ids": ["gross_sales"],
  "dimensions": ["orders.region"],
  "filters": [
    {"field": "orders.status", "operator": "=", "value": "completed"}
  ],
  "order_by": [{"field": "gross_sales", "direction": "desc"}],
  "max_rows": 100
}
```

Supported exploratory capabilities include:

- zero or more promoted metrics;
- qualified model dimensions;
- request-scoped derived metrics and dimensions over promoted fields;
- time dimensions with `day`, `week`, `month`, `quarter`, or `year` grain;
- `=`, `!=`, `>`, `>=`, `<`, `<=`, `in`, `not_in`, `is_null`, `is_not_null`, `contains`,
  `starts_with`, and `ends_with` filters;
- explicit time ranges;
- aggregate `having` comparisons;
- `percent_of_total`, `rank`, and `running_total` calculations;
- ordering and bounded result size.

Plans without metrics produce bounded detail queries. Request-scoped logic remains unpromoted and
is recorded in the manifest.

See `examples/ask-data/advanced-plan.json` for a complete richer plan.

## Coverage diagnostics

```bash
uv run data-agent model coverage --input examples/ask-data/coverage-gap.json
```

The response lists covered and missing metrics and fields, relationship connectivity, suggestions,
the best matching promoted model, and the next action. Missing coverage routes to Semantic Setup.

## Analysis workspace

Each workspace contains:

```text
analysis.json       Durable analysis manifest
analysis.md         Readable evidence record
analysis.ipynb      Editable semantic analysis
report.html         Optional self-contained report
```

The manifest records model and plan hashes, generated SQL, parameters, source objects, query
evidence, result, validation state, narrative, and artifact paths.

The notebook exposes editable semantic variables and builds the plan from them. It compares the
current model/plan signature with saved evidence:

- unchanged plan: reuse saved evidence;
- changed plan: recompile automatically without silently reusing old rows;
- live execution: require `RUN_LIVE = True` and confirmed Snowflake context.

Generated SQL is visible evidence, not the editable source of truth. Experimental pandas
transformations are allowed when clearly separated from semantic SQL.

## Validation and reports

Result checks are optional. Add only useful checks for emptiness, truncation, required columns,
result-grain duplicates, non-null values, or known numeric ranges.

Reports retain semantic provenance and are labeled:

- **Exploratory · not validated** when checks did not run;
- **Validated** only when checks pass.

HTML reports are self-contained, accessible, responsive, printable, and free of remote scripts,
fonts, and assets. Findings must remain evidence-backed; do not invent causality or definitions.

## Visual guide

[Business question to semantic exploration](diagrams/data-question-workflow.html) is the
self-contained workflow diagram.
