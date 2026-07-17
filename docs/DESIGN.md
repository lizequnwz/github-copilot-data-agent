# Design

## Product boundary

GitHub Copilot is the conversational interface. The repository is not a service or MCP server.
The agent follows a skill and invokes local Python commands for deterministic work.

```text
Business question
  -> Ask Data interpretation card and material clarification
  -> promoted metric, model-backed derived metric, or allowlisted ad hoc source selection
  -> structured semantic plan or explicitly unpromoted text-to-SQL contract
  -> Snowflake SQL compilation and validation
  -> SQL validation and max_rows + 1 read-only execution
  -> result validation
  -> answer with semantic grain, result grain, SQL, query details, and optional report
```

Semantic models enter through a parallel builder workflow:

```text
Power BI / Tableau / JSON / YAML / neutral IR / Ossie
  -> source extractor
  -> neutral semantic IR
  -> conservative expression translation
  -> deterministic raw OSI and official validation
  -> audited LLM review patch
  -> deterministic patch application and readiness validation
  -> per-model competency tests and object-level change impact
  -> optional Snowflake metadata/expression verification
  -> final model and clean automatic promotion
```

## Components

| Component | Responsibility |
|---|---|
| `.github/agents/data-analytics.agent.md` | Selects the relevant user workflow. |
| `.github/skills/snowflake-analysis/` | Guides setup, semantic lookup, querying, validation, and response. |
| `.github/skills/osi-semantic-model-builder/` | Converts BI semantic exports into OSI models. |
| `data_agent/semantic/` | Loads, searches, validates, converts, and compiles promoted and derived semantic plans. |
| `data_agent/ad_hoc.py` | Validates unpromoted text-to-SQL contracts against promoted and allowlisted sources. |
| `ossie-main/` | Pinned official Apache Ossie schema, validator, examples, and converter guidance. |
| `data_agent/bi/` | Extracts Power BI, Tableau, and generic metadata to neutral IR. |
| `data_agent/tools/snowflake.py` | Connects with browser SSO or environment-token OAuth and runs bounded read-only operations. |
| `data_agent/security/sql.py` | Parses Snowflake SQL and rejects unsupported operations. |
| `data_agent/tools/result_validation.py` | Checks result shape before interpretation. |
| `data_agent/reporting/` | Creates accessible multi-series SVG charts and interactive self-contained HTML reports. |

The review workspace provides Business and Analyst views over one auto-audited draft. Its three
destinations are Catalog, Metrics, and Advanced. The description-first Catalog groups columns
beneath tables, shows completeness, offers a next-missing queue, and saves related edits from a
persistent Undo/Discard/Save bar. The guided metric builder presents common aggregations first and
progressively reveals optional business context, custom expressions, and dialect. Compiled patches
remain in memory; raw JSON Pointer operations remain an advanced escape hatch.

Refresh compares semantic objects instead of only file hashes. Each change is classified as
`breaking`, `semantic`, or `metadata`. The previously promoted model remains active until the new
draft passes official validation, readiness checks, competency tests, and explicit promotion.

## Deliberate limits

- The semantic compiler supports promoted and request-scoped derived metrics, dimensions,
  parameterized filters, bounded time ranges, selected-projection ordering, and simple join paths.
- Ad hoc text-to-SQL requires explicit output aliases, formula and assumptions, positional filter
  parameters, a `max_rows + 1` limit, and sources from promoted models or `allowed_objects`.
- Power BI and Tableau conversion does not attempt full DAX, M, LOD, table-calculation, parameter,
  filter, or role translation.
- Binary PBIX and packaged TWBX files must be exported or unpacked before conversion.
- Snowflake identifiers are currently limited to unquoted names in generated discovery helpers.
- The agent does not modify Snowflake data.

These boundaries are surfaced as errors or manifest review items instead of being hidden.

## Useful safeguards

Browser SSO or environment-token OAuth, explicit context confirmation, SQL parsing, approved
sources, explicit columns, parameterized predicate values, query timeouts, and row/byte limits
remain part of the local workflow. Optional role, warehouse, database, and schema values are
preferred defaults rather than connection blockers. Derived and ad hoc metrics are labeled
unpromoted and never update shared semantics implicitly.
