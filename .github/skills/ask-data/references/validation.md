# Optional result validation

Exploration does not require formal result checks. Add checks when the user asks for assurance, the
analysis stabilizes, or the result will support a consequential or recurring decision.

Use only relevant checks:

- empty or truncated results;
- required columns;
- duplicate rows at expected result grain;
- required non-null values;
- known numeric ranges.

Validation changes assurance state, not semantic sourcing. The same promoted model and plan remain
the source of generated SQL.

Label results and reports **Exploratory · not validated** when checks did not run. Explain failed
checks and revise the plan or assumptions. Never label failed evidence as validated.
