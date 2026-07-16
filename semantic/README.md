# Semantic models

- `models/` contains OSI models available to the analysis agent.
- `generated/` contains replaceable model and manifest pairs created from BI exports.
- `schemas/` documents the authoritative schema location. The schema itself comes from the pinned
  `ossie-main/` Apache Ossie Git submodule; this directory does not contain a duplicate.

Use the `osi-semantic-model-builder` skill or run:

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py SOURCE \
  --model-name MODEL --review-ui
```

Use Business or Analyst view to review meaning, mappings, keys, relationships, translations,
expressions, and AI context. **Apply and validate** creates audited decisions and a patch, runs the
official/readiness validators plus `tests/<model>.yaml` when present, and promotes only a clean
model after destination confirmation. Manual copying is not the normal promotion path. See
[Semantic models](../docs/SEMANTIC_MODELS.md).
