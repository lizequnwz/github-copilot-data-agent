# Semantic models

Apache Ossie, formerly Open Semantic Interchange (OSI), is the shared format used by the analysis
agent. The project vendors the `0.2.0.dev0` schema for reproducible offline validation.

## Model locations

- `semantic/models/`: models searched by default during analysis.
- `semantic/generated/`: replaceable builder output and conversion manifests.
- `semantic/schemas/`: the vendored schema.

## Builder workflow

```text
source export
  -> format detection
  -> neutral semantic IR 1.0
  -> supported expression translation
  -> OSI emitter and schema validation
  -> <model>.osi.yaml
  -> <model>.conversion.json
```

The neutral IR retains source IDs, expressions, physical mappings, relationships, unsupported
constructs, and a source snapshot hash before OSI emission.

## Supported inputs

| Input | Current extraction |
|---|---|
| Power BI PBIP/TMDL directory | Tables, fields, keys, relationships, simple DAX aggregates, source expressions |
| Tableau `.twb` or `.tds` | Datasources, fields, physical source, simple aggregates, calculation review items |
| Tableau `.tde` with `.tds` | Descriptor semantics plus a snapshot hash covering both files |
| Generic JSON/YAML | Datasets, fields, metrics, relationships, keys, and descriptions |
| Neutral semantic IR | Direct OSI emission |
| Existing Ossie | Validation, normalization, and manifest generation |

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
keys, relationships, fields, and metric expressions. Generated files can be deleted and rebuilt.

## Upstream references

- [Apache Ossie repository](https://github.com/apache/ossie)
- [Apache Ossie schema](https://github.com/apache/ossie/blob/main/core-spec/osi-schema.json)
- [Power BI TMDL overview](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview)
- [Tableau Metadata API](https://help.tableau.com/current/api/metadata_api/en-us/index.html)
