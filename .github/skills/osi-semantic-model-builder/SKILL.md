---
name: osi-semantic-model-builder
description: Build an Apache Ossie/Open Semantic Interchange (OSI) model from exported Power BI PBIP/TMDL, Tableau TWB/TDS/TDE metadata, generic JSON/YAML, neutral semantic IR, or an existing Ossie document. Use when a user wants to import, convert, validate, inspect, or refresh BI semantic metadata for use by the Snowflake data agent.
---

# OSI semantic model builder

Turn exported BI semantics into a schema-valid OSI model while preserving original expressions,
source identifiers, physical mappings, and any translation gaps.

## Choose the input path

- Power BI: use an unpacked PBIP/TMDL directory. Binary `.pbix` files must be exported first.
- Tableau: use `.twb` or `.tds`; a `.tde` requires a matching `.tds` descriptor.
- Generic: use JSON or YAML containing datasets/tables, fields, metrics, and relationships.
- Neutral IR or Ossie: pass the JSON/YAML file directly.

Read [references/supported-inputs.md](references/supported-inputs.md) when the source needs mapping
or contains calculations. Read [references/examples.md](references/examples.md) for runnable
commands and expected artifacts.

## Build the model

1. Identify the source path, desired model name, and intended Snowflake tables or views.
2. Detect the format unless the user supplied `--source-type`.
3. Create a JSON source map when the BI export does not resolve physical tables. For Tableau,
   create a field map when display names do not match unquoted Snowflake column aliases.
4. Run the bundled builder from the repository root:

   ```bash
   uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py SOURCE \
     --model-name MODEL
   ```

5. Inspect both paths printed by the script under `semantic/generated/`:
   - `<model>.osi.yaml`: generated OSI model.
   - `<model>.conversion.json`: source hash, translation summary, issues, and review checklist.
6. Resolve mechanical mapping issues when evidence is available and rerun the same command.
7. Copy a reviewed model into `semantic/models/` only when its physical sources, keys,
   relationships, and important metrics are usable for analysis.

## Translation boundary

- Route every source through neutral semantic IR before OSI emission.
- Translate only direct aggregates such as SUM, AVG, MIN, MAX, COUNT, and distinct count.
- Preserve DAX, Tableau formulas, source IDs, and snapshot hashes in custom extensions.
- Mark non-trivial mappings as `exact`, `equivalent-with-assumptions`, `partial`, `unsupported`,
  or `requires-human-review`.
- Never invent physical tables, columns, relationship keys, or equivalent calculations.

## Completion output

Return the generated model and manifest paths, detected source type, schema status, dataset/field/
relationship/metric counts, preserved expressions, blockers, assumptions, and the next concrete
review action. A schema-valid file can still require mapping or calculation review.

