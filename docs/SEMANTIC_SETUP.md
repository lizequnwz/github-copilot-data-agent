# Semantic Setup

Semantic Setup creates and improves promoted Apache Ossie models used by Ask Data.

## Normal path

```bash
uv run data-agent model setup SOURCE --model-name MODEL
```

The command detects the source, converts it deterministically, compares it with any promoted model
of the same name, writes work under `workspaces/models/`, and opens the guided review workspace.
Use `--no-review` to stop after conversion.

For repeatable automation, use `--review-decisions PATH` to replay guided decisions or
`--review-patch PATH` to apply an advanced audited patch. Either option replaces the interactive
workspace for that run.

Supported inputs:

| Input | Current extraction |
|---|---|
| Power BI PBIP/TMDL | Tables, fields, keys, relationships, descriptions, simple DAX aggregates |
| Tableau `.tds` or `.twb` | Datasources, fields, physical sources, aggregates, calculation review items |
| Tableau `.tde` with `.tds` | Descriptor semantics plus snapshot evidence |
| Generic JSON/YAML | Datasets, fields, metrics, relationships, descriptions, and context |
| Neutral semantic IR | Direct Ossie emission |
| Existing Ossie | Validation, deterministic serialization, and refresh comparison |

## Review

Business reviewers own meaning, inclusions, exclusions, synonyms, and expected questions. Analysts
own physical mappings, keys, relationships, grain, and expressions. The workspace exposes Catalog,
Metrics, and Advanced views with progressive detail.

Raw conversion provenance is immutable. Guided changes record rationale, evidence, confidence, and
assumptions. Failed validation preserves the draft and previously promoted model.

## Promotion

Promotion requires:

- official Ossie validation;
- project analysis-readiness checks;
- no unresolved assumptions;
- configured semantic competency tests passing;
- optional Snowflake verification passing when requested;
- explicit destination confirmation.

Clean models promote to `semantic/models/`. Competency plans live under `semantic/tests/`.

## Advanced operations

Low-level automation remains available under `data-agent advanced`:

```text
osi-validate
osi-test
semantic-convert
semantic-review
semantic-diff
```

These are implementation stages, not separate user journeys.

## Upstream schema

The project uses the pinned schema and validator in `ossie-main/`. Initialize it with:

```bash
git submodule update --init --recursive
```

## Visual guide

[Semantic layer creation and review](diagrams/semantic-layer-review.html) shows conversion, review,
validation, and promotion.
