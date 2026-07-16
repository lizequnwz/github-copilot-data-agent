# Snowflake analysis helper contracts

- [Semantic search and compilation](#semantic-search-and-compilation)
- [Configuration and connection](#configuration-and-connection)
- [SQL validation and execution](#sql-validation-and-execution)
- [Result validation](#result-validation)
- [Metadata diagnosis](#metadata-diagnosis)

Run helpers from the repository root with one JSON request and one JSON response:

```bash
uv run python -m data_agent COMMAND --input REQUEST.json --output RESPONSE.json
```

Every request needs a stable `request_id`. Treat a nonzero exit or `status: error` as a failed
helper call and inspect `message` without exposing local secrets.

## Semantic search and compilation

Use `osi-search` with:

```json
{"request_id":"search","roots":["semantic/models"],"query":"gross sales by region","limit":10}
```

Success is `status: success`; inspect every returned match before choosing a model. A runnable
example lives at `examples/requests/osi-search.json`.

Use `osi-compile` with `model_path` and a semantic `plan` containing `semantic_model`, non-empty
`metric_ids`, `dimensions`, model-defined `filters`, optional `time_range`, selected-field
`order_by`, and positive `max_rows`:

```json
{
  "request_id": "compile",
  "model_path": "semantic/models/demo_sales.yaml",
  "plan": {
    "semantic_model": "demo_sales",
    "metric_ids": ["gross_sales"],
    "dimensions": ["orders.region"],
    "filters": [{"field":"orders.status","operator":"=","value":"completed"}],
    "time_range": {
      "field": "orders.order_date",
      "start": "2026-05-01",
      "end_exclusive": "2026-07-01",
      "label": "May through June 2026"
    },
    "order_by": [{"field":"gross_sales","direction":"desc"}],
    "max_rows": 10
  }
}
```

Success is `status: success`; retain `sql`, `parameters`, `result_grain`, `result_columns`,
`max_rows`, `query_limit`, `period`, and `normalized_plan` as execution evidence. See
`examples/requests/osi-compile.json` for the runnable request.

## Configuration and connection

Use `config-check` with:

```json
{"request_id":"config","config_path":"snowflake_config.yaml"}
```

Proceed only on `status: ready`. Display the returned `configuration` and obtain confirmation; the
response always marks `confirmation_required: true`.

Use `connection-check` only after confirmation:

```json
{
  "request_id": "connection",
  "config_path": "snowflake_config.yaml",
  "configuration_confirmed": true
}
```

Success is `status: success`; retain `query_id` and `actual_context`. Treat `context_mismatch` as a
failed connection gate.

## SQL validation and execution

Use `validate-sql` with the compiled SQL and, when applicable, configured object restrictions:

```json
{
  "request_id": "validate-sql",
  "sql": "SELECT region, SUM(amount) AS gross_sales FROM db.schema.orders GROUP BY region LIMIT 11",
  "blocked_schemas": [],
  "allowed_objects": []
}
```

Success is `status: success` with `validation.valid: true`. Retain the parsed statement type,
referenced objects, and warnings.

Use `execute-readonly` with the exact compiled SQL and parameters:

```json
{
  "request_id": "execute",
  "config_path": "snowflake_config.yaml",
  "configuration_confirmed": true,
  "sql": "SELECT region, SUM(amount) AS gross_sales FROM db.schema.orders WHERE status = %s GROUP BY region LIMIT 11",
  "parameters": ["completed"],
  "max_rows": 10,
  "query_limit": 11
}
```

Success is `status: success`; retain `query_id`, `role`, `columns`, `rows`, `row_count`,
`truncated`, `max_rows`, `query_limit`, execution time, and embedded SQL validation. A response
with `truncated: true` fails the execution gate.

## Result validation

Pass the complete execution result to `validate-result` with the compiled result grain and all
question-specific checks:

```json
{
  "request_id": "validate-result",
  "result": {"columns":["REGION","GROSS_SALES"],"rows":[["East",128000]],"truncated":false},
  "grain": ["region"],
  "required_columns": ["region","gross_sales"],
  "required_non_null": ["region","gross_sales"],
  "numeric_ranges": {"gross_sales":{"min":0}}
}
```

Success is `status: pass` with no `errors`. Column matching is case-insensitive, while returned
column names remain unchanged in the evidence.

## Metadata diagnosis

Use `search-objects`, `describe-object`, `sample-values`, or `profile-table` only after completing
the connection gate and only to diagnose a physical mapping or model-coverage gap. Include
`config_path` and `configuration_confirmed: true` in every request. Keep object names fully
qualified as `DATABASE.SCHEMA.OBJECT`, select explicit profile columns, and treat sensitive-looking
sample columns as blocked unless configuration and request authorization both permit them.
