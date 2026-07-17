# Charts and HTML reports

Reporting is the final presentation stage of Ask Data, not a separate analytical workflow.

Retain the promoted semantic model, model SHA, metric provenance, normalized plan, plan SHA,
compiler-generated SQL, parameters, query evidence, result, validation state, and material caveats.
Request-scoped logic remains visibly unpromoted.

Lead with a direct evidence-backed finding. Quantify useful ranks, shares, deltas, or trends
supported by displayed rows. Separate observations from explanations. Never invent causality,
confidence, freshness, or business definitions.

Prefer a table when exact values matter most. Use a line chart for time, a bar chart for categorical
comparison, and a waterfall only for an additive bridge. Every chart must have a title, text
alternative, finite plotted values, and a complete underlying table.

HTML reports must be self-contained, responsive, accessible, printable, and free of remote scripts,
fonts, and assets. Preserve keyboard/touch interactions, light/dark styles, definitions, notes,
methodology, and the optional SQL appendix.

Label reports **Exploratory · not validated** when checks are absent or `not_run`. Use the validated
label only after checks pass. Do not render a failed result as a validated report.

Write reports inside the analysis workspace unless the user selects another in-scope destination.
