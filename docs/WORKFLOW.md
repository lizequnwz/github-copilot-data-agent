# User workflow

The recommended entry point is the repository's `data-analytics` GitHub Copilot agent. The local
Python commands are its deterministic execution layer and are also useful for testing and
automation.

## Start here

Run the offline walkthrough before connecting to Snowflake:

```bash
uv sync --extra dev
uv run python scripts/demo_analysis.py
```

This uses the synthetic `demo_sales` model and writes
`reports/generated/demo-sales-analysis.html`. It does not connect to Snowflake.

To trigger the conversational workflow:

- In VS Code, open this repository, open Copilot Chat, and select `data-analytics` from the agents
  dropdown.
- In GitHub Copilot CLI, use `/agent` and select `data-analytics`, or start a request with
  `copilot --agent=data-analytics --prompt "..."`.

The agent first selects **Ask Data** or **Semantic Setup**, then chooses the smallest relevant skill:
`snowflake-analysis` for data questions, `osi-semantic-model-builder` for semantic onboarding, and
`analytics-report-generation` for an explicitly requested chart or report.

## Visual workflow guides

- [Business question to validated answer](diagrams/data-question-workflow.html) shows how a scoped
  question moves through the shared semantic layer, connection confirmation, read-only Snowflake
  execution, result validation, and reporting.
- [Semantic layer creation and review](diagrams/semantic-layer-review.html) shows the normal BI
  conversion, business and analyst review, audited Apply operation, validation, and promotion
  path.

Both guides are self-contained HTML files with light/dark themes and image export. Their editable
Archify sources live beside them as
[`data-question-workflow.workflow.json`](diagrams/data-question-workflow.workflow.json) and
[`semantic-layer-review.workflow.json`](diagrams/semantic-layer-review.workflow.json).

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
interpretation below, confirms Snowflake context before its first connection, validates and runs a
bounded query, checks the result, and leads with the answer. It does not replace unsupported
semantic-plan behavior with ad hoc SQL.

```text
Metric
Population
Dimensions
Filters
Period
Expected result grain
Semantic model
Requested output
```

The structured plan supports explicit filters, an inclusive-start/exclusive-end `time_range`, and
`order_by` on selected dimensions or metrics. The response preserves qualified semantic `grain`
and separately reports returned-column `result_grain`, `result_columns`, `max_rows`, and the
extra-row `query_limit` used to detect truncation.

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

Semantic-layer creation and refresh use the browser review workspace by default. Responsibilities
are deliberately split:

- Business users define business meaning, inclusions/exclusions, synonyms, and the questions the
  model must answer.
- Analysts confirm physical mappings, keys, relationship direction, grain, and expressions.
- The agent generates deterministic artifacts, compiles audited decisions, validates Ossie, and
  runs competency questions, and promotes only an eligible result.

Start Semantic Setup by resolving the business domain, definition owner, intended warehouse
sources, and questions the model must answer. In the workspace, choose Business or Analyst view.
Normal controls cover descriptions, synonyms, example questions, AI instructions, sources, keys,
relationships, expressions, and translation decisions. `custom_extensions` and raw JSON Pointer
editing remain advanced-only. Selected translations with the same status can share one reviewed
decision while still producing one audited operation per object.

Example prompts:

> Convert this unpacked Power BI TMDL directory into an OSI model and show me what needs review.

> Build an OSI model from this Tableau `.tds` datasource. Map it to the real Snowflake source, use
> the provided field map, then summarize translated calculations, unsupported calculations, and
> blocking review items.

> Refresh the generated model from this updated BI export and compare the manifest with the last
> conversion.

> Review the generated semantics with me. Lead with blocking decisions, preserve source evidence,
> and open the browser workspace so I can approve or correct each change.

> Help me resolve the remaining assumptions. Ask for one material business decision at a time and
> record my answer as user evidence.

> Apply my saved decisions, show the before/after audit, and promote only if validation is clean.

> Verify the reviewed model against Snowflake metadata after showing me the non-secret connection
> context for confirmation.

Launch the normal workflow with:

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py SOURCE \
  --model-name MODEL --review-ui
```

The builder writes a deterministic raw OSI file and manifest, starts a temporary loopback-only
server, shows the object-level impact from any promoted version, and opens the review workspace.
Start with blocking issues, search an object section,
review one focused editor, and provide rationale, evidence, confidence, and assumptions for every
change. Drafts auto-save without changing OSI. **Apply and validate** compiles the complete
decisions file and audited patch against the original raw hash, applies it deterministically,
reruns validation, and confirms the destination before a clean promotion.

If a browser cannot be opened, add `--no-open` and use the printed URL. The generated static review
HTML is a fallback that downloads decisions JSON. Apply that file later with
`--review-decisions PATH`. Direct `--review-patch` editing is reserved for audit and debugging.

### Normal Tableau path: `.tds`

Most Tableau semantic onboarding should begin with the `.tds` datasource because it carries the
datasource fields, default aggregations, calculations, and connection metadata needed for model
conversion. Use `examples/tableau/world.tds` and its mapping files as the working shape:

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py \
  examples/tableau/world.tds --model-name world_indicators \
  --source-map examples/tableau/world-source-map.demo.json \
  --field-map examples/tableau/world-field-map.example.json --review-ui
```

For a real datasource:

1. Copy `examples/tableau/world-source-map.example.json` and replace the placeholder with the real
   `DATABASE.SCHEMA.TABLE_OR_VIEW`.
2. Create or adapt a field map when Tableau display names do not match simple unquoted Snowflake
   column aliases.
3. Run the builder with `--review-ui`; use the manifest and raw YAML for technical traceability.
4. Resolve physical-source blockers, then review keys, relationships, important fields, metric
   expressions, descriptions, synonyms, examples, and `ai_context` in the workspace.
5. Select **Apply and validate**. Confirm the proposed `semantic/models/` destination; promotion
   occurs only when official and readiness validation pass with no unresolved assumptions.

Snowflake evidence is optional. When requested, confirm the displayed non-secret context first and
add `--verify-snowflake --configuration-confirmed`; failed or partial verification prevents
promotion for that run while preserving the raw artifact.

A `.twb` workbook is also supported when workbook-level metadata is the source. A binary `.tde`
cannot provide the semantic definition by itself; it requires a matching `.tds` descriptor or an
explicit `--descriptor` path.

## Request a report

Start with a validated analytical result, then ask:

> Turn this result into a bar chart and a self-contained HTML report.

Reports are written under `reports/generated/`. Query details are included when the result came
from Snowflake; offline examples use clearly labeled synthetic details.

## Typed command examples

All commands use the same `--input REQUEST.json --output RESPONSE.json` contract.

Search promoted semantics:

```json
{"request_id":"search-sales","roots":["semantic/models"],"query":"gross sales region","limit":10}
```

Compile a bounded two-month plan:

```json
{
  "request_id": "compile-sales",
  "model_path": "semantic/models/demo_sales.yaml",
  "plan": {
    "semantic_model": "demo_sales",
    "metric_ids": ["gross_sales"],
    "dimensions": ["orders.region"],
    "filters": [{"field":"orders.status","operator":"=","value":"completed"}],
    "time_range": {
      "field":"orders.order_date",
      "start":"2026-05-01",
      "end_exclusive":"2026-07-01",
      "label":"May through June 2026"
    },
    "order_by": [{"field":"gross_sales","direction":"desc"}],
    "max_rows": 10
  }
}
```

Run the complete offline analysis with
`examples/analysis/sales-by-region.json`. Validate OSI with:

```json
{"request_id":"validate-demo","model_path":"semantic/models/demo_sales.yaml"}
```

Convert generic semantics:

```json
{"request_id":"convert-demo","source_path":"tests/fixtures/generic/sales.yaml","source_type":"auto","model_name":"demo_generic_sales"}
```

Apply an audited review patch:

```json
{"request_id":"review-demo","raw_model_path":"semantic/generated/demo_generic_sales.raw.osi.yaml","manifest_path":"semantic/generated/demo_generic_sales.conversion.json","patch_path":"semantic/generated/demo_generic_sales.review.patch.json","promote_if_clean":true}
```

Compare refreshed semantics:

```json
{"request_id":"diff-demo","before_path":"semantic/models/demo_sales.yaml","after_path":"semantic/generated/demo_sales.osi.yaml"}
```

Run competency questions:

```json
{"request_id":"test-demo","model_path":"semantic/models/demo_sales.yaml","cases_path":"semantic/tests/demo_sales.yaml"}
```

Use these commands respectively with `osi-search`, `osi-compile`, `analyze`, `osi-validate`,
`semantic-convert`, `semantic-review`, `semantic-diff`, and `osi-test`.

Runnable request files for search, compile, validation, and competency testing are available under
`examples/requests/`.
