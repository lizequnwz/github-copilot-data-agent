# Semantic conversion

The conversion workflow turns source semantic metadata into a usable, reviewable Apache Ossie candidate without discarding vendor-specific expressions.

## Golden source

The core contract is Apache Ossie `0.2.0.dev0`: datasets, fields, many-to-one relationships, metrics, dialect expressions, AI context, and JSON-string custom extensions. The original [`open-semantic-interchange/ossie`](https://github.com/open-semantic-interchange/ossie) repository is the project-selected source; it now redirects new development to [`apache/ossie`](https://github.com/apache/ossie). The schema vendored at `semantic/schemas/osi-0.2.0.dev0.schema.json` is used for deterministic offline validation.

The upstream draft is mutable. Updating the vendored schema requires re-running all conversion fixtures and reviewing generated model diffs.

## Workflow

```text
source asset
  -> format detection
  -> source extractor
  -> neutral semantic IR 1.0
  -> conservative expression translation
  -> Ossie 0.2.0.dev0 emitter
  -> JSON Schema validation
  -> candidate .osi.yaml + .conversion.json manifest
  -> representative compilation and source comparison
  -> human certification
```

The neutral IR is the loss-accounting boundary. It retains source IDs, source expressions, physical mappings, relationships, unsupported constructs, and a source snapshot hash before Ossie emission.

## Supported inputs

| Input | Detection | Current extraction |
|---|---|---|
| Power BI PBIP/TMDL | Directory containing `.tmdl` | Tables, columns, data types, key flags, relationships, simple DAX aggregates, source expressions, selected unsupported constructs |
| Tableau workbook | `.twb` file | Data sources, physical table, dimensions, time fields, simple aggregate calculations, unsupported LOD/table calculations |
| Tableau datasource / extract | `.tds`, or `.tde` with a same-named `.tds` | Datasource metadata, metadata-only fields, default aggregations as reviewable metrics, direct calculations, and source snapshot hashing across descriptor/extract |
| Generic semantic YAML/JSON | `datasets` or `tables` array | Datasets/tables, fields/columns, metrics/measures, relationships, keys, descriptions |
| Neutral semantic IR | `ir_version` plus `datasets` | Direct Ossie emission |
| Existing Ossie | `version` plus `semantic_model` | Validation and candidate manifest generation |

Binary `.pbix` and packaged `.twbx` files must first be unpacked or exported to PBIP/TMDL and `.twb`. A raw Tableau `.tde` is binary and needs a `.tds` descriptor; use a same-named sibling or pass `descriptor_path` when the descriptor has a different name or location. The descriptor supplies fields, default aggregations, calculations, and datasource identity. Live Power BI XMLA and Tableau Metadata API ingestion are later adapters; they should emit the same neutral IR.

## Translation behavior

Simple aggregates are translated only when their meaning is direct:

- DAX: `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, and `DISTINCTCOUNT` over one model column.
- Tableau: `SUM`, `AVG`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, and `COUNTD` over one field.
- Generic input: a supplied normalized SQL expression is preserved.

Complex DAX, M, calculation groups, Tableau LOD expressions, table calculations, row-level roles, parameters, and filters stay in source metadata or are listed as review issues. They are never labeled exact automatically.

Translation states are:

- `exact`: direct structural or expression mapping.
- `equivalent-with-assumptions`: usable mapping with an explicit assumption.
- `partial`: only part of the source construct is represented.
- `unsupported`: retained for review but not emitted as a core construct.
- `requires-human-review`: no safe normalized expression was produced.

## Commands

The friendly repository script is:

```bash
uv run python scripts/convert_semantic.py SOURCE [--source-type auto] [--model-name NAME]
```

For agent and automation use, call the typed command:

```bash
uv run python -m data_agent semantic-convert --input request.json --output response.json
```

Example request:

```json
{
  "request_id": "convert-sales-v1",
  "source_path": "incoming/sales-model",
  "source_type": "auto",
  "model_name": "sales",
  "source_map": {
    "Orders": "PROD.ANALYTICS.ORDERS"
  },
  "field_map": {
    "Orders": {
      "Order Date": "order_date"
    }
  }
}
```

Lower-level commands—`powerbi-extract`, `tableau-extract`, and `ir-to-osi`—remain available for inspecting or adjusting intermediate output.

### Tableau `.tds` / `.tde` mapping

For a Tableau extract, use a warehouse table or view that exposes normalized, unquoted aliases. A `.tde` does not provide a Snowflake relation on its own.

```json
{
  "source_map": {
    "World Indicators": "ANALYTICS.PUBLISHED.WORLD_INDICATORS"
  },
  "field_map": {
    "World Indicators": {
      "Birth Rate": "birth_rate",
      "CO2 Emissions": "co2_emissions"
    }
  }
}
```

Then run:

```bash
uv run python scripts/convert_semantic.py examples/tableau/world.tds \
  --model-name world_indicators \
  --source-map examples/tableau/world-source-map.example.json \
  --field-map examples/tableau/world-field-map.example.json
```

Copy and edit the supplied map files first. A `REPLACE_WITH...` value remains unresolved and produces a blocking review issue. The adapter emits Tableau default aggregations such as `Avg` as metric expressions such as `AVG(world_indicators.birth_rate)`, with `equivalent-with-assumptions` status because a Tableau visualization can override its default aggregation. Complex LOD, table calculations, and unsupported formulas remain review items.

## Candidate artifacts

`semantic/candidates/` contains generated pairs only:

```text
sales.osi.yaml
sales.conversion.json
```

The manifest records source and model hashes, source type, Ossie version, schema validity, object counts, translation-state counts, blocking/review issues, and a standard review checklist. Delete or regenerate candidates freely; analysis uses `semantic/certified/` by default.

## Adding another source format

1. Add an extractor that returns neutral IR 1.0.
2. Preserve the immutable source hash and original expressions.
3. Normalize physical datasets, fields, metrics, and many-to-one relationships.
4. Label every non-trivial translation.
5. Route the format through `semantic-convert`.
6. Add a small source fixture and assertions for object counts, expressions, issues, and schema validation.
7. Update this table and the `osi-semantic-builder` skill.

Do not add a source-specific path directly to the Ossie emitter; all source adapters pass through neutral IR so loss and assumptions remain visible.
