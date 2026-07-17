# Design

## Product boundary

GitHub Copilot is the conversational interface. The repository is not a service or MCP server.
The agent follows a skill and invokes local Python commands for deterministic work.

```text
Business question
  -> promoted semantic model
  -> lightweight semantic plan
  -> compiler-generated parameterized SQL
  -> read-only Snowflake execution
  -> table, observations, and iterative refinement
  -> local plan-driven Markdown/notebook workspace
  -> optional result checks
  -> exploratory or validated report
```

Exploration and validation use the same semantic source path. Every query compiles from a promoted
model; users iterate by changing dimensions, filters, ordering, time range, or a request-scoped
derived metric. Formal result checks are progressive assurance options rather than entry
requirements. When a promoted model lacks coverage, analysis stops and routes to Semantic Setup.

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
| `ossie-main/` | Pinned official Apache Ossie schema, validator, examples, and converter guidance. |
| `data_agent/bi/` | Extracts Power BI, Tableau, and generic metadata to neutral IR. |
| `data_agent/tools/snowflake.py` | Connects with browser SSO or environment-token OAuth and runs bounded read-only operations. |
| `data_agent/security/sql.py` | Parses Snowflake SQL and rejects unsupported operations. |
| `data_agent/tools/result_validation.py` | Checks result shape before interpretation. |
| `data_agent/reporting/` | Creates accessible multi-series SVG charts and interactive self-contained HTML reports. |
| `data_agent/reporting/workspace.py` | Creates editable Markdown and Jupyter analysis workspaces. |

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
- Ask Data does not execute arbitrary text-to-SQL. Missing source, field, or relationship coverage
  is a Semantic Setup task.
- Power BI and Tableau conversion does not attempt full DAX, M, LOD, table-calculation, parameter,
  filter, or role translation.
- Binary PBIX and packaged TWBX files must be exported or unpacked before conversion.
- Snowflake identifiers are currently limited to unquoted names in generated discovery helpers.
- The agent does not modify Snowflake data.

These boundaries are surfaced as errors or manifest review items instead of being hidden.

## Useful safeguards

Browser SSO or environment-token OAuth, explicit context confirmation, read-only SQL parsing,
model-bound sources, explicit projections, parameterized predicate values, query timeouts,
cancellation, and row/byte protections remain part of the local workflow. Result-grain and content
checks are opt-in assurance controls. Optional role, warehouse, database, and schema values are
preferred defaults rather than connection blockers. Request-scoped derived metrics are labeled
unpromoted and never update shared semantics implicitly.
