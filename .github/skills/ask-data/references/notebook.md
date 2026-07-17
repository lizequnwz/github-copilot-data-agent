# Notebook workspace

Create a workspace automatically for every covered plan, including a plan that has not executed,
unless the user requests an inline-only answer.

The workspace contains `analysis.json`, `analysis.md`, and `analysis.ipynb`. Preserve the question,
model identity and SHA, normalized plan and SHA, generated SQL, parameters, query evidence, result,
validation state, findings, caveats, and artifact paths.

Expose simple editable variables for metrics, dimensions, filters, time grains, derived logic,
calculations, ordering, and row limit. Build the internal plan from those variables.

Reuse saved evidence only while the model path and plan signature are unchanged. Recompile an edited
plan automatically. Never silently show old results for a changed plan. Live execution remains
explicit and requires confirmed Snowflake context.

Display generated SQL but do not treat it as the editable source of truth. Route database work
through the Ask Data service rather than opening a raw Snowflake connection in notebook cells.

Include a pandas result frame, a useful editable chart cell, and an optional HTML-report cell.
Clearly distinguish semantic SQL from notebook-only transformations.
