# Semantic models

- `models/` contains OSI models available to the analysis agent.
- `generated/` contains replaceable model and manifest pairs created from BI exports.
- `schemas/` contains the vendored Apache Ossie schema used for offline validation.

Use the `osi-semantic-model-builder` skill or run:

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py SOURCE \
  --model-name MODEL
```

Review generated physical mappings, keys, relationships, and important metric expressions before
copying a model into `models/`. See [Semantic models](../docs/SEMANTIC_MODELS.md).
