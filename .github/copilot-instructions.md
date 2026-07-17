# Repository instructions

Follow `AGENTS.md` as the authoritative project contract. For end-to-end user work, route through
`.github/agents/data-analytics.agent.md`; do not restate its skill procedures here.

## Local commands

- Install: `uv sync --extra dev --extra snowflake`
- Offline exploration walkthrough: `uv run data-agent ask --input examples/ask-data/exploration.json`
- CLI: `uv run data-agent`
- Validation: `uv run python scripts/validate_project.py`
- Tests: `uv run python -m unittest discover -s tests -v`

Keep procedural changes in the owning skill, shared invariants in `AGENTS.md`, and user guidance in
`README.md`, `docs/ASK_DATA.md`, or `docs/SEMANTIC_SETUP.md`. Keep local work under `workspaces/`
and promoted models under `semantic/models/`.
