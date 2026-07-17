# Architecture

## Product boundary

GitHub Copilot is the conversational interface. Local Python code provides deterministic model
coverage, semantic compilation, Snowflake execution, validation, workspace generation, reporting,
and Semantic Setup.

The architecture follows the two product routes:

```text
data_agent/ask/       Ask Data
data_agent/setup/     Semantic Setup
```

Shared runtime modules stay shallow:

```text
models.py             Promoted model loading and search
ossie.py              Pinned schema and official validation
snowflake.py          Connection, execution, and metadata operations
sql_safety.py         Parsed read-only SQL enforcement
config.py             Non-secret connection configuration
io.py                 Typed JSON request/response helpers
```

## Ask Data

`ask/service.py` is the public orchestrator. It calls coverage diagnostics, semantic compilation,
optional Snowflake execution, optional result checks, default workspace generation, and optional
HTML reporting.

The compiler supports promoted definitions plus request-scoped derived logic while ensuring every
physical source and relationship comes from the selected promoted model.

## Semantic Setup

`setup/` owns source adapters, conversion, refresh diff, review workspace, verification, competency
tests, and promotion. Source adapters expose separate Power BI, Tableau, and generic interfaces over
a shared private extraction implementation.

Generated model work is isolated under `workspaces/models/`; promoted models and competency tests
remain under `semantic/`.

## Public and advanced commands

The public CLI exposes `ask`, `doctor`, and `model`. Legacy deterministic stages remain under the
hidden `advanced` namespace so tests and automation can operate on individual stages without
turning them into user-facing product choices.

## Hard runtime protections

Credentials are never emitted. Live work requires explicit confirmation of the displayed non-secret
context. Only parsed read-only SQL executes. Generated queries remain model-bound and preserve
timeouts, cancellation, row-fetch, and result-byte limits.

These protections remain stable while result validation and shared-definition promotion are
progressive assurance choices.
