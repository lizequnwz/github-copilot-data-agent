---
name: osi-semantic-model-builder
description: Build OSI semantic models from supported BI exports or existing semantic documents. Use for deterministic raw conversion, validation-only inspection, audited review and promotion, refresh and diff, or semantic enrichment for the Snowflake data agent.
allowed-tools: ["read", "search", "edit", "execute"]
---

# OSI semantic model builder

Apply the promotion gate from `AGENTS.md`. Produce executable OSI through deterministic conversion
and audited review decisions; treat the raw artifact as immutable input to the review applier.

## Choose the operation

- **Validation-only inspection**: validate an existing Ossie document with `osi-validate`, report
  official and readiness results, and stop without conversion, review, or promotion.
- **Raw conversion**: run the deterministic builder without a review option, inspect the raw model
  and manifest, report review blockers, and stop.
- **Full onboarding or enrichment**: run the builder once with `--review-ui`; conversion completes
  before the workspace opens.
- **Refresh**: use the full-review branch against a model already in `semantic/models/`, and review
  every emitted object-level change before editing affected objects.
- **Audited decisions replay**: use `--review-decisions PATH` for exported guided-review decisions.
- **Manual patch**: use `--review-patch PATH` only for advanced audit, debugging, or automation that
  cannot use guided decisions; read
  [references/review-patch.md](references/review-patch.md) before this branch.

## Choose the input path

- Power BI: use an unpacked PBIP/TMDL directory. Export binary `.pbix` files first.
- Tableau: prefer a `.tds`. A `.twb` is supported, while `.tde` requires a `.tds` descriptor.
- Generic: use JSON/YAML with datasets, fields, metrics, and relationships.
- Neutral IR or Ossie: pass the JSON/YAML document directly.

Read the selected source section in
[references/supported-inputs.md](references/supported-inputs.md) for mappings and expression limits.
Read [references/examples.md](references/examples.md) when a runnable command for that source is
needed.

## Raw conversion gate

1. Resolve the source path, model name, and intended physical tables/views.
   Also capture the business domain, definition owner, and competency questions when available.
2. Create source and field maps when the export does not resolve physical Snowflake objects.
3. Run the builder from the repository root:

   ```bash
   uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py SOURCE \
     --model-name MODEL
   ```

4. Inspect `<model>.conversion.json` and `<model>.raw.osi.yaml` under `semantic/generated/`.
5. For a refresh, account for every emitted change and classify its breaking, semantic, or metadata
   impact before opening affected object editors.
6. Resolve evidence-backed mechanical mapping errors by correcting inputs or maps and rerunning the
   converter. Keep semantic decisions for audited review.

The raw conversion gate passes only when the command returns success, the raw model and conversion
manifest exist, official schema validation passes, and the reported source type, object counts,
blocking issues, assumptions, and refresh changes are accounted for. A passed raw gate permits
review but never promotion of the raw artifact.

The converter uses the schema and validation functions from the pinned `ossie-main` submodule.
Portable translated expressions use `ANSI_SQL`; source-native expressions are preserved in their
official Ossie dialect or in provenance extensions.

## Review and promotion gate

For full onboarding, enrichment, or refresh, launch the builder once with the source mappings and
`--review-ui`:

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py SOURCE \
  --model-name MODEL --review-ui
```

1. Lead with blocking issues. Ask business users for meaning, exclusions, synonyms, and expected
   questions; ask analysts for mappings, keys, relationships, grain, and expressions.
2. Select Business or Analyst review mode. Use Catalog to review table and column descriptions in
   context and commit related description edits together. Use the drawer for
   advanced properties; Close, Cancel, and Escape discard or confirm only unsaved drawer edits and
   never require incomplete fields. Add metrics with the guided aggregation templates or custom
   expression mode, then use the non-writing preview before saving the draft. The workspace records
   the user's save action as automatic audit metadata; reviewers do not fill a separate change-note
   form.
   Key and relationship selectors use physical source-column identifiers, not semantic field
   names. A semantic field rename must not rewrite those physical references.
   Raw JSON operations are advanced-only. Never alter converter provenance.
3. Select **Apply and validate** and confirm the proposed promotion destination. The backend
   compiles the complete decisions artifact into the audited patch and applies it deterministically.
4. The applier writes `<model>.osi.yaml`, reruns official and readiness validation, records the
   complete before/after audit, runs `semantic/tests/<model>.yaml` when present, and promotes only a
   clean result to `semantic/models/`.
5. If assumptions remain, leave the reviewed model under `semantic/generated/` and report the
   exact evidence or user decision needed.

The promotion gate passes only when every blocking issue has an audited disposition, every applied
operation has rationale, evidence, confidence, and assumptions, official validation and analysis
readiness pass, the matching competency fixture passes when present, the destination was explicitly
confirmed, and the result reports the expected promoted path. A review with assumptions may pass
artifact validation but does not pass the promotion gate.

Use `--no-open` for a headless interactive launch.

## Optional Snowflake verification

Use `--verify-snowflake` only when warehouse evidence is requested or materially improves
confidence. Complete the connection gate from `snowflake-analysis`, then add
`--configuration-confirmed`. Verification checks metadata and compiles expressions with
`cursor.describe()` without executing analytical queries. Failure prevents promotion for that run
but does not invalidate the raw model.

## Translation boundary

- Preserve source descriptions, titles, aliases, formats, semantic roles, expressions, and hashes.
- Translate only behavior with deterministic evidence; retain other constructs for review.
- Use source titles/captions as deterministic synonyms only when they differ from OSI identifiers.
- Keep DAX in extensions because it is not an official Ossie dialect.
- Use `reviewed-unsupported` only after an audited reviewer explicitly accepts that a preserved
  source construct remains excluded from executable OSI. This clears the review blocker without
  changing immutable converter provenance.
- Retain unresolved physical mappings, relationship keys, and unsupported expressions as explicit
  blocking review evidence.

## Completion output

Return the operation branch; raw, decisions, patch, final, manifest, and promoted paths as
applicable; detected source type; official validation and analysis-readiness status; object counts;
blocking issues and assumptions; optional Snowflake verification status/query IDs; and the next
concrete review action. For validation-only inspection, return the inspected model path and both
validation statuses without conversion artifacts.
