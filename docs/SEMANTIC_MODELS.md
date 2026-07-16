# Semantic models

Apache Ossie, formerly Open Semantic Interchange (OSI), is the shared format used by the analysis
agent. The project pins the official repository as the `ossie-main` Git submodule and directly
uses its `0.2.0.dev0` schema and validator functions.

## Model locations

- `semantic/models/`: models searched by default during analysis.
- `semantic/generated/`: replaceable raw, patch, final, and conversion-manifest artifacts.
- `ossie-main/`: pinned official schema, validator, converter guidance, examples, and license.

## Builder workflow

```text
source export
  -> format detection
  -> neutral semantic IR 1.0
  -> supported expression translation
  -> deterministic raw OSI
  -> official Ossie + analysis-readiness validation
  -> <model>.raw.osi.yaml
  -> <model>.conversion.json
  -> interactive business + analyst decisions
  -> <model>.review.decisions.json
  -> compiled audited review patch
  -> deterministic patch application and revalidation
  -> per-model competency questions
  -> <model>.osi.yaml
  -> automatic promotion when clean
```

The neutral IR retains source IDs, descriptions, titles/aliases, formats, labels, expressions,
physical mappings, relationships, unsupported constructs, and a source snapshot hash before OSI
emission. Portable translations use `ANSI_SQL`; vendor-specific expressions retain their official
dialect where Ossie supports it.

## Supported inputs

| Input | Current extraction |
|---|---|
| Power BI PBIP/TMDL directory | Descriptions, folders, formats, fields, keys, relationships, simple DAX aggregates, and preserved unsupported DAX |
| Tableau `.tds` (normal path) or `.twb` | Datasources, fields, physical source, simple aggregates, calculation review items |
| Tableau `.tde` with `.tds` | Descriptor semantics plus a snapshot hash covering both files |
| Generic JSON/YAML | Datasets, fields, metrics, relationships, keys, descriptions, `ai_context`, synonyms, and multi-dialect expressions |
| Neutral semantic IR | Direct OSI emission |
| Existing Ossie | Validation, deterministic serialization, and manifest generation |

## Translation behavior

Direct `SUM`, `AVERAGE`/`AVG`, `MIN`, `MAX`, `COUNT`, and distinct-count expressions can be
translated. Complex DAX, Power Query transformations, Tableau LOD expressions, table
calculations, roles, parameters, and filters are preserved or reported for review.

Translation states are `exact`, `equivalent-with-assumptions`, `partial`, `unsupported`,
`reviewed-unsupported`, and `requires-human-review`. `reviewed-unsupported` records an audited
decision to preserve the source construct in immutable provenance while keeping it out of
executable OSI; unlike an unreviewed `unsupported` state, it does not block promotion.

## Examples

Power BI:

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py \
  tests/fixtures/powerbi --model-name demo_powerbi
```

Tableau with explicit mappings:

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py \
  examples/tableau/world.tds --model-name world_indicators \
  --source-map examples/tableau/world-source-map.demo.json \
  --field-map examples/tableau/world-field-map.example.json
```

Generic YAML:

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py \
  tests/fixtures/generic/sales.yaml --model-name demo_generic
```

The normal workflow opens the interactive review workspace:

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py SOURCE \
  --model-name MODEL --review-ui
```

Before the workspace opens, conversion compares the deterministic raw model with any currently
promoted model of the same name. The manifest, command summary, and workspace show object-level
added, removed, and changed items with `breaking`, `semantic`, or `metadata` impact.

The workspace opens blocking issues first when present and otherwise starts in a description-first
Catalog. Tables group their columns and keep both description levels editable in context; related
description edits can be reviewed and committed together, with audit metadata captured automatically
when the user saves. Business and Analyst views progressively
reveal metrics, relationships, and advanced properties. A dismissible drawer covers synonyms,
examples, instructions, sources, keys, relationships, dialect expressions, and translation
decisions, while the metric builder offers common aggregations and custom compile-previewed logic.
Key and relationship selectors show physical source columns derived from field expressions and
preserve existing physical references; semantic field names are reviewed separately.
Selected translations with the same status may share one reviewed decision while emitting one
audited operation per object. The advanced JSON operation editor remains available for uncommon
OSI constructs. Every change requires rationale, evidence, confidence, and explicit assumptions.
Destructive changes require confirmation and can be undone before Apply. Structural references are
updated for unambiguous renames; expression references that cannot be rewritten safely block Apply.

Committed decisions auto-save under `semantic/generated/`; half-completed drawer and inline edits
stay in the browser until explicitly committed and never change OSI or count as review evidence.
On Apply, Python validates the complete decisions file against the original raw SHA-256, generates
the audited patch, protects the OSI version and converter provenance, records before/after values,
and reruns official, readiness, and matching `semantic/tests/<model>.yaml` competency validation.
The workspace retains failed edits and displays the recovery action. A clean model is promoted only
after the destination is confirmed.

Competency fixtures contain deterministic questions, structured plans, expected semantic and
result grain, and required or excluded SQL fragments. They do not execute analytical queries.

The server binds exclusively to `127.0.0.1` and uses a random session token, exact Origin checks,
JSON-only bounded requests, no CORS, and restricted artifact paths. `--review-port PORT` selects a
port; otherwise an available port is chosen. `--no-open` prints the URL without opening a browser.
The static `<model>.review.html` fallback can download decisions JSON for later application:

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py SOURCE \
  --model-name MODEL --review-decisions PATH
```

Manual JSON patching with `--review-patch` remains supported for advanced audit/debugging. In both
paths, assumptions and low-confidence logic changes remain visible and prevent automatic
promotion.

Snowflake verification is optional. Add `--verify-snowflake --configuration-confirmed` only after
displaying and confirming the non-secret connection context. It checks object metadata and uses
the connector's `cursor.describe()` to compile model expressions without executing analytical
queries.

## Typed command interface

The `data-agent` runner exposes the same deterministic stages for automation:

| Command | Request purpose |
|---|---|
| `semantic-convert` | Supply `source_path`, optional `source_type`/mappings, and `model_name`; receive raw and manifest paths. |
| `semantic-review` | Supply `raw_model_path`, `manifest_path`, and `patch_path`; optionally request Snowflake verification or disable promotion. |
| `osi-validate` | Supply `model_path`; receive separate official-validation and project-readiness results. |
| `osi-test` | Supply `model_path` and `cases_path`; compile every competency case and report failures. |
| `semantic-diff` | Supply `before_path` and `after_path`; receive object-level breaking, semantic, and metadata changes. |

All commands use the existing `--input REQUEST.json --output RESPONSE.json` CLI contract.

## Upstream references

- [Apache Ossie repository](https://github.com/apache/ossie)
- [Apache Ossie schema](https://github.com/apache/ossie/blob/main/core-spec/osi-schema.json)
- [Apache Ossie validator](https://github.com/apache/ossie/blob/main/validation/validate.py)
- [Power BI TMDL overview](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview)
- [Tableau Metadata API](https://help.tableau.com/current/api/metadata_api/en-us/index.html)
