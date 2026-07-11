from __future__ import annotations

from collections import Counter
from typing import Any

from data_agent.io import ContractError, envelope


def validate_result(request: dict[str, Any]) -> dict[str, Any]:
    result = request.get("result")
    if not isinstance(result, dict):
        raise ContractError("result must be an object")
    columns = result.get("columns")
    rows = result.get("rows")
    if (
        not isinstance(columns, list)
        or not all(isinstance(c, str) for c in columns)
        or not isinstance(rows, list)
    ):
        raise ContractError("result requires string columns and row arrays")
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {
        "non_empty": bool(rows),
        "truncated": bool(result.get("truncated", False)),
    }
    if not rows:
        errors.append("result is empty")
    if result.get("truncated"):
        errors.append("result is truncated")
    required = request.get("required_columns", [])
    missing = sorted(set(required) - set(columns))
    checks["missing_required_columns"] = missing
    if missing:
        errors.append(f"missing required columns: {', '.join(missing)}")
    grain = request.get("grain", [])
    if not isinstance(grain, list):
        raise ContractError("grain must be an array")
    indices = [columns.index(name) for name in grain if name in columns]
    if len(indices) != len(grain):
        errors.append("one or more grain columns are absent")
    elif grain:
        keys = [tuple(row[index] for index in indices) for row in rows]
        duplicates = sum(count - 1 for count in Counter(keys).values() if count > 1)
        checks["duplicate_grain_rows"] = duplicates
        if duplicates:
            errors.append(f"{duplicates} duplicate rows at expected grain")
    required_non_null = request.get("required_non_null", [])
    null_counts = {}
    for name in required_non_null:
        if name in columns:
            index = columns.index(name)
            null_counts[name] = sum(row[index] is None for row in rows)
    checks["required_null_counts"] = null_counts
    if any(null_counts.values()):
        errors.append("required columns contain nulls")
    numeric_ranges = request.get("numeric_ranges", {})
    for name, bounds in numeric_ranges.items():
        if name not in columns or not isinstance(bounds, dict):
            continue
        index = columns.index(name)
        low, high = bounds.get("min"), bounds.get("max")
        invalid = sum(
            1
            for row in rows
            if row[index] is not None
            and ((low is not None and row[index] < low) or (high is not None and row[index] > high))
        )
        checks[f"{name}_out_of_range"] = invalid
        if invalid:
            errors.append(f"{name} contains {invalid} out-of-range values")
    return envelope(
        request, "pass" if not errors else "fail", checks=checks, errors=errors, warnings=warnings
    )
