---
name: osi-semantic-builder
description: Detect, extract, convert, validate, and review Power BI, Tableau, generic, neutral IR, or existing Apache Ossie semantic metadata.
---

# Purpose

Turn a user-provided semantic asset into a usable Apache Ossie candidate while preserving source meaning, expressions, lineage, and conversion loss. Apache Ossie was formerly Open Semantic Interchange (OSI); use the vendored `0.2.0.dev0` schema and the upstream sources listed in `docs/REFERENCES.md`.

# Trigger

Use this skill when the user provides or references:

- an unpacked Power BI PBIP/TMDL directory
- a Tableau `.twb` workbook
- generic semantic JSON or YAML
- neutral semantic IR
- an Ossie/OSI document to validate or normalize

# Required workflow

1. Identify the source path, desired model name, and intended physical platform.
2. Read `docs/SEMANTIC_CONVERSION.md` for the supported input and translation boundary.
3. Detect the format with `semantic-convert` unless the user specifies it.
4. For PBIP/TMDL with unresolved physical tables, request or build a `source_map` from reviewed metadata. Do not invent a production table.
5. Run the complete workflow:

   ```bash
   uv run python scripts/convert_semantic.py SOURCE --model-name MODEL
   ```

   For typed automation, use `semantic-convert` with JSON input/output.
6. Inspect both files under `semantic/candidates/`: the `.osi.yaml` candidate and `.conversion.json` manifest.
7. Report source type and hash, schema status, object counts, translation-state counts, blocking issues, and review issues.
8. Resolve mechanical issues when evidence is available, rerun conversion, and confirm the model remains schema-valid.
9. Compile representative metrics where possible and compare results with the source BI artifact before recommending certification.

# Translation rules

- Every source adapter emits neutral semantic IR before Ossie.
- Preserve source object IDs, physical mappings, DAX/Tableau expressions, and the source snapshot hash.
- Map only direct supported expressions into Ossie core dialect expressions.
- Classify non-trivial translations as `exact`, `equivalent-with-assumptions`, `partial`, `unsupported`, or `requires-human-review`.
- Store vendor metadata in `ENTERPRISE_DATA_AGENT` custom extensions as JSON strings.
- Ossie relationships are many-to-one: `from` is the many side and `to` is the one side.
- Never label complex DAX, M, LOD, table calculation, parameter, filter, or security logic exact without an explicit reviewed translation.

# Output contract

Return:

- candidate and manifest paths
- Ossie version and schema validation status
- datasets, fields, relationships, and metric counts
- preserved expressions and untranslated constructs
- blocking issues, assumptions, and required reviewer actions
- a clear statement that certification is or is not recommended

# Stop conditions

Do not recommend certification when the schema is invalid, a physical source is unresolved, relationship endpoints or keys are unknown, a source expression was lost, or unsupported logic is labeled exact.
