# Snowflake data agent

Help analysts and product owners answer scoped business questions with shared OSI semantic models
and read-only Snowflake queries. Keep the workflow direct, inspectable, and easy to run locally.

## Scope and routing

Classify end-user data-agent requests into one explicit mode. Repository engineering, testing,
documentation, and skill maintenance use the normal engineering workflow and do not require a
data-agent mode.

- **Ask Data**: business questions, semantic planning, Snowflake execution, result validation, and
  interpretation.
- **Semantic Setup**: semantic-model import, refresh, review, validation, and promotion.

The custom agent owns mode-to-skill routing, optional output routing, and user-facing continuity.
Each skill owns its detailed procedure; do not duplicate those steps in repository or custom-agent
instructions.

## Repository-wide gates

- **Semantic gate**: use a promoted model from `semantic/models/` as the source of business
  definitions. An unsupported model or compiler operation leads to a narrower question or model
  enhancement, not ad hoc analytical SQL.
- **Connection gate**: display and confirm the non-secret `snowflake_config.yaml` context before
  the first connection and whenever it changes. Connect through browser SSO with the configured
  read-only role.
- **Validation gate**: validate explicit, parameterized, bounded SQL and the returned rows before
  interpretation or reporting.
- **Promotion gate**: create deterministic raw OSI, preserve source evidence and immutable
  provenance, apply audited decisions, pass official and readiness validation, and obtain explicit
  destination confirmation before promotion.

The owning skills define the checkable criteria for these gates. Keep detailed steps there rather
than repeating them in repository or custom-agent instructions.

## Project boundaries

- `.github/agents/` routes the GitHub Copilot experience.
- `.github/skills/` contains the authoritative Ask Data, Semantic Setup, and reporting procedures.
- `data_agent/` contains deterministic execution helpers.
- `semantic/models/` contains promoted models available to analysis.
- `semantic/generated/` contains repeatable conversion and review artifacts.
- `ossie-main/` is the pinned official Apache Ossie schema and validation source.
