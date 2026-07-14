# Supported inputs

## Power BI

Provide an unpacked PBIP/TMDL directory. The extractor reads tables, columns, keys,
relationships, descriptions, display folders, formats, and simple DAX aggregates. Portable
translations use `ANSI_SQL`; DAX remains in source metadata extensions. Complex DAX and
unsupported constructs remain review items. If physical sources are absent, pass a source map:

```json
{"Orders": "DEMO.ANALYTICS.ORDERS", "Customers": "DEMO.ANALYTICS.CUSTOMERS"}
```

## Tableau

Default to a `.tds` datasource when one is available; it is the normal semantic input and carries
the datasource fields, aggregations, calculations, and connection metadata. Use
`examples/tableau/world.tds` as the working example. A `.twb` workbook is also supported when the
workbook is the available source. A `.tde` is binary and must have a same-named `.tds` sibling or
an explicit `--descriptor`.

Use a source map for the real target Snowflake relation and a field map when Tableau display names
differ from SQL aliases:

```json
{
  "World Indicators": {
    "Birth Rate": "birth_rate",
    "CO2 Emissions": "co2_emissions"
  }
}
```

Field-map values must be unquoted identifiers. Expose spaced or quoted source columns through a
view with simple aliases. Treat `REPLACE_WITH_DATABASE...` source values as blocking placeholders,
not usable mappings.

The extractor retains Tableau descriptions, captions/aliases, measure folders, semantic roles,
formats, aggregations, and formulas. Physical columns and translated aggregates use `ANSI_SQL`;
calculated expressions retain a `TABLEAU` dialect and gain SQL only when translation is exact.

## Generic JSON or YAML

Use a top-level `datasets` or `tables` array. Datasets may contain `fields`/`columns`,
`metrics`/`measures`, `source`, `primary_key`, and `unique_keys`. Top-level relationships and
metrics are also accepted. Supplied descriptions, labels, `ai_context`, synonyms, and single- or
multi-dialect expressions are retained.

## Neutral IR and existing Ossie

Neutral IR requires `ir_version` and `datasets`. Existing Ossie requires `version` and
`semantic_model`. Both pass through schema validation and produce a conversion manifest.

## Translation states

- `exact`: direct structural or aggregate translation.
- `equivalent-with-assumptions`: usable mapping with a recorded assumption.
- `partial`: only part of the source behavior is represented.
- `unsupported`: preserved but not emitted as an executable core expression.
- `requires-human-review`: evidence is insufficient for a usable expression.
