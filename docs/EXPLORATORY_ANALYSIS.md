# Exploratory analysis workspace

The default Ask Data experience is an iterative analytical loop rather than a governance workflow:

```text
question -> SQL -> read-only query -> inspect -> chart -> refine -> share
```

Semantic models and validation remain available when a useful exploration becomes a recurring
analysis, shared metric, or published decision artifact.

## Quick start

Run the offline example:

```bash
uv sync --extra dev
uv run python scripts/demo_exploration.py
```

This writes `analysis.md`, `analysis.ipynb`, and the corresponding request/response JSON under
`reports/generated/exploratory-sales/`.

For the full notebook environment:

```bash
uv sync --extra notebook
uv run jupyter lab reports/generated/exploratory-sales/analysis.ipynb
```

## Flexible SQL request

Exploratory requests need SQL and little else:

```json
{
  "request_id": "quick-look",
  "analysis_mode": "exploratory",
  "question": "What changed by region?",
  "sql": "SELECT region, SUM(amount) AS sales FROM DB.SCHEMA.ORDERS GROUP BY region",
  "parameters": [],
  "execute": true,
  "configuration_confirmed": true
}
```

`analysis_mode` may be omitted when the request has SQL and no `model_path`. Projection wildcards,
literal filters, queries without an explicit `LIMIT`, missing formula metadata, and sources outside
`allowed_objects` or configured blocked-schema lists are accepted in exploratory mode. Snowflake
role permissions remain authoritative for data access.

Snowflake execution still permits only a parsed read-only query. Tokens stay in the environment,
the non-secret connection context must be confirmed, and configured timeout, fetched-row, and
result-byte protections remain active.

## Notebook behavior

The generated notebook contains:

1. Saved analysis evidence.
2. Editable question, SQL, parameters, and row-fetch target.
3. An opt-in live execution cell routed through `data_agent.analysis.analyze`.
4. A pandas table and a quick configurable chart.
5. An optional self-contained exploratory HTML report.
6. Guidance for moving the exploration toward validation.

`USE_SAVED_RESPONSE` defaults to `True`, so Run All preserves the saved result. Set it to `False`
to re-plan edited SQL. `RUN_LIVE` defaults to `False` so that step still does not unexpectedly query
Snowflake. Set `RUN_LIVE = True` and `CONFIGURATION_CONFIRMED = True` after reviewing the configured
context.

Do not create a raw Snowflake connection in notebook cells. Routing reruns through `analyze`
preserves read-only parsing, authentication handling, timeouts, query IDs, serialization, and local
result protections.

## Optional validation

Exploratory results return `result_validation.status: not_run` unless the request includes
`result_checks` or sets `validate_result: true`.

Add checks when they answer a real assurance need:

```json
{
  "validate_result": true,
  "result_grain": ["region"],
  "result_checks": {
    "required_columns": ["region", "sales"],
    "required_non_null": ["region"],
    "numeric_ranges": {"sales": {"min": 0}}
  }
}
```

Other maturity options are:

- move a repeated calculation to a request-scoped derived metric;
- compile through a promoted semantic model;
- use governed ad hoc mode for parameter and source contracts;
- promote a shared definition through Semantic Setup.

These steps increase repeatability and confidence without blocking the initial investigation.

## Reports and publishing

HTML reports may be rendered from exploratory or validated results. Reports without passing checks
display **Exploratory · not validated**. Failed checks remain blocking because publishing a known
failure as if it were usable would be misleading.

All generated work stays under `reports/generated/` and is ignored by Git. Review data sensitivity,
definitions, freshness, and caveats before moving an artifact into a committed or externally shared
location.
