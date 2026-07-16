from __future__ import annotations

import re
from typing import Any

from data_agent.config import Settings
from data_agent.io import ContractError
from data_agent.security.sql import (
    explicit_query_limit,
    query_projection_names,
    validate_sql,
)
from data_agent.semantic.models import promoted_sources

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_INTERPRETATION_FIELDS = (
    "metric",
    "formula",
    "population",
    "dimensions",
    "filters",
    "period",
    "expected_result_grain",
    "requested_output",
)


def compile_ad_hoc(request: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Validate and normalize one explicitly unpromoted text-to-SQL analysis."""

    sql = request.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise ContractError("ad hoc analysis requires non-empty sql")
    parameters = request.get("parameters", [])
    if not isinstance(parameters, list):
        raise ContractError("ad hoc analysis parameters must be an array")
    max_rows = _max_rows(request.get("max_rows", settings.max_rows), settings.max_rows)
    query_limit = explicit_query_limit(sql)
    if query_limit != max_rows + 1:
        raise ContractError(f"ad hoc SQL must use LIMIT {max_rows + 1} to detect truncation")

    approved = tuple(sorted(set(settings.allowed_objects).union(promoted_sources())))
    if not approved:
        raise ContractError(
            "ad hoc SQL requires a promoted source or an object in access.allowed_objects"
        )
    validation = validate_sql(
        sql,
        blocked_schemas=settings.blocked_schemas,
        allowed_objects=approved,
        parameters=parameters,
        require_parameterized_predicates=True,
    )
    outputs = list(query_projection_names(sql))
    result_grain = request.get("result_grain", [])
    if not isinstance(result_grain, list) or not all(
        isinstance(name, str) for name in result_grain
    ):
        raise ContractError("ad hoc result_grain must be an array of output column names")
    output_lookup = {name.casefold() for name in outputs}
    unknown_grain = [name for name in result_grain if name.casefold() not in output_lookup]
    if unknown_grain:
        raise ContractError(
            f"ad hoc result_grain contains unknown outputs: {', '.join(unknown_grain)}"
        )

    metric = _metric_definition(request.get("metric"), outputs)
    interpretation = _interpretation(request.get("interpretation"))
    return {
        "sql": sql,
        "parameters": parameters,
        "grain": result_grain,
        "result_grain": result_grain,
        "result_columns": {name: name for name in outputs},
        "model": None,
        "max_rows": max_rows,
        "query_limit": query_limit,
        "period": interpretation["period"],
        "normalized_plan": {
            "analysis_mode": "ad_hoc",
            "metric": metric,
            "interpretation": interpretation,
            "result_grain": result_grain,
            "max_rows": max_rows,
            "approved_objects": list(validation.referenced_objects),
        },
        "metric_definitions": [metric],
        "analysis_mode": "ad_hoc",
        "unpromoted": True,
        "referenced_objects": list(validation.referenced_objects),
    }


def _max_rows(value: Any, configured_max: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractError("ad hoc max_rows must be an integer") from exc
    if parsed <= 0:
        raise ContractError("ad hoc max_rows must be positive")
    return min(parsed, configured_max, 5000)


def _metric_definition(value: Any, outputs: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("ad hoc analysis requires a metric definition")
    name = value.get("name")
    formula = value.get("formula")
    description = value.get("description")
    assumptions = value.get("assumptions", [])
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ContractError("ad hoc metric name must be a safe SQL output name")
    if name.casefold() not in {output.casefold() for output in outputs}:
        raise ContractError("ad hoc metric name must match a selected SQL output")
    if not isinstance(formula, str) or not formula.strip():
        raise ContractError("ad hoc metric requires a formula")
    if not isinstance(description, str) or not description.strip():
        raise ContractError("ad hoc metric requires a description")
    if not isinstance(assumptions, list) or not all(
        isinstance(assumption, str) for assumption in assumptions
    ):
        raise ContractError("ad hoc metric assumptions must be an array of strings")
    return {
        "name": name,
        "formula": formula.strip(),
        "description": description.strip(),
        "assumptions": assumptions,
        "unpromoted": True,
    }


def _interpretation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("ad hoc analysis requires an interpretation object")
    missing = [
        field
        for field in _INTERPRETATION_FIELDS
        if field not in value or value[field] is None or value[field] == ""
    ]
    if missing:
        raise ContractError(f"ad hoc interpretation is missing: {', '.join(missing)}")
    return {field: value[field] for field in _INTERPRETATION_FIELDS}
