# Design

## Product boundary

GitHub Copilot is the conversational interface. The repository is not a service or MCP server.
The agent follows a skill and invokes local Python commands for deterministic work.

```text
Business question
  -> semantic model search and clarification
  -> structured metric/dimension/filter plan
  -> Snowflake SQL compilation or preparation
  -> SQL validation and bounded read-only execution
  -> result validation
  -> answer, with an optional report
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
  -> optional Snowflake metadata/expression verification
  -> final model and clean automatic promotion
```

## Components

| Component | Responsibility |
|---|---|
| `.github/agents/data-analytics.agent.md` | Selects the relevant user workflow. |
| `.github/skills/snowflake-analysis/` | Guides setup, semantic lookup, querying, validation, and response. |
| `.github/skills/osi-semantic-model-builder/` | Converts BI semantic exports into OSI models. |
| `data_agent/semantic/` | Loads, searches, validates, converts, and compiles semantic models. |
| `ossie-main/` | Pinned official Apache Ossie schema, validator, examples, and converter guidance. |
| `data_agent/bi/` | Extracts Power BI, Tableau, and generic metadata to neutral IR. |
| `data_agent/tools/snowflake.py` | Connects with browser SSO and runs bounded read-only operations. |
| `data_agent/security/sql.py` | Parses Snowflake SQL and rejects unsupported operations. |
| `data_agent/tools/result_validation.py` | Checks result shape before interpretation. |
| `data_agent/reporting/` | Creates optional SVG charts and HTML reports. |

## Deliberate limits

- The semantic compiler supports direct metrics, dimensions, filters, and simple join paths.
- Power BI and Tableau conversion does not attempt full DAX, M, LOD, table-calculation, parameter,
  filter, or role translation.
- Binary PBIX and packaged TWBX files must be exported or unpacked before conversion.
- Snowflake identifiers are currently limited to unquoted names in generated discovery helpers.
- The agent does not modify Snowflake data.

These boundaries are surfaced as errors or manifest review items instead of being hidden.

## Useful safeguards

Browser SSO, a configured read-only role, SQL parsing, explicit columns, parameterized values,
query timeouts, and row/byte limits remain part of the local workflow. They keep example and
development use predictable without requiring a separate runtime platform.
