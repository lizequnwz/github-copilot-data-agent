# User workflow

The recommended entry point is the repository's `data-analytics` GitHub Copilot agent. The local
Python commands are its deterministic execution layer and are also useful for testing and
automation.

## Start here

Run the offline walkthrough before connecting to Snowflake:

```bash
git submodule update --init --recursive
uv sync --extra dev
uv run python scripts/demo_exploration.py
```

This uses synthetic rows and writes `analysis.md` and `analysis.ipynb` under
`reports/generated/exploratory-sales/`. It does not connect to Snowflake. The model-backed,
validated walkthrough remains available through `scripts/demo_analysis.py`.

To trigger the conversational workflow:

- In VS Code, open this repository, open Copilot Chat, and select `data-analytics` from the agents
  dropdown.
- In GitHub Copilot CLI, use `/agent` and select `data-analytics`, or start a request with
  `copilot --agent=data-analytics --prompt "..."`.

The agent first selects **Ask Data** or **Semantic Setup**, then chooses the smallest relevant skill:
`snowflake-analysis` for data questions, `osi-semantic-model-builder` for semantic onboarding, and
`analytics-report-generation` for an explicitly requested chart or report.

## Visual workflow guides

- [Business question to validated answer](diagrams/data-question-workflow.html) shows the optional
  assurance path after an exploration has stabilized: semantic compilation, connection
  confirmation, bounded execution, result-grain validation, and reporting.
- [Semantic layer creation and review](diagrams/semantic-layer-review.html) shows the normal BI
  intake, deterministic conversion, object-level refresh impact, parallel Business and Analyst
  views, audited decisions, competency-gated validation, and promotion path.

Both guides are self-contained HTML files with light/dark themes and image export. Their editable
Archify sources live beside them as
[`data-question-workflow.workflow.json`](diagrams/data-question-workflow.workflow.json) and
[`semantic-layer-review.workflow.json`](diagrams/semantic-layer-review.workflow.json).

## Explore a data question

Select the `data-analytics` Copilot agent and provide the business question in ordinary language:

> Explore completed-order sales by region. Show the SQL and create a notebook so I can adjust it.

Users may start with:

- a question or hypothesis;
- partial or complete SQL;
- one or more table names;
- a request to profile, compare, trend, segment, or visualize data.

The agent asks only what is needed to make the next query useful. It may inspect
`semantic/models/`, but direct SQL does not require model coverage, formula metadata, an object
allowlist, parameterized predicates, a declared result grain, or an explicit SQL `LIMIT`.

```text
Question or hypothesis
Next useful read-only SQL query
Result table and query details
Observation, chart, or follow-up experiment
Optional Markdown/notebook workspace
```

SQL-only requests default to `analysis_mode: exploratory`. They remain explicitly unpromoted.
Snowflake execution still uses parsed read-only statements, confirmed non-secret connection
context, query timeouts, cancellation support, and local fetch/byte protections.

For a live query, expect:

```text
Finding or next experiment
Query ID and role
SQL
Returned rows and truncation status
Useful caveats or follow-up questions
Markdown/notebook links when generated
```

Exploratory results return `result_validation.status: not_run` by default. Add
`validate_result: true` or explicit `result_checks` when assurance becomes useful. Teams may then
move stable logic to a derived metric, a promoted semantic plan, or the governed ad hoc contract.
See [Exploratory analysis workspace](EXPLORATORY_ANALYSIS.md) for the complete notebook and
progressive-validation workflow.

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

For a direct local check, run:

```bash
uv run python scripts/check_snowflake.py
```

The explicit command displays the non-secret preferences before connecting and reports one concise
connected, configuration-required, or connection-failed result.

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
Navigation stays limited to Catalog, Metrics, and Advanced. Catalog groups columns beneath their
tables, shows completeness, and offers a next-missing queue. A persistent bar saves related
description edits directly and keeps Undo and Discard visible; the workspace records the save
action as audit metadata. Metrics shows common aggregation templates first, with custom
expressions, dialect, synonyms, and examples disclosed only when requested. Technical properties
open in a drawer whose Close, Cancel, and Escape paths never validate incomplete fields.
Relationships, model status, `custom_extensions`, and raw JSON Pointer editing remain under
Advanced.

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

Ask at any point:

> Turn this result into a bar chart and a self-contained HTML report.

Reports are written under `reports/generated/`. Query details are included when the result came
from Snowflake; offline examples use clearly labeled synthetic details. Reports without passing
result checks are visibly labeled **Exploratory · not validated**.

## Typed command examples

All commands use the same `--input REQUEST.json --output RESPONSE.json` contract.

Run a flexible SQL exploration:

```bash
uv run python -m data_agent analyze \
  --input examples/analysis/exploratory-sales.json \
  --output /tmp/exploratory-sales.response.json
```

Generate its Markdown and notebook workspace:

```bash
uv run python -m data_agent render-workspace \
  --input examples/requests/render-workspace.json \
  --output /tmp/render-workspace.response.json
```

The remaining examples show optional semantic, validation, and promotion paths.

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
