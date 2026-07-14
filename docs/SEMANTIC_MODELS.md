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
  -> audited LLM review patch
  -> deterministic patch application and revalidation
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

Translation states are `exact`, `equivalent-with-assumptions`, `partial`, `unsupported`, and
`requires-human-review`.

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

Review the conversion manifest first. Resolve physical source blockers, then inspect important
keys, relationships, fields, and metric expressions. Create the audited JSON patch described in
the skill reference and rerun with:

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py SOURCE \
  --model-name MODEL --review-patch semantic/generated/MODEL.review.patch.json
```

Every patch operation repeats the raw model hash and records rationale, evidence, confidence, and
assumptions. Python protects the OSI version and conversion provenance, applies the patch, reruns
official validation, and promotes only a clean reviewed model. Assumptions remain visible in the
manifest and prevent automatic promotion.

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

All three use the existing `--input REQUEST.json --output RESPONSE.json` CLI contract.

## Upstream references

- [Apache Ossie repository](https://github.com/apache/ossie)
- [Apache Ossie schema](https://github.com/apache/ossie/blob/main/core-spec/osi-schema.json)
- [Apache Ossie validator](https://github.com/apache/ossie/blob/main/validation/validate.py)
- [Power BI TMDL overview](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview)
- [Tableau Metadata API](https://help.tableau.com/current/api/metadata_api/en-us/index.html)
