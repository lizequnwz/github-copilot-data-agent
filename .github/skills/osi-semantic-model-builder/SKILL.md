---
name: osi-semantic-model-builder
description: Build and review an Apache Ossie/Open Semantic Interchange (OSI) model from exported Power BI PBIP/TMDL, Tableau TWB/TDS/TDE metadata, generic JSON/YAML, neutral semantic IR, or an existing Ossie document. Use when a user wants to import, convert, validate, inspect, enrich, or refresh BI semantic metadata for use by the Snowflake data agent.
allowed-tools: ["read", "search", "edit", "execute"]
---

# OSI semantic model builder

Use a deterministic converter first and an audited semantic review second. Never write the final
OSI model directly from source metadata or from an unaudited LLM response.

## Choose the input path

- Power BI: use an unpacked PBIP/TMDL directory. Export binary `.pbix` files first.
- Tableau: prefer a `.tds`. A `.twb` is supported, while `.tde` requires a `.tds` descriptor.
- Generic: use JSON/YAML with datasets, fields, metrics, and relationships.
- Neutral IR or Ossie: pass the JSON/YAML document directly.

Read [references/supported-inputs.md](references/supported-inputs.md) for mappings and expression
limits and [references/examples.md](references/examples.md) for commands. Read
[references/review-patch.md](references/review-patch.md) only for advanced manual review.

## Stage 1: deterministic raw model

1. Resolve the source path, model name, and intended physical tables/views.
2. Create source and field maps when the export does not resolve physical Snowflake objects.
3. Run the builder from the repository root:

   ```bash
   uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py SOURCE \
     --model-name MODEL
   ```

4. Inspect `<model>.conversion.json` and `<model>.raw.osi.yaml` under `semantic/generated/`.
5. Do not promote the raw model. Resolve mechanical mapping errors and rerun when evidence exists.

The converter uses the schema and validation functions from the pinned `ossie-main` submodule.
Portable translated expressions use `ANSI_SQL`; source-native expressions are preserved in their
official Ossie dialect or in provenance extensions.

## Stage 2: interactive audited review

1. Launch the builder with the source mappings and `--review-ui`:

   ```bash
   uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py SOURCE \
     --model-name MODEL --review-ui
   ```

2. Lead with blocking issues. Ask business users for meaning, exclusions, synonyms, and expected
   questions; ask analysts for mappings, keys, relationships, grain, and expressions.
3. Use the focused editors for descriptions, synonyms, examples, instructions, expressions,
   keys, relationships, and sources. Give every change rationale, evidence, confidence, and
   assumptions. Never invent evidence or alter converter provenance.
4. Select **Apply and validate** and confirm the proposed promotion destination. The backend
   compiles the complete decisions artifact into the audited patch and applies it deterministically.
5. The applier writes `<model>.osi.yaml`, reruns official and readiness validation, records the
   complete before/after audit, and promotes only a clean result to `semantic/models/`.
6. If assumptions remain, leave the reviewed model under `semantic/generated/` and report the
   exact evidence or user decision needed.

Use `--no-open` for a headless launch. Use a downloaded decisions file with
`--review-decisions PATH`. Manual `--review-patch` is an advanced audit/debugging path.

## Optional Snowflake verification

Use `--verify-snowflake` only when warehouse evidence is requested or materially improves
confidence. First run `config-check`, display and confirm the non-secret context, then add
`--configuration-confirmed`. Verification checks metadata and compiles expressions with
`cursor.describe()` without executing analytical queries. Failure prevents promotion for that run
but does not invalidate the raw model.

## Translation boundary

- Preserve source descriptions, titles, aliases, formats, semantic roles, expressions, and hashes.
- Translate only behavior with deterministic evidence; retain other constructs for review.
- Use source titles/captions as deterministic synonyms only when they differ from OSI identifiers.
- Keep DAX in extensions because it is not an official Ossie dialect.
- Never hide unresolved physical mappings, relationship keys, or unsupported expressions.

## Completion output

Return the raw, patch, final, manifest, and promoted paths as applicable; detected source type;
official validation and analysis-readiness status; object counts; assumptions; optional Snowflake
verification status/query IDs; and the next concrete review action.
