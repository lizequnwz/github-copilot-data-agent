# Runnable examples

Run commands from the repository root.

## Validation-only inspection

Validate an existing promoted or generated Ossie document without conversion or promotion:

```bash
uv run python -m data_agent osi-validate \
  --input examples/requests/osi-validate.json --output /tmp/osi-validation.json
```

## Raw conversion only

Omit every review option when the requested branch stops at deterministic artifacts:

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py \
  tests/fixtures/generic/sales.yaml --model-name demo_generic
```

## Power BI TMDL

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py \
  tests/fixtures/powerbi --model-name demo_powerbi --review-ui
```

## Tableau workbook

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py \
  tests/fixtures/tableau/sales.twb --model-name demo_tableau --review-ui
```

## Tableau datasource with mappings

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py \
  examples/tableau/world.tds --model-name world_indicators \
  --source-map examples/tableau/world-source-map.demo.json \
  --field-map examples/tableau/world-field-map.example.json --review-ui
```

The demo map uses a synthetic Snowflake object. Copy the `.example.json` variant and replace its
placeholder when adapting the command to a real model.

## Generic YAML

```bash
uv run python .github/skills/osi-semantic-model-builder/scripts/build_model.py \
  tests/fixtures/generic/sales.yaml --model-name demo_generic --review-ui
```

Each first-stage command prints a summary and writes:

```text
semantic/generated/<model>.raw.osi.yaml
semantic/generated/<model>.conversion.json
```

For commands containing `--review-ui`, the browser workspace opens after conversion. Resolve
blocking mappings, review important fields, relationships, metric expressions, and AI context,
then select **Apply and validate**. A clean
review writes `<model>.osi.yaml` and promotes it to `semantic/models/<model>.yaml`; generated
output is replaceable. Add `--no-open` for a headless session, or apply exported decisions later
with `--review-decisions PATH`.
