# Enterprise Snowflake Data Analytics Agent Blueprint

**Document purpose:** A critical implementation blueprint for building a general, enterprise-ready Snowflake-backed analytics agent using GitHub Copilot as the initial technical interface.

**Current POC implementation decision (2026-07-11):** Start with one `data-analytics` custom agent using Copilot's default tools and five core skills: Snowflake environment setup, read-only querying, Ossie semantic building/conversion, result validation, and report generation. The POC uses `snowflake_config.yaml` exclusively for non-secret browser-SSO connection context; `.env` and environment-variable configuration are not supported. Multi-agent roles, the knowledge library, and the full eval framework described later in this blueprint are deferred. The selected Open Semantic Interchange source, <https://github.com/open-semantic-interchange/ossie>, now directs new work to Apache Ossie at <https://github.com/apache/ossie>. The POC vendors the shared `0.2.0.dev0` core schema and implements Power BI, Tableau, generic JSON/YAML, neutral IR, and existing Ossie conversion through one neutral-IR pipeline. Offline conversion fixtures and accessible Python-SVG/HTML report tests are included.

The later multi-agent sections remain as an enterprise roadmap, not the current repository layout.

**Primary design thesis:** Build a Snowflake-connected, semantic-first analytics agent that uses Open Semantic Interchange (OSI) files as governed business context, GitHub Copilot instructions and skills as procedural knowledge, and reviewed custom tools as the execution layer.

**Important caveat:** GitHub Copilot can be the development environment and an excellent MVP chat interface for technical users. It should not automatically be assumed to be the final business-wide runtime. A no-MCP prototype can use Copilot's execute capability to call reviewed Python CLI programs, but a mature enterprise system should eventually use a dedicated internal agent API, controlled tool runtime, and business-facing interface.

---

## 1. Executive Summary

The target system is not a simple natural-language-to-SQL chatbot. It is a governed analytics system where the model reasons over curated semantic definitions, approved institutional knowledge, safe execution tools, and validation workflows.

The intended flow is:

```text
Business question
    -> Resolve business meaning
    -> Search reviewed OSI semantic models
    -> Generate or compile Snowflake SQL
    -> Execute safely
    -> Validate the data
    -> Create charts, tables, or HTML reports
    -> Return findings with provenance, confidence, and caveats
```

The first major semantic capability should be:

```text
Power BI or Tableau semantic asset
    -> Extract semantic metadata
    -> Convert into a neutral internal representation
    -> Translate to OSI YAML
    -> Validate
    -> Human review
    -> Publish as approved semantic context
```

This architecture directly addresses the core failure mode in enterprise analytics agents: syntactically valid SQL can still be semantically wrong if the agent chooses the wrong logical table, misunderstands a metric, uses deprecated business logic, or applies the wrong grain.

---

## 2. Agreed Design Constraints

- The initial version cannot assume the underlying Snowflake warehouse can be redesigned.
- The agent needs direct Snowflake access.
- The POC uses `snowflake_config.yaml` for non-secret browser-SSO connection context; `.env` and environment-variable configuration are not supported.
- Open Semantic Interchange (OSI) is the semantic interchange format.
- Skills are central to repeatable analytical behavior.
- MCP is postponed for the first phase.
- Institutional knowledge must be stored in reviewable files.
- The agent must record unresolved business concepts instead of silently guessing.
- The primary interaction should initially be conversational, most likely through GitHub Copilot for technical users.

---

## 3. Core Architecture

```text
+--------------------------------------------------+
| User interface                                   |
| Copilot Chat / CLI initially                     |
| Web, Teams, Slack, or portal later               |
+-------------------------+------------------------+
                          |
+-------------------------v------------------------+
| Agent control layer                              |
| AGENTS.md                                        |
| Custom agent profiles                            |
| Skills                                           |
| Session state                                    |
+-------------------------+------------------------+
                          |
+-------------------------v------------------------+
| Semantic orchestration                           |
| Intent classification                            |
| OSI search and resolution                      |
| Structured analytical query plan                 |
| Confidence and source-tier assignment            |
+-------------------------+------------------------+
                          |
+-------------------------v------------------------+
| Typed execution tools                            |
| Snowflake discovery/query tools                  |
| Power BI extractor                               |
| Tableau extractor                                |
| OSI validator/compiler                         |
| Plot and report renderer                         |
| Memory proposal tool                             |
+-------------------------+------------------------+
                          |
+-------------------------v------------------------+
| Context and knowledge                            |
| Certified OSI models                           |
| Candidate models                                 |
| Dashboard source mappings                        |
| Business glossary                                |
| Incident and caveat documents                    |
| Pending/approved memory                          |
+-------------------------+------------------------+
                          |
+-------------------------v------------------------+
| Enterprise systems                               |
| Snowflake                                        |
| Power BI                                         |
| Tableau                                          |
| GitHub repositories                              |
+-------------------------+------------------------+
                          |
+-------------------------v------------------------+
| Trust layer                                      |
| Evals and regression tests                       |
| SQL and semantic validation                      |
| Audit and observability                          |
| Security and cost controls                       |
+--------------------------------------------------+
```

Permanent boundaries:

```text
AGENTS.md defines policy.
Skills define procedure.
Tools perform controlled actions.
OSI and reviewed knowledge define business meaning.
```

Do not allow any one layer to replace the others.

---

## 4. Critical Missing Pieces and Recommendations

### 4.1 OSI Is an Interchange Standard, Not Automatically a Query Engine

OSI gives a portable representation of metrics, dimensions, entities, relationships, and semantic metadata. It does not by itself guarantee that the agent can deterministically turn every business question into correct Snowflake SQL.

You need an explicit semantic resolver and compiler:

```text
Natural-language question
    -> Structured semantic query plan
    -> Resolve metric IDs, dimensions, entities, filters, and time grain
    -> Validate legal joins and aggregation grain
    -> Compile to Snowflake SQL
```

Recommended components:

```text
osi_search
osi_resolver
osi_query_planner
osi_to_snowflake_compiler
osi_validator
semantic_result_validator
```

Do not combine these into one large prompt. The LLM can assist with planning and interpretation, but deterministic compilation should be preferred wherever semantic coverage exists.

### 4.2 Dashboard Conversion Will Not Always Be Lossless

Power BI and Tableau contain vendor-specific constructs that may not map cleanly into OSI:

- DAX measures
- Calculation groups
- Power Query transformations
- Tableau level-of-detail calculations
- Table calculations
- Visual-level filters
- Context filters
- Blended data sources
- Custom calendars
- Parameters
- Row-level security rules

Do not translate directly:

```text
Power BI -> OSI
Tableau -> OSI
```

Use an intermediate representation:

```text
Power BI parser ----+
                    +--> Internal Semantic IR --> OSI emitter
Tableau parser -----+
```

The intermediate representation should preserve both normalized meaning and original vendor expressions:

```yaml
measure:
  id: active_customer_count
  normalized_expression: count_distinct(customer_id)
  source_expression:
    language: dax
    value: DISTINCTCOUNT(Customer[CustomerId])
  translation_status: exact
  source_artifact: executive_sales_model
  source_object_id: measure-123
```

Use translation states:

```text
exact
equivalent-with-assumptions
partial
unsupported
requires-human-review
```

### 4.3 Copilot Scripts Are Not Fully Equivalent to Native Custom Tools

For the no-MCP MVP, Copilot can invoke reviewed CLI tools:

```text
Copilot skill
    -> execute tool
    -> python -m data_agent.cli query ...
```

However, enterprise-grade execution requires:

- structured JSON inputs
- structured JSON outputs
- fixed command allowlists
- no arbitrary SQL shell construction
- deterministic exit codes
- timeouts
- audit IDs
- output size limits
- no secrets in stdout or logs

Treat every CLI program as though it were already a remote API:

```bash
python -m data_agent.tools.snowflake_query \
  --input /tmp/request.json \
  --output /tmp/result.json
```

Avoid allowing skills to build arbitrary commands such as:

```bash
python query.py "SELECT ... generated text ..."
```

The SQL should be passed through a typed request file and validated within the tool.

### 4.4 Memory Must Not Directly Rewrite Trusted Instructions

The agent should never automatically modify `AGENTS.md` or certified OSI files based only on a conversation.

Use three stages:

```text
Pending memory
    -> human/domain review
Approved knowledge
    -> semantic review
Certified OSI model
```

The agent may propose a learning, but it must not certify it.

### 4.5 Enterprise Security Cannot Rely Only on SQL Text Blocking

Blocking words such as `DROP` or `DELETE` is not sufficient.

Enforcement must happen at several levels:

1. Snowflake role has no write privileges.
2. SQL AST parser allows only approved statement types.
3. Agent tool applies object and schema policies.
4. Warehouse and session enforce time and cost limits.
5. Results are filtered or masked according to Snowflake policy.
6. Query activity is tagged and logged.

Read-only access must be enforced through a dedicated Snowflake role, not merely by an agent prompt.

---

## 5. System Instruction Design

GitHub Copilot-style instruction surfaces should be separated by purpose.

### 5.1 `.github/copilot-instructions.md`

Repository-wide developer guidance:

- how to build and test the project
- coding conventions
- architectural boundaries
- required commands
- package and folder conventions

### 5.2 `AGENTS.md`

Operational behavior for the data agent:

- source precedence
- safety rules
- analytical workflow
- clarification policy
- SQL policy
- validation policy
- memory policy
- output contract

### 5.3 `.github/agents/*.agent.md`

Selectable custom Copilot agent profiles defining:

- agent name and description
- available tools
- optional model
- specialization
- behavioral prompt

---

## 6. Recommended Root `AGENTS.md`

```markdown
# Mission

You are an enterprise analytics agent for Snowflake-backed data.

Your purpose is to:
1. Interpret business questions.
2. Prefer certified Open Semantic Interchange (OSI) semantic models.
3. Generate safe, reviewable analytical plans.
4. Execute read-only Snowflake queries using approved tools.
5. Validate results before presenting conclusions.
6. Clearly disclose sources, freshness, assumptions, and uncertainty.

# Non-negotiable rules

- Never invent a metric definition.
- Never treat raw table names as proof of business meaning.
- Never execute warehouse write operations.
- Never expose credentials, tokens, or private configuration.
- Never alter certified semantic models without a reviewed pull request.
- Never silently resolve an ambiguous business concept.
- Never claim causation from descriptive data alone.
- Never output restricted row-level data unless explicitly authorized.

# Source precedence

Use sources in this order:

1. Certified OSI semantic model
2. Reviewed domain knowledge
3. Approved dashboard-derived candidate model
4. Snowflake metadata and lineage
5. Raw Snowflake exploration

Lower-tier sources must never override higher-tier sources silently.

# Required analytical workflow

1. Classify the user's intent.
2. Resolve business concepts.
3. Search certified OSI models.
4. Identify metric, dimensions, filters, population, and time range.
5. Produce a structured query plan.
6. Validate grain and join paths.
7. Compile Snowflake SQL.
8. Run static safety checks.
9. Execute with approved Snowflake tool.
10. Validate results.
11. Produce findings and visualizations.
12. Return provenance footer.
13. Propose unresolved learnings to pending memory.

# Clarification policy

Ask a question when ambiguity could materially change the answer, including:
- multiple plausible metric definitions
- unclear population or segment
- unclear date interpretation
- conflicting semantic models
- unsupported dashboard calculation

When proceeding with a default:
- state the default before execution
- include it in the final answer
- do not save it as approved memory

# SQL policy

- Use explicit column lists.
- Use explicit join conditions.
- Confirm table grain before aggregation.
- Detect possible many-to-many joins.
- Default to complete calendar periods.
- Apply result limits for exploration.
- Do not use SELECT *.
- Do not execute unvalidated SQL.
- Use only the configured read-only role.

# Validation policy

Before answering:
- confirm non-empty results
- inspect row count and date coverage
- check duplicate grain keys
- check unexpected nulls
- check aggregation totals
- compare against known ranges when available
- distinguish observed facts from interpretation

# Memory policy

The agent may create pending memory proposals.
It may not automatically:
- edit AGENTS.md
- certify a metric
- overwrite approved knowledge
- promote a dashboard-derived definition

Every memory proposal must include evidence, source, and confidence.

# Output contract

Every analytical response must include:
- direct answer
- methodology summary
- metric and filter definitions
- data freshness
- source tier
- confidence
- caveats
- executed SQL reference or query ID
```

Design principle: keep `AGENTS.md` high-level enough to allow reasoning. Use skills for detailed procedures rather than making `AGENTS.md` enormous.

### 6.1 Nested `AGENTS.md` Files

Recommended:

```text
AGENTS.md
semantic/AGENTS.md
tools/AGENTS.md
evals/AGENTS.md
reports/AGENTS.md
memory/AGENTS.md
```

Examples:

`semantic/AGENTS.md` should specify:

- only use supported OSI fields
- preserve source expressions
- require provenance
- do not mark models certified
- use namespaced extensions
- run schema validation

`tools/AGENTS.md` should specify:

- tools must accept and return JSON
- tools must not print secrets
- tools must include trace IDs
- every network call has a timeout
- all Snowflake operations are read-only

`memory/AGENTS.md` should specify:

- pending records are append-only
- every proposal must cite evidence
- approved memory requires reviewer identity
- review decisions stay recorded on the pending proposal or in version history

---

## 7. Custom Agent Profiles

Do not create one all-powerful custom agent. Use a small number of specialized agents with different permissions.

### 7.1 `data-analyst.agent.md`

Purpose:

- answer data questions
- query certified OSI models
- execute read-only SQL
- generate reports

Recommended tools:

```yaml
tools:
  - read
  - search
  - execute
```

Do not grant `edit` initially. This prevents ordinary analytics conversations from modifying semantic context.

### 7.2 `osi-builder.agent.md`

Purpose:

- extract Power BI/Tableau semantic metadata
- create candidate OSI files
- generate source mapping records
- identify unsupported expressions

Recommended tools:

```yaml
tools:
  - read
  - search
  - execute
  - edit
```

It may edit only:

```text
semantic/candidates/
semantic/mappings/
memory/pending/
```

### 7.3 `semantic-reviewer.agent.md`

Purpose:

- review candidate OSI models
- compare model changes
- identify ambiguous definitions
- generate validation tests
- prepare a PR review report

It should not directly certify content without a human approval step.

### 7.4 `eval-engineer.agent.md`

Purpose:

- produce golden questions
- add semantic compilation tests
- create security and regression cases
- analyze failures

### 7.5 `report-engineer.agent.md`

Purpose:

- build accessible charts and HTML reports
- enforce report templates
- validate rendering and data disclosure rules

---

## 8. Skills Architecture

Skills represent procedural knowledge: how to perform an analytical task.

Every skill should contain:

```text
Purpose
Trigger conditions
Do-not-use conditions
Required inputs
Permitted tools
Step-by-step procedure
Validation checks
Output schema
Failure conditions
Examples
Tests
```

A skill should not merely contain general advice.

### 8.1 Mandatory MVP Skills

#### `semantic-first-analysis`

The primary router.

Responsibilities:

- determine whether OSI coverage exists
- choose certified versus candidate models
- route to raw exploration only when necessary
- assign answer confidence tier

#### `osi-model-ingestion`

Responsibilities:

- accept internal semantic IR
- generate OSI YAML
- preserve source metadata
- mark confidence and translation status
- validate schema
- create review checklist

#### `powerbi-semantic-extraction`

Responsibilities:

- inspect PBIP/TMDL when available
- use XMLA metadata when available
- extract tables, columns, relationships, measures, expressions, and roles
- preserve DAX
- classify unsupported constructs

#### `tableau-semantic-extraction`

Responsibilities:

- query Tableau Metadata API when available
- identify workbooks, data sources, fields, and lineage
- preserve calculated fields
- identify workbook-specific filters and parameters
- mark incomplete extraction

#### `snowflake-sql`

Responsibilities:

- write Snowflake-compatible SQL
- confirm grain
- avoid fanout
- use Snowflake date and window functions correctly
- produce readable CTE-based queries
- apply performance and safety rules

#### `result-validation`

Responsibilities:

- analyze row counts
- detect duplicate grain
- validate time ranges
- inspect nulls and outliers
- detect suspicious zero-row results
- compare alternate calculations where appropriate

#### `visualization-selection`

Responsibilities:

- select chart type based on analytical intent
- specify chart title, axes, and labels
- prevent misleading scales
- display definitions and date range
- generate chart metadata

#### `html-analytics-report`

Responsibilities:

- create executive summary
- include methodology
- embed charts and tables
- include SQL and provenance appendix
- enforce accessibility and responsive design
- avoid unsafe arbitrary JavaScript

#### `business-concept-learning`

Responsibilities:

- detect unresolved terminology
- gather candidate definitions and evidence
- create pending memory proposal
- identify likely domain owner
- never promote automatically

#### `adversarial-review`

Responsibilities:

- challenge source choice
- challenge filters
- challenge joins
- challenge interpretation
- flag causal overclaims
- return pass/fail plus required corrections

### 8.2 Skills to Add Later

- cohort analysis
- retention analysis
- funnel analysis
- experiment readout
- forecasting
- anomaly investigation
- marketing attribution
- recurring business review
- dashboard reconciliation
- Snowflake query optimization
- dbt lineage analysis

Avoid building dozens of overlapping skills immediately. Overlapping skills and overlapping tools can confuse the agent and make behavior less predictable.

---

## 9. Custom Tools Without MCP

### 9.1 Recommended Implementation Pattern

Implement a Python package with a stable CLI:

```text
data_agent/
├── tools/
│   ├── snowflake/
│   ├── semantic/
│   ├── powerbi/
│   ├── tableau/
│   ├── reporting/
│   └── memory/
└── cli.py
```

Each command accepts JSON and returns JSON.

Example request:

```json
{
  "request_id": "req_123",
  "user_id": "charlie",
  "role": "DATA_AGENT_READONLY",
  "sql": "SELECT ...",
  "max_rows": 5000,
  "timeout_seconds": 60,
  "purpose": "quarterly advisor engagement analysis",
  "semantic_model_version": "advisor-engagement@4f38a2"
}
```

Example response:

```json
{
  "request_id": "req_123",
  "status": "success",
  "query_id": "01b...",
  "columns": [],
  "rows": [],
  "row_count": 125,
  "truncated": false,
  "execution_seconds": 2.7,
  "data_freshness": "2026-07-08",
  "warnings": []
}
```

### 9.2 Snowflake Tools

#### `snowflake_connection_check`

Returns:

- authenticated user
- active role
- warehouse
- database
- schema
- connectivity status

#### `snowflake_search_objects`

Searches:

- databases
- schemas
- tables
- views
- columns
- comments
- tags

#### `snowflake_describe_object`

Returns:

- columns and types
- comments
- clustering information
- approximate row count
- owner
- last altered date

#### `snowflake_sample_values`

Returns bounded distinct/sample values for semantic value resolution.

It must block sampling of sensitive columns unless authorized.

#### `snowflake_profile_table`

Returns:

- row count
- null rates
- distinct counts
- min/max dates
- candidate keys
- freshness indicators

#### `snowflake_validate_sql`

Uses a parser or AST to enforce:

```text
SELECT / WITH / SHOW / DESCRIBE / EXPLAIN only
single statement only
no external stages
no file operations
no unsafe functions
no blocked schemas
no unsupported table functions
```

#### `snowflake_execute_readonly`

Enforces:

- fixed role
- query tag
- statement timeout
- row cap
- result byte cap
- no secondary roles unless explicitly approved
- query ID capture

#### `snowflake_cancel_query`

Required for long-running or expensive queries.

### 9.3 Semantic Tools

#### `osi_validate`

- validate YAML against pinned OSI schema
- report exact field errors
- enforce organization extension conventions

#### `osi_search`

Searches certified and candidate semantic models by:

- business name
- synonyms
- description
- source table
- dashboard
- owner
- dimension values

#### `osi_resolve_query`

Input:

```json
{
  "question": "Active advisors by segment last quarter"
}
```

Output:

```json
{
  "metric": "active_advisor_count",
  "dimensions": ["firm_segment"],
  "filters": [],
  "time_range": {
    "type": "previous_complete_quarter"
  },
  "population": "external_advisors",
  "confidence": 0.94
}
```

#### `osi_compile_snowflake`

This should be deterministic wherever possible.

#### `semantic_diff`

Compares:

- metric expressions
- join paths
- grain
- dimensions
- source mappings
- owners
- freshness assumptions

### 9.4 BI Extraction Tools

#### `powerbi_extract_model`

Supported input modes:

```text
PBIP directory
TMDL directory
TMDL script
XMLA connection
exported model metadata
```

#### `tableau_extract_model`

Supported input modes:

```text
Tableau Metadata API
downloaded workbook/package
published data source metadata
```

#### `semantic_ir_to_osi`

The common conversion layer.

### 9.5 Reporting Tools

#### `render_chart`

Prefer a declarative chart specification rather than agent-generated arbitrary plotting code.

#### `render_html_report`

Use a controlled template system.

Do not let the model freely generate executable browser scripts.

#### `export_result`

Controlled formats:

```text
CSV
Parquet
HTML
PNG/SVG
PDF later
```

Apply row and file-size limits.

### 9.6 Memory Tools

#### `memory_propose`

Creates:

```text
memory/pending/<timestamp>-<concept>.yaml
```

#### `memory_approve`

Human-only operation.

#### `memory_reject`

Records reason so the same invalid learning is not repeatedly proposed.

#### `memory_search`

Returns only knowledge the requesting user is authorized to access.

---

## 10. Core Analytical Workflow

### Stage 1: Intent Resolution

Identify:

- requested metric
- population
- dimensions
- filters
- time range
- required precision
- intended audience
- requested output

### Stage 2: Semantic Discovery

Search in this order:

```text
Certified OSI
Approved glossary
Dashboard-derived candidate OSI
Snowflake metadata
Raw warehouse discovery
```

### Stage 3: Ambiguity Decision

Calculate an ambiguity/risk score.

Require clarification when:

- two certified metrics match
- population materially changes the result
- date interpretation is unclear
- dashboard and OSI definitions conflict
- sensitive fields may be involved

### Stage 4: Structured Plan

The model must produce a query plan before SQL:

```json
{
  "metric_ids": ["active_advisor_count"],
  "dimensions": ["firm_segment"],
  "filters": [
    {
      "field": "advisor_type",
      "operator": "=",
      "value": "external"
    }
  ],
  "time_window": "previous_complete_quarter",
  "grain": ["firm_segment"],
  "source_tier": "certified_osi"
}
```

### Stage 5: Semantic Validation

Verify:

- metric supports dimensions
- join path exists
- filters are permitted
- aggregation is valid
- requested grain is supported

### Stage 6: Compile SQL

Do not ask the LLM to write raw SQL when a deterministic compilation path exists.

### Stage 7: Static Safety Review

- parse AST
- confirm read-only
- inspect referenced objects
- estimate risk
- enforce limits

### Stage 8: Execute

Apply:

- query tag
- fixed role
- timeout
- warehouse
- row limit
- audit context

### Stage 9: Result Validation

- empty results
- duplicate keys
- nulls
- unexpected ranges
- incomplete dates
- total reconciliation
- unit consistency

### Stage 10: Synthesis

Separate:

```text
Facts
Interpretation
Hypotheses
Recommended follow-up
```

### Stage 11: Provenance Footer

Every result should include:

```text
Source tier:
Semantic model:
Semantic version:
Snowflake query ID:
Data freshness:
Role used:
Confidence:
Caveats:
```

### Stage 12: Memory Proposal

Only after the answer:

```text
"I encountered an unresolved definition for active advisor.
A pending memory proposal was created for review."
```

---

## 11. Dashboard-to-OSI Workflow

```text
1. Authenticate to BI source
2. Extract semantic metadata
3. Store immutable raw snapshot
4. Parse source model
5. Convert to internal semantic IR
6. Resolve Snowflake physical objects
7. Translate supported calculations
8. Preserve unsupported source expressions
9. Generate candidate OSI
10. Validate OSI schema
11. Run semantic linting
12. Compile representative queries
13. Execute sample validations
14. Compare against dashboard outputs
15. Generate semantic diff and review report
16. Open pull request
17. Domain owner reviews
18. Promote candidate to certified
19. Update semantic index
20. Add regression evals
```

Critical promotion rule: a dashboard is not automatically a trusted source of truth.

Dashboard-derived models should begin as:

```yaml
lifecycle:
  status: candidate
  source_type: powerbi
  source_artifact: advisor_executive_dashboard
  extraction_timestamp: 2026-07-09T12:00:00Z
  confidence: medium
  reviewer: null
```

Promotion states:

```text
draft
candidate
reviewed
certified
deprecated
rejected
```

---

## 12. Institutional Knowledge and Memory

### 12.1 Do Not Overload OSI

OSI should contain structured semantic information:

- metrics
- dimensions
- entities
- joins
- expressions
- relationships
- synonyms
- ownership
- source lineage

Long-form narrative belongs in adjacent Markdown:

```text
knowledge/
├── glossary/
├── domains/
├── incidents/
├── dashboards/
├── business-rules/
└── decision-logs/
```

Link them using stable IDs:

```yaml
documentation_refs:
  - knowledge://glossary/active-advisor
  - knowledge://incidents/tracking-change-2026-q1
```

### 12.2 Memory Scopes

Use:

```text
global
domain
team
personal
session
```

A personal preference must never change a global metric.

Example:

```yaml
scope: personal
subject: user-123
rule: default growth comparisons to week-over-week
```

Versus:

```yaml
scope: global
rule: exclude employee test accounts from active advisor metrics
reviewed_by: data-governance-team
```

---

## 13. Snowflake Enterprise Security

### 13.1 Authentication

The POC uses `snowflake_config.yaml` with browser SSO and never stores a username/password credential pair. Password-based `.env` configuration is not supported.

For enterprise deployment, prefer:

- key-pair authentication for a service identity
- OAuth/federated identity
- user pass-through when feasible
- rotated secrets in an enterprise secrets manager

### 13.2 Role Design

Create separate roles:

```text
DATA_AGENT_METADATA
DATA_AGENT_ANALYST_READONLY
DATA_AGENT_SENSITIVE_READONLY
DATA_AGENT_SEMANTIC_PUBLISHER
```

The normal agent must never use `SYSADMIN`, `SECURITYADMIN`, or a general engineering role.

### 13.3 Object Access

Grant only:

```text
USAGE on approved warehouses
USAGE on approved databases/schemas
SELECT on approved views/tables
MONITOR only where necessary
```

### 13.4 Query Controls

Apply:

- `QUERY_TAG`
- `STATEMENT_TIMEOUT_IN_SECONDS`
- statement queued timeout
- resource monitors
- dedicated warehouse
- auto-suspend
- maximum result rows and bytes
- concurrency limits

### 13.5 Sensitive Data

Integrate:

- masking policies
- row access policies
- object tags
- PII classification
- export restrictions
- aggregate-only policies where needed

### 13.6 Credentials in Copilot Environments

Copilot cloud agents may receive configured secrets and variables in their execution environment, but network access, Snowflake allowlisting, secret scope, and firewall behavior must be reviewed carefully.

For enterprise Snowflake access, a local Copilot/VS Code environment behind the organization's VPN may initially be easier and safer than cloud-based access.

---

## 14. Validation and Evaluation Framework

Evaluation must be a first-class subsystem, not a later add-on.

### 14.1 Evaluation Categories

#### Semantic Resolution

Test whether the agent selects:

- correct metric
- correct population
- correct date field
- correct dimensions
- correct canonical filters

#### SQL Correctness

Test:

- valid Snowflake SQL
- correct joins
- correct grouping
- no fanout
- no missing filters
- correct timezone
- correct complete-period behavior

#### Result Correctness

Compare:

- result sets
- aggregates
- row counts
- expected ranges
- known dashboard outputs

#### OSI Conversion Quality

Test:

- source objects extracted
- expression translation
- lineage preservation
- unsupported constructs identified
- source-to-OSI round-trip fidelity where possible

#### Security

Red-team:

- write SQL requests
- prompt injection in table comments
- malicious dashboard descriptions
- attempts to reveal credentials
- attempts to query restricted schemas
- SQL hidden in user-provided text
- data-exfiltration requests

#### Reporting

Test:

- chart accuracy
- accessible labels
- no misleading axes
- correct units
- no restricted data leakage
- responsive HTML rendering

### 14.2 Golden Eval Record

```yaml
id: active-advisors-last-quarter
question: >
  How many active advisors did we have last quarter,
  broken down by firm segment?

expected_semantics:
  metric: active_advisor_count
  dimension: firm_segment
  population: external_advisors
  time_range: previous_complete_quarter

expected_source_tier: certified_osi

forbidden:
  tables:
    - raw_clickstream_events
  patterns:
    - trailing_90_days

assertions:
  - semantic_model_used
  - no_many_to_many_join
  - complete_quarter_used
  - employee_accounts_excluded
  - result_matches_golden_within_tolerance
```

### 14.3 Required Metrics

Track:

```text
semantic coverage rate
certified semantic usage rate
raw-table fallback rate
clarification rate
wrong-source correction rate
SQL execution failure rate
result validation failure rate
human acceptance rate
average Snowflake credits
latency
token/model cost
memory proposal acceptance rate
dashboard conversion review rejection rate
```

---

## 15. Observability

Every run should record:

```text
user ID
session ID
agent version
AGENTS.md commit
skill versions
OSI model versions
model identifier
question
structured query plan
tool calls
generated SQL
Snowflake query ID
role and warehouse
execution time
rows and bytes returned
validation results
answer confidence
user feedback
memory proposal
```

Do not log:

- passwords
- private keys
- tokens
- raw sensitive rows unless explicitly approved
- entire unredacted prompts containing protected data

Store audit records in an append-only system.

---

## 16. CI/CD Requirements

Every pull request should run:

```text
Python lint and type checks
Unit tests
OSI schema validation
Organization semantic lint
Semantic diff
OSI-to-Snowflake compilation tests
Golden query tests
SQL safety tests
Dashboard conversion tests
Skill validation
AGENTS.md policy checks
Security scans
Report rendering tests
Regression evals
```

Block merging when:

- a certified metric changes without owner approval
- source fields change without semantic diff
- a skill references a missing tool
- an OSI model no longer compiles
- golden result tests regress
- unresolved expressions are silently marked supported
- sensitive object access expands unexpectedly

---

## 17. Recommended Repository Blueprint

```text
enterprise-data-agent/
├── AGENTS.md
├── .github/
│   ├── copilot-instructions.md
│   ├── agents/
│   │   ├── data-analyst.agent.md
│   │   ├── osi-builder.agent.md
│   │   ├── semantic-reviewer.agent.md
│   │   ├── eval-engineer.agent.md
│   │   └── report-engineer.agent.md
│   ├── skills/
│   │   ├── semantic-first-analysis/
│   │   ├── osi-model-ingestion/
│   │   ├── powerbi-semantic-extraction/
│   │   ├── tableau-semantic-extraction/
│   │   ├── snowflake-sql/
│   │   ├── result-validation/
│   │   ├── visualization-selection/
│   │   ├── html-analytics-report/
│   │   ├── business-concept-learning/
│   │   └── adversarial-review/
│   ├── instructions/
│   │   ├── python.instructions.md
│   │   ├── semantic.instructions.md
│   │   ├── sql.instructions.md
│   │   └── tests.instructions.md
│   └── hooks/
├── data_agent/
│   ├── orchestration/
│   │   ├── intent.py
│   │   ├── planner.py
│   │   ├── state.py
│   │   └── confidence.py
│   ├── tools/
│   │   ├── snowflake/
│   │   ├── semantic/
│   │   ├── powerbi/
│   │   ├── tableau/
│   │   ├── reports/
│   │   └── memory/
│   ├── compiler/
│   │   ├── semantic_plan.py
│   │   └── snowflake_sql.py
│   ├── validation/
│   ├── reporting/
│   ├── security/
│   ├── telemetry/
│   └── cli.py
├── semantic/
│   ├── AGENTS.md
│   ├── certified/
│   ├── candidates/
│   ├── deprecated/
│   ├── mappings/
│   ├── source-snapshots/
│   └── schemas/
├── knowledge/
│   ├── glossary/
│   ├── domains/
│   ├── dashboards/
│   ├── incidents/
│   └── decision-logs/
├── memory/
│   ├── AGENTS.md
│   ├── pending/
│   ├── approved/
├── evals/
│   ├── AGENTS.md
│   ├── semantic/
│   ├── sql/
│   ├── dashboard-conversion/
│   ├── security/
│   └── reporting/
├── reports/
│   ├── templates/
│   ├── assets/
│   └── examples/
├── tests/
└── docs/
```

---

## 18. Capability Roadmap

### 18.1 MVP Capabilities

The first usable version should:

- chat with a technical user
- connect to Snowflake through environment configuration
- inspect schemas and tables
- execute bounded read-only SQL
- ingest one Power BI semantic model
- ingest one Tableau semantic model
- generate candidate OSI YAML
- validate OSI files
- search certified semantics
- generate a structured query plan
- compile basic OSI queries to Snowflake
- create tables and common charts
- produce an HTML report
- disclose provenance and confidence
- propose unresolved business concepts to pending memory
- run a basic eval suite

### 18.2 Enterprise Capabilities

Later:

- identity-aware access
- row and column policy enforcement
- multi-domain semantic search
- large semantic registry
- scheduled and recurring reports
- asynchronous long-running analysis
- collaborative sessions
- report sharing
- anomaly detection
- dashboard reconciliation
- data-quality incident awareness
- semantic drift detection
- automatic PR creation for context updates
- model and skill version experimentation
- formal service-level objectives

### 18.3 Explicit Non-Capabilities for Initial Releases

The agent should not:

- modify Snowflake data
- create or alter production tables
- autonomously certify metrics
- make business decisions
- claim causal conclusions without proper design
- export unrestricted sensitive data
- execute arbitrary Python supplied by users
- automatically rewrite `AGENTS.md`
- silently learn from every chat
- replace data owners or governance reviewers

---

## 19. Recommended Delivery Phases

### Phase 0: Architectural Spike

Deliver:

- one custom Copilot data analyst
- root `AGENTS.md`
- two skills
- Snowflake connection check
- Snowflake read-only query CLI
- query logging
- 10 safety tests

Exit criterion:

```text
Copilot can safely execute a bounded Snowflake query through a typed script
without exposing credentials or permitting writes.
```

### Phase 1: Semantic Foundation

Deliver:

- pinned Open Semantic Interchange (OSI) version
- internal semantic IR
- OSI validator
- semantic search
- simple OSI-to-Snowflake compiler
- certification lifecycle

Exit criterion:

```text
A manually created certified OSI model can reliably answer
20 golden business questions.
```

### Phase 2: Power BI Conversion

Deliver:

- PBIP/TMDL parser
- DAX preservation
- candidate OSI generation
- dashboard comparison tests
- human review workflow

Exit criterion:

```text
At least one production dashboard converts into a candidate model
with documented translation fidelity.
```

### Phase 3: Tableau Conversion

Deliver the equivalent Tableau pipeline.

### Phase 4: Analytical Outputs

Deliver:

- charts
- HTML reports
- result validation
- provenance footer
- memory proposal workflow

### Phase 5: Enterprise Hardening

Deliver:

- enterprise authentication
- RBAC and sensitive-data controls
- observability
- cost controls
- red-team tests
- service deployment
- business-user UI

---

## 20. Strongest First Demonstration

The best proof-of-architecture demo is:

```text
A user chats with the Copilot data analyst.
The agent imports one Power BI semantic model.
The agent converts it into a reviewed candidate OSI model.
The model is promoted through a pull request.
The user asks a business question.
The agent returns Snowflake-backed results, a validated chart, and an HTML report.
The answer shows the exact semantic model, freshness, assumptions, confidence,
and Snowflake query ID used.
```

This demo proves the critical loop: semantic ingestion, review, Snowflake execution, validation, reporting, and provenance.

---

## 21. Further Recommendations

1. Build the semantic compiler, not merely semantic YAML storage.
2. Use an intermediate representation for Power BI and Tableau conversion.
3. Separate candidate semantics from certified semantics.
4. Enforce read-only access in Snowflake RBAC, not only in prompts or code.
5. Use typed CLI tools for the no-MCP phase.
6. Keep mutable memory outside `AGENTS.md`.
7. Make evaluation and observability part of the first release.
8. Treat GitHub Copilot as the technical MVP interface, not automatically the final enterprise user interface.
9. Keep the tool surface small and typed at first.
10. Make every answer disclose source tier, freshness, confidence, and caveats.

---

## 22. Source and Citation Notes

This document preserves the plan and source trail from the referenced conversation. The prior response contained non-portable citation markers from the ChatGPT interface; those markers do not resolve outside that environment. The practical reference list below captures the cited public materials and should be refreshed before formal publication or vendor/security review.

### Primary References from the Conversation

1. OpenAI, "Inside our in-house data agent": <https://openai.com/index/inside-our-in-house-data-agent/>
2. Kaelio, "Open-source Anthropic internal data analytics engine": <https://www.kaelio.com/blog/open-source-anthropic-internal-data-analytics-engine>
3. Anthropic / Claude, "How Anthropic enables self-service data analytics with Claude": <https://claude.com/blog/how-anthropic-enables-self-service-data-analytics-with-claude>
4. Snowflake, "Open Semantic Interchange specs finalized": <https://www.snowflake.com/en/blog/open-semantic-interchanges-specs-finalized/>
5. Original Open Semantic Interchange GitHub repository: <https://github.com/open-semantic-interchange/ossie>
6. Current Apache Ossie GitHub repository: <https://github.com/apache/ossie>

### Documentation Areas to Verify During Implementation

- GitHub Copilot custom instructions, custom agents, skills, and agent execution environment.
- Snowflake Python connector, authentication options, session parameters, RBAC, masking policies, row access policies, and query controls.
- Open Semantic Interchange (OSI) / Open Semantic Interchange schema, examples, validation tooling, and converter behavior.
- Microsoft Power BI PBIP, TMDL, Tabular Object Model, and XMLA endpoint access.
- Tableau Metadata API, workbook metadata, data source metadata, calculated fields, and lineage APIs.
