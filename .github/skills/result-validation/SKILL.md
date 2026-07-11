---
name: result-validation
description: Check a Snowflake result for emptiness, truncation, duplicate grain, nulls, date coverage, ranges, and reconciliation before interpretation or reporting.
---

# Procedure

1. Require the result JSON, expected grain, required columns, and any known ranges or totals.
2. Run `validate-result`.
3. Check non-empty rows, truncation, duplicate grain keys, required nulls, requested date coverage, numeric ranges, and units.
4. Compare totals or an alternate calculation when the analytical risk warrants it.
5. Return pass/fail with evidence and corrections.

Do not treat successful SQL execution or visual inspection alone as validation. A failed check blocks confident interpretation and report generation.
