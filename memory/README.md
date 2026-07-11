# Small reviewed memory

Memory is intentionally separate from semantic models:

- `approved/`: short, reviewed business notes the agent may use.
- `pending/`: evidence-backed proposals awaiting review.

Metrics, fields, joins, source mappings, and conversion evidence belong under `semantic/`, not here. The agent may propose a pending note but never edits approved notes automatically.
