# POC implementation

## Design

The POC uses one GitHub Copilot custom agent, five skills, and a reviewed local Python package:

```text
User -> data-analytics agent -> task skill -> data_agent command -> artifact or bounded query result
```

The custom agent is `.github/agents/data-analytics.agent.md`. Its omitted `tools` field gives it Copilot's default tools. The commands under `data_agent/` are local CLI programs invoked through those tools; they are not native Copilot tools or an MCP server.

## Ossie conversion boundary

Apache Ossie was formerly called Open Semantic Interchange (OSI). The selected `open-semantic-interchange/ossie` source now points new work to `apache/ossie`; both identify the `0.2.0.dev0` core schema used by this POC as a mutable draft.

Source adapters never write Ossie directly. Power BI, Tableau, generic metadata, and future adapters first produce neutral semantic IR. The emitter then creates core datasets, fields, many-to-one relationships, metrics, and vendor extensions. The complete `semantic-convert` command writes a schema-valid candidate and a conversion manifest under `semantic/candidates/`.

Vendor semantics are not assumed lossless. Original DAX/Tableau expressions and IDs stay in `ENTERPRISE_DATA_AGENT` custom extensions; unsupported constructs appear in the manifest. Only conservative simple aggregate translations enter core metric expressions automatically.

The semantic tree is intentionally small:

- `semantic/schemas/`: vendored validation schema.
- `semantic/certified/`: reviewed models used by default.
- `semantic/candidates/`: generated YAML/manifest pairs.

## Reporting boundary

`render-chart` creates SVG directly in Python from a declarative bar/line specification. `render-report` creates one responsive HTML file with semantic headings, keyboard focus, chart text alternatives, a data table, dark mode, print CSS, provenance, and no remote assets or executable scripts.

## Snowflake boundary

`snowflake_config.yaml` is the only Snowflake configuration method. Live actions require browser SSO and user confirmation. SQL is parsed, bounded, and executed with query time, row, and byte limits. Snowflake is optional for conversion, validation, and report rendering.

## Memory boundary

Memory stores short institutional notes only:

- `memory/approved/`: reviewed notes the agent may use.
- `memory/pending/`: proposed notes awaiting human review.

Metric definitions and conversion metadata belong in `semantic/`, not memory.

## Deferred

- Live Power BI XMLA and Tableau Metadata API adapters.
- Full DAX, M, LOD, table-calculation, parameter, filter, and role translation.
- Autonomous certification.
- Multiple specialist agents, MCP/service runtime, and business-user application.
- Full semantic resolver, golden business-query suite, and enterprise observability.

See [How `data_agent` works](DATA_AGENT.md) and [Semantic conversion](SEMANTIC_CONVERSION.md).
