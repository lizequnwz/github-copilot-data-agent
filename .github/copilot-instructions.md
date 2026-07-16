# Repository instructions

Follow `AGENTS.md` as the authoritative project contract. For end-to-end user work, route through
`.github/agents/data-analytics.agent.md`; do not restate its skill procedures here.

## Local commands

- Install: `uv sync --extra dev --extra snowflake`
- Offline walkthrough: `uv run python scripts/demo_analysis.py`
- CLI tools: `uv run python -m data_agent`
- Validation: `uv run python scripts/validate_project.py`
- Tests: `uv run python -m unittest discover -s tests -v`

Keep procedural changes in the owning skill, shared invariants in `AGENTS.md`, and user guidance in
`README.md` or `docs/WORKFLOW.md`. Keep generated conversion artifacts under `semantic/generated/`
and promoted models under `semantic/models/`.
