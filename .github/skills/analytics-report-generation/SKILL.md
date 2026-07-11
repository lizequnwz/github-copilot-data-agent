---
name: analytics-report-generation
description: Create an accessible Python-rendered SVG chart or self-contained responsive HTML report from validated aggregate results.
---

# Procedure

1. Require a passing result-validation response and aggregate, non-restricted rows.
2. Choose a line chart for a time trend, a sorted bar chart for up to 15 categories, or a table when exact values matter more than shape.
3. Include a descriptive title, units, date range, direct value labels, and chart alternative text. Never rely on color alone.
4. Use `render-chart`; do not generate arbitrary plotting code, JavaScript, or remote assets.
5. Provide the chart and its underlying table to `render-report`.
6. Include the direct finding, definitions, methodology, freshness, Ossie model/source tier, query ID, role, confidence, SQL appendix, and caveats.
7. Write the final HTML under `reports/generated/` and verify it contains the expected title, rows, provenance, responsive viewport, and chart text alternative.

# UX requirements

- Semantic heading order and a skip link.
- Keyboard-visible focus and a scrollable table wrapper on small screens.
- Minimum 16px body text, high-contrast semantic color tokens, and tabular numerals.
- Light/dark mode, reduced-motion behavior, and print styling.
- No remote scripts, fonts, images, or executable chart content.

# Stop conditions

Stop on unvalidated or truncated results, missing provenance, row-level sensitive data, non-finite chart values, misleading chart selection, or unsafe markup.
