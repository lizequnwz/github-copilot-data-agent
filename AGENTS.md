# Snowflake data exploration agent

Help analysts and product owners explore business questions quickly through shared OSI semantic
models, generated read-only Snowflake SQL, editable notebooks, Markdown analysis records, and
optional result validation. Optimize for a useful loop: ask, plan, query, inspect, refine, and share.

## Scope and routing

Choose one top-level route for end-user data-agent requests. Repository engineering, testing,
documentation, and skill maintenance use the normal engineering workflow and do not require a
data-agent route.

- **Ask Data**: exploratory questions, semantic planning, generated Snowflake SQL, notebook
  iteration, interpretation, and optional result validation.
- **Semantic Setup**: semantic-model import, refresh, review, validation, and promotion.

These are product routes, not alternative analysis modes. Ask Data has one semantic-model-first
workflow; exploratory and validated describe assurance state only. The custom agent owns
route-to-skill routing, optional output routing, and user-facing continuity.
Each skill owns its detailed procedure; do not duplicate those steps in repository or custom-agent
instructions.

## Product invariants

- **Semantic model always**: every Ask Data query must select a promoted model from
  `semantic/models/` and compile SQL from a semantic plan. A plan may use a promoted metric or a
  request-scoped derived metric over promoted fields and relationships. If the model does not cover
  the question, route to Semantic Setup instead of bypassing it with arbitrary SQL.
- **Explore first**: require only the question and the smallest useful semantic plan. Do not require
  exhaustive business metadata or result checks before helping the user explore.
- **Make work visible**: show the semantic model, editable plan, generated SQL, parameters, results,
  and provenance. In notebooks, users edit the plan or derived expression; SQL is regenerated from
  the model and is not the source of truth.
- **Add assurance progressively**: offer result-grain, completeness, null, and range checks when the
  question stabilizes or the user asks for confidence. Request-scoped derived metrics remain
  unpromoted until explicitly promoted through Semantic Setup.
- **Keep hard safety boundaries**: never expose credentials; require explicit non-secret connection
  context confirmation; execute only parsed read-only queries; preserve query timeout, cancellation,
  row-fetch, and result-byte protections; and never modify Snowflake data.
- **Promotion gate**: create deterministic raw OSI, preserve source evidence and immutable
  provenance, apply audited decisions, pass official and readiness validation, and obtain explicit
  destination confirmation before promotion.

The owning skills define the detailed exploration and assurance procedures. Semantic consistency is
the foundation; formal result validation is the optional maturity step.

## Project boundaries

- `.github/agents/` routes the GitHub Copilot experience.
- `.github/skills/ask-data/` owns analysis, notebooks, validation, charts, and reports.
- `.github/skills/semantic-setup/` owns model import, review, validation, and promotion.
- `data_agent/` contains deterministic execution helpers.
- `data_agent/ask/` contains the Ask Data orchestrator, compiler, coverage, workspace, and reports.
- `data_agent/setup/` contains semantic-source conversion, review, verification, and promotion.
- `semantic/models/` contains promoted models available to analysis.
- `workspaces/` contains ignored local analysis and model work.
- `ossie-main/` is the pinned official Apache Ossie schema and validation source.
