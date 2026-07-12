# Runnable examples

Run commands from the repository root.

## Power BI TMDL

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py \
  tests/fixtures/powerbi --model-name demo_powerbi
```

## Tableau workbook

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py \
  tests/fixtures/tableau/sales.twb --model-name demo_tableau
```

## Tableau datasource with mappings

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py \
  examples/tableau/world.tds --model-name world_indicators \
  --source-map examples/tableau/world-source-map.demo.json \
  --field-map examples/tableau/world-field-map.example.json
```

The demo map uses a synthetic Snowflake object. Copy the `.example.json` variant and replace its
placeholder when adapting the command to a real model.

## Generic YAML

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py \
  tests/fixtures/generic/sales.yaml --model-name demo_generic
```

Each command prints a summary and writes:

```text
semantic/generated/<model>.osi.yaml
semantic/generated/<model>.conversion.json
```

Open the manifest first. Resolve blocking physical mappings, then inspect important fields,
relationships, and metric expressions in the YAML. Rerun the command after changing source or map
files; generated output is replaceable.
