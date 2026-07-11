# How `data_agent` works

`data_agent` is a local Python package behind the Copilot agent. It is not an autonomous service or an MCP server. Copilot selects a skill, writes a typed JSON request, invokes a command, and reads a typed JSON response.

```text
python -m data_agent <command> --input request.json --output response.json
        -> cli.py selects a handler
        -> handler validates the request
        -> semantic, reporting, or Snowflake module performs the operation
        -> io.py writes one atomic response envelope
```

## Package map

| Path | Responsibility |
|---|---|
| `cli.py` | Declares command names, dispatches handlers, normalizes exit behavior, and hides unexpected exception detail from response JSON. |
| `io.py` | Reads bounded JSON requests, validates common string fields, creates response envelopes, and writes responses atomically. |
| `config.py` | Loads the single non-secret Snowflake YAML configuration into immutable settings. |
| `bi/extract.py` | Detectable source adapters for Power BI TMDL/PBIP, Tableau `.twb`, generic JSON/YAML, and neutral IR. Every adapter emits neutral semantic IR. |
| `semantic/conversion.py` | Runs the complete source-to-candidate workflow, validates against the vendored Ossie schema, and writes the conversion manifest. |
| `semantic/ingestion.py` | Converts neutral IR into Ossie datasets, fields, relationships, metrics, and custom extensions while collecting issues. |
| `semantic/models.py` | Loads, validates, enumerates, and searches Ossie JSON/YAML documents. |
| `semantic/compiler.py` | Compiles a small governed metric/dimension/filter plan into Snowflake SQL. It remains intentionally narrower than conversion. |
| `security/sql.py` | Parses Snowflake SQL and applies the POC read-only policy. |
| `tools/snowflake.py` | Performs optional browser-SSO connection, metadata discovery, query execution, and cancellation. |
| `tools/result_validation.py` | Applies offline result checks before interpretation or report rendering. |
| `reporting/render.py` | Produces Python-generated accessible SVG charts and self-contained responsive HTML reports. |
| `tools/memory.py` | Writes a small evidence-backed note to `memory/pending/`; it does not change semantic models. |

## Response contract

Every response contains:

- `request_id`: caller correlation ID.
- `status`: command outcome.
- `warnings`: recoverable limitations or review items.

Commands add domain-specific fields such as `candidate_path`, `manifest_path`, `query_id`, `rows`, `svg`, or `report_path`. Expected contract errors return exit code `2`; unexpected internal failures return exit code `3` and omit internal exception detail from the JSON response.

## Semantic conversion versus analysis

Conversion is fully offline and writes only candidate artifacts. Analysis searches `semantic/certified/` by default, compiles a structured plan when possible, optionally executes Snowflake SQL, validates the result, and then renders an answer or report. Candidate semantics never silently become certified semantics.

See [Semantic conversion](SEMANTIC_CONVERSION.md), [Tool contracts](TOOLS.md), and [Operating guide](OPERATING_GUIDE.md).
