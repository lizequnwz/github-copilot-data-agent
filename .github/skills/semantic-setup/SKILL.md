---
name: semantic-setup
description: Import, inspect, refresh, review, validate, and promote Apache Ossie semantic models from Power BI, Tableau, generic JSON or YAML, neutral semantic IR, or existing Ossie documents. Use when Ask Data reports missing model coverage or when a user wants to create or improve shared semantics.
---

# Semantic Setup

Use the normal onboarding command from the repository root:

```bash
uv run data-agent model setup SOURCE --model-name MODEL
```

This deterministic path converts the source, writes model work under `workspaces/models/`, and opens
the guided review workspace by default.

## Workflow

1. Resolve the source, model name, intended Snowflake tables or views, business domain, owner, and
   important competency questions when available.
2. Read [references/supported-inputs.md](references/supported-inputs.md) for the selected source
   format. Add source or field maps only when physical mappings cannot be resolved deterministically.
3. Run `data-agent model setup`. Inspect the detected source type, object counts, refresh impact,
   blocking issues, deterministic raw model, and conversion manifest.
4. In the review workspace, lead with blocking coverage gaps. Ask business reviewers for meaning,
   exclusions, synonyms, and expected questions; ask analysts for sources, keys, relationships,
   grain, and expressions.
5. Preserve converter provenance. Keep raw JSON operations advanced. Use guided decisions for normal
   review and capture rationale, evidence, confidence, and assumptions automatically.
6. Apply and validate only after the user confirms the proposed destination. Promotion requires
   official Ossie validation, analysis readiness, competency tests when configured, and no
   unresolved assumptions.
7. Return the raw, manifest, reviewed, and promoted paths; validation and coverage state; remaining
   blockers; and the next concrete action.

## Variants

- Use `data-agent advanced osi-validate` for validation-only inspection.
- Use `--no-review` for deterministic conversion without opening the workspace.
- Use `--review-decisions PATH` to replay guided decisions, or `--review-patch PATH` for advanced
  audited patch replay. Either option replaces the interactive workspace for that run.
- Use `--verify-snowflake --configuration-confirmed` only after the user confirms the displayed
  non-secret context.
- Read [references/review-patch.md](references/review-patch.md) only for advanced patch replay or
  audit automation.
- Read [references/examples.md](references/examples.md) for runnable source-specific examples.

Never promote an incomplete or assumption-bearing model implicitly. Failed review preserves the
draft and previously promoted model.
