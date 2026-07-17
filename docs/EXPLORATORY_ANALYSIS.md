# Semantic exploration workspace

Ask Data has one core workflow:

```text
question -> promoted model -> semantic plan -> generated SQL -> inspect -> refine -> share
```

Every query uses a promoted model. Exploration stays lightweight because result checks are optional
and the notebook makes the plan easy to edit.

## Quick start

Run the offline example:

```bash
uv sync --extra dev
uv run python scripts/demo_exploration.py
```

This compiles `semantic/models/demo_sales.yaml` and writes `analysis.md`, `analysis.ipynb`, and the
request/response JSON under `reports/generated/exploratory-sales/`.

For the full notebook environment:

```bash
uv sync --extra notebook
uv run jupyter lab reports/generated/exploratory-sales/analysis.ipynb
```

## Minimal exploratory request

An exploration needs a promoted model and a small semantic plan:

```json
{
  "request_id": "quick-look",
  "question": "How do completed-order sales compare across regions?",
  "model_path": "semantic/models/demo_sales.yaml",
  "plan": {
    "semantic_model": "demo_sales",
    "metric_ids": ["gross_sales"],
    "dimensions": ["orders.region"],
    "filters": [
      {"field": "orders.status", "operator": "=", "value": "completed"}
    ],
    "order_by": [{"field": "gross_sales", "direction": "desc"}],
    "max_rows": 100
  }
}
```

The compiler resolves physical sources, model-defined joins, filter expressions, parameters,
aliases, ordering, and the query limit. The response includes the normalized plan and generated SQL.

If the model has the required fields but lacks a shared metric, add a request-scoped
`derived_metrics` expression using qualified promoted fields. The result remains explicitly
unpromoted. If required fields or relationships are missing, use Semantic Setup; Ask Data does not
bypass the model with arbitrary SQL.

## Notebook behavior

The generated notebook contains:

1. Saved semantic analysis evidence.
2. Editable question, `MODEL_PATH`, and `PLAN`.
3. Compiler-generated SQL and parameters.
4. An opt-in live execution cell routed through `data_agent.analysis.analyze`.
5. A pandas table and quick configurable chart.
6. An optional self-contained HTML report.
7. A switch for adding result validation later.

`USE_SAVED_RESPONSE` defaults to `True`, so Run All preserves saved evidence. Set it to `False` to
compile the edited plan. `RUN_LIVE` defaults to `False`; set it to `True` with
`CONFIGURATION_CONFIRMED = True` only after reviewing the non-secret Snowflake context.

The generated SQL is visible but is not the notebook's editable source. Change the plan or
request-scoped derived expression and let the compiler regenerate SQL. This keeps exploratory work
consistent with shared sources, relationships, and field definitions.

## Optional result validation

Results return `result_validation.status: not_run` unless `validate_result: true` or
`result_checks` is present.

Add only checks that answer a real assurance need:

```json
{
  "validate_result": true,
  "result_checks": {
    "grain": ["region"],
    "required_columns": ["region", "gross_sales"],
    "required_non_null": ["region"],
    "numeric_ranges": {"gross_sales": {"min": 0}}
  }
}
```

Exploration and validation use the same promoted model and semantic plan. Validation changes the
assurance level, not how SQL is sourced.

## Reports and promotion

HTML reports may be created before result checks run and display **Exploratory · not validated**.
Validated reports retain the same model, plan, generated SQL, and query evidence.

A request-scoped derived metric can be useful for many explorations without becoming shared
semantics. Promote it only through Semantic Setup after definition review and competency checks.
Generated analytical work stays under `reports/generated/` and is ignored by Git.
