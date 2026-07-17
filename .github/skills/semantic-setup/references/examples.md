# Runnable examples

Run commands from the repository root.

## Validation-only inspection

```bash
uv run data-agent advanced osi-validate \
  --input examples/semantic-setup/validate-model.json \
  --output /tmp/osi-validation.json
```

## Raw conversion only

```bash
uv run data-agent model setup tests/fixtures/generic/sales.yaml \
  --model-name demo_generic --no-review
```

## Power BI TMDL

```bash
uv run data-agent model setup tests/fixtures/powerbi --model-name demo_powerbi
```

## Tableau workbook

```bash
uv run data-agent model setup tests/fixtures/tableau/sales.twb --model-name demo_tableau
```

## Tableau datasource with mappings

```bash
uv run data-agent model setup examples/semantic-setup/tableau/world.tds \
  --model-name world_indicators \
  --source-map examples/semantic-setup/tableau/world-source-map.demo.json \
  --field-map examples/semantic-setup/tableau/world-field-map.example.json
```

The demo map uses a synthetic Snowflake object. Copy the `.example.json` variant and replace its
placeholder for a real model.

Generated work is written under:

```text
workspaces/models/<model>.raw.osi.yaml
workspaces/models/<model>.conversion.json
```

The review workspace opens after conversion by default. Resolve blocking mappings, review important
fields, relationships, metrics, and business context, then select **Apply and validate**. A clean
review promotes to `semantic/models/<model>.yaml`. Use `--no-open` for a headless session.
