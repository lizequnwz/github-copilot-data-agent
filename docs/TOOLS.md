# Typed tool reference

The POC exposes reviewed CLI commands through `uv run python -m data_agent`. These are executable repository tools invoked through Copilot's default shell/execute capability; they are not native Copilot or MCP tools.

Every command reads one JSON object and writes one JSON object:

```bash
uv run python -m data_agent COMMAND --input request.json --output response.json
```

Every request should include a unique `request_id`. Responses include `request_id`, `status`, and `warnings`. Generated SQL belongs in the JSON request file, never in the shell command.

## Snowflake setup and execution

All live commands use `snowflake_config.yaml`, the only supported POC configuration source. They require browser SSO and `configuration_confirmed: true` after the agent displays the non-secret context and the user confirms it.

| Command | Required request fields | Purpose |
|---|---|---|
| `config-check` | `request_id`; optional `config_path` | Validate placeholders, SSO method, limits, and public connection context without connecting. |
| `connection-check` | `request_id`, `configuration_confirmed` | Open browser SSO and return the effective user, role, warehouse, database, and schema. |
| `search-objects` | `request_id`, `configuration_confirmed`, `query` | Search approved database table names and comments. |
| `describe-object` | `request_id`, `configuration_confirmed`, `object` | Return columns for `DATABASE.SCHEMA.OBJECT`. |
| `sample-values` | `request_id`, `configuration_confirmed`, `object`, `column` | Return bounded value counts; sensitive-looking columns are blocked unless policy and request both authorize them. |
| `profile-table` | `request_id`, `configuration_confirmed`, `object`, `columns` | Return row count, null counts, and approximate distinct counts for up to 20 columns. |
| `validate-sql` | `request_id`, `sql`; optional object policy | Parse one Snowflake query and reject writes, `SELECT *`, stages, dynamic SQL, blocked schemas, and non-allowlisted objects. |
| `execute-readonly` | `request_id`, `configuration_confirmed`, `sql`; optional `parameters`, `max_rows` | Revalidate and execute a bounded query with role, tag, timeout, row, and byte controls. |
| `cancel-query` | `request_id`, `configuration_confirmed`, `query_id` | Cancel a long-running Snowflake query. |

`execute-readonly` returns columns, rows, row count, truncation status, query ID, effective configured role, execution time, and SQL-validation evidence.

## Open Semantic Interchange

| Command | Required request fields | Purpose |
|---|---|---|
| `osi-validate` | `request_id`, `model_path` | Validate JSON/YAML against the pinned OSI schema. |
| `osi-search` | `request_id`, `query`; optional `roots`, `limit` | Search certified models by default, or explicit candidate roots when requested. |
| `osi-compile` | `request_id`, `model_path`, `plan` | Compile a governed metric/dimension/filter plan into bounded Snowflake SQL. |
| `semantic-diff` | `request_id`, `before_path`, `after_path` | Compare normalized semantic documents and return content hashes. |
| `semantic-convert` | `request_id`, `source_path`; optional `source_type`, `model_name`, `source_map` | Detect, extract, emit, validate, and write a candidate Ossie YAML plus conversion manifest. |
| `powerbi-extract` | `request_id`, `source_path`; optional `source_artifact`, `source_map` | Extract unpacked PBIP/TMDL tables, fields, keys, relationships, and supported simple measures to neutral semantic IR. |
| `tableau-extract` | `request_id`, `source_path`; optional `source_artifact`, `source_map` | Extract a `.twb` data source, fields, and supported simple calculated measures to neutral semantic IR. |
| `ir-to-osi` | `request_id`, `semantic_ir`; optional `model_name` | Convert neutral IR to candidate OSI content while preserving source metadata and review warnings. |

`semantic-convert` accepts `auto`, `powerbi`, `tableau`, `generic`, `semantic-ir`, or `osi` as `source_type`. It writes only under `semantic/candidates/`. See [Semantic conversion](SEMANTIC_CONVERSION.md) for the IR contract, translation states, and review workflow.

## Validation, reporting, and memory

| Command | Required request fields | Purpose |
|---|---|---|
| `validate-result` | `request_id`, `result`; optional grain/range checks | Check emptiness, truncation, required columns, duplicate grain, nulls, and numeric ranges. |
| `render-chart` | `request_id`, `spec` | Render a declarative accessible bar or line SVG from 1–100 aggregate points, including axes and direct value labels. |
| `render-report` | `request_id`, `output_path`, passing `validation`, `summary`, `columns`, `rows`, `metadata` | Render escaped, responsive HTML with optional safe chart, definitions, methodology, caveats, provenance, and SQL appendix. |
| `memory-propose` | `request_id`, `concept`, `evidence`; optional definitions/scope/owner | Write an evidence-backed proposal to `memory/pending/`. |

Report metadata requires `title`, `source_tier`, `semantic_model`, `confidence`, `data_freshness`, `query_id`, `role`, and `request_id`. Reports are self-contained responsive HTML with light/dark and print support. Generated reports belong under `reports/generated/`.

## Exit behavior

- `0`: successful command.
- `2`: invalid request, failed policy/validation, or configuration still required.
- `3`: unexpected internal failure; the response intentionally omits exception details that might expose sensitive data.
