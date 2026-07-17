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
    if not all(isinstance(row, list) and len(row) == len(columns) for row in rows):
        raise ContractError("each result row must be an array matching the column count")
    column_indices: dict[str, int] = {}
    for index, name in enumerate(columns):
        canonical = name.casefold()
        if canonical in column_indices:
            raise ContractError(
                f"result columns are ambiguous when matched case-insensitively: {name}"
            )
        column_indices[canonical] = index
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {
        "non_empty": bool(rows),
        "empty_allowed": request.get("allow_empty") is True,
        "truncated": bool(result.get("truncated", False)),
    }
    if not rows and request.get("allow_empty") is not True:
        errors.append("result is empty")
    if result.get("truncated"):
        errors.append("result is truncated")
    required = _column_names(request.get("required_columns", []), "required_columns")
    missing = sorted(name for name in required if name.casefold() not in column_indices)
    checks["missing_required_columns"] = missing
    if missing:
        errors.append(f"missing required columns: {', '.join(missing)}")
    grain = _column_names(request.get("grain", []), "grain")
    indices = [
        column_indices[name.casefold()] for name in grain if name.casefold() in column_indices
    ]
    if len(indices) != len(grain):
        errors.append("one or more grain columns are absent")
    elif grain:
        keys = [tuple(row[index] for index in indices) for row in rows]
        duplicates = sum(count - 1 for count in Counter(keys).values() if count > 1)
        checks["duplicate_grain_rows"] = duplicates
        if duplicates:
            errors.append(f"{duplicates} duplicate rows at expected grain")
    required_non_null = _column_names(request.get("required_non_null", []), "required_non_null")
    null_counts = {}
    for name in required_non_null:
        if name.casefold() in column_indices:
            index = column_indices[name.casefold()]
            null_counts[name] = sum(row[index] is None for row in rows)
    checks["required_null_counts"] = null_counts
    if any(null_counts.values()):
        errors.append("required columns contain nulls")
    numeric_ranges = request.get("numeric_ranges", {})
    if not isinstance(numeric_ranges, dict):
        raise ContractError("numeric_ranges must be an object")
    for name, bounds in numeric_ranges.items():
        if (
            not isinstance(name, str)
            or name.casefold() not in column_indices
            or not isinstance(bounds, dict)
        ):
            continue
        index = column_indices[name.casefold()]
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


def _column_names(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ContractError(f"{label} must be an array of column names")
    return value
