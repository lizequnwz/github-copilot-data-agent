# User workflow

The recommended entry point is the repository's `data-analytics` GitHub Copilot agent. The local
Python commands are its deterministic execution layer and are also useful for testing and
automation.

## Start here

Run the offline walkthrough before connecting to Snowflake:

```bash
git submodule update --init --recursive
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
  question moves through interpretation, semantic compilation, connection confirmation, bounded
  read-only Snowflake execution, result-grain validation, and reporting.
- [Semantic layer creation and review](diagrams/semantic-layer-review.html) shows the normal BI
  intake, deterministic conversion, object-level refresh impact, parallel Business and Analyst
  views, audited decisions, competency-gated validation, and promotion path.

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

The agent searches `semantic/models/`, asks only material clarification questions, and selects a
promoted metric when available. If no promoted metric fits, it may calculate an explicitly
unpromoted metric from promoted fields or validate ad hoc text-to-SQL over promoted physical
sources and configured `access.allowed_objects`. It confirms Snowflake context before its first
connection, validates and runs a bounded query, checks the result, and leads with the answer.

```text
Metric or explicit formula
Population
Dimensions
Filters
Period
Expected result grain
Source mode and sources
Requested output
```

Promoted and derived structured plans support explicit filters, an
inclusive-start/exclusive-end `time_range`, and `order_by` on selected dimensions or metrics.
Derived metrics provide `name`, `description`, `expression`, and `assumptions` and are not written
back to the model. Ad hoc requests provide explicit SQL, positional parameters, metric metadata,
all eight interpretation fields, and `LIMIT max_rows + 1`; their physical sources must be promoted
or allowlisted. Responses preserve qualified semantic `grain` when applicable and separately
report returned-column `result_grain`, `result_columns`, `max_rows`, and the extra-row `query_limit`
used to detect truncation. Snowflake normally returns unquoted aliases in uppercase even when the
generated SQL uses lowercase identifiers; result checks therefore match column names
case-insensitively and preserve the returned names for query evidence.

For a live query, expect:

```text
Answer
Definition and grain
Filters and time range
Source mode, semantic model or approved objects
Query ID and role
SQL
Caveats or follow-up questions
```

Derived and ad hoc answers also identify the formula, assumptions, and unpromoted status.

## First connection

Copy the example configuration and add the non-secret values:

```bash
cp snowflake_config.example.yaml snowflake_config.yaml
uv sync --extra dev --extra snowflake
```

Then ask:

> Check my Snowflake configuration and connect with browser SSO.

Use `authenticator: externalbrowser` for browser SSO. For access-token OAuth, set
`authenticator: oauth`, name the environment variable with `oauth_token_env`, and export the token
there. The agent displays account, user, authentication mode, token availability (never the token),
and any preferred role, warehouse, database, and schema. After confirmation it connects, reports
the effective context, and treats differences from configured preferences as warnings.

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
Catalog groups columns beneath their tables and keeps descriptions directly editable; related
description edits can be reviewed and committed together without a separate change-note form; the
workspace records the save action as audit metadata. Metrics offers common aggregation templates,
custom expressions, and a non-writing preview. Technical properties open in a drawer whose Close,
Cancel, and Escape paths never validate incomplete fields. `custom_extensions` and raw JSON Pointer
editing remain advanced-only.

Dataset keys and relationship columns are physical source-column identifiers. They are derived
from simple field expressions and remain unchanged when a semantic field is renamed. Selecting
**Retain as reviewed unsupported** preserves the unsupported source construct in immutable
conversion provenance, keeps it out of executable OSI, and clears its promotion blocker after the
audited decision is applied.

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

Compile a model-backed metric without promoting a new shared definition:

```bash
uv run python -m data_agent osi-compile \
  --input examples/analysis/average-order-value-derived.json \
  --output /tmp/average-order-value-derived.response.json
```

Validate an unpromoted text-to-SQL plan over a promoted or allowlisted source:

```bash
uv run python -m data_agent analyze \
  --input examples/analysis/average-order-value-ad-hoc.json \
  --output /tmp/average-order-value-ad-hoc.response.json
```

The offline ad hoc example reads source controls from `snowflake_config.example.yaml`; no connection
occurs unless the request also sets `execute: true`. Use a completed local `snowflake_config.yaml`
for live execution. Predicate values must use `%s` placeholders, every output must have a stable
name, and the SQL limit must equal `max_rows + 1`.

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

Runnable request files for search, compile, validation, competency testing, derived metrics, and ad
hoc analysis are available under `examples/`.
