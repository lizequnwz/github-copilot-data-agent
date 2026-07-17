from __future__ import annotations

from typing import Any

from data_agent.io import ContractError, envelope, require_string
from data_agent.security.sql import validate_sql
from data_agent.semantic.compiler import compile_plan
from data_agent.semantic.models import load_promoted_document
from data_agent.tools.result_validation import validate_result
from data_agent.tools.snowflake import execute_readonly, load_settings


def analyze(request: dict[str, Any]) -> dict[str, Any]:
    """Compile a semantic plan, optionally execute it, and optionally validate the result."""

    if "analysis_mode" in request:
        raise ContractError(
            "analysis_mode is no longer a request field; Ask Data always uses model_path and plan"
        )
    model_path = require_string(request, "model_path")
    plan = request.get("plan")
    if not isinstance(plan, dict):
        raise ContractError("plan must be an object")
    compiled = compile_plan(load_promoted_document(model_path), plan)

    result: dict[str, Any]
    if request.get("execute") is True:
        settings = load_settings(request)
        sql_validation = validate_sql(
            compiled["sql"],
            allowed_objects=compiled["referenced_objects"],
        )
        result = execute_readonly(
            {
                **request,
                "sql": compiled["sql"],
                "parameters": compiled["parameters"],
                "max_rows": min(compiled["max_rows"], settings.max_rows),
                "query_limit": compiled["query_limit"],
                "allowed_objects": compiled["referenced_objects"],
                "enforce_blocked_schemas": False,
            }
        )
    else:
        sql_validation = validate_sql(
            compiled["sql"],
            allowed_objects=compiled["referenced_objects"],
        )
        example_result = request.get("example_result")
        if example_result is None:
            return envelope(
                request,
                "planned",
                **_response_fields(compiled),
                sql_validation=sql_validation.as_dict(),
                warnings=list(sql_validation.warnings),
            )
        if not isinstance(example_result, dict):
            raise ContractError("example_result must be an object")
        result = example_result

    checks = request.get("result_checks", {})
    if not isinstance(checks, dict):
        raise ContractError("result_checks must be an object")
    validation_requested = request.get("validate_result") is True or bool(checks)
    if not validation_requested:
        return envelope(
            request,
            "success",
            **_response_fields(compiled),
            sql_validation=sql_validation.as_dict(),
            result=result,
            result_validation={
                "request_id": str(request.get("request_id", "analysis")),
                "status": "not_run",
                "checks": {},
                "errors": [],
                "warnings": [
                    "result checks were not requested; add validation when assurance is useful"
                ],
            },
            warnings=list(sql_validation.warnings),
        )
    validated = validate_result(
        {
            "request_id": request.get("request_id", "analysis"),
            "result": result,
            "grain": checks.get("grain", compiled["result_grain"]),
            "required_columns": checks.get(
                "required_columns", list(compiled["result_columns"].values())
            ),
            "required_non_null": checks.get("required_non_null", []),
            "numeric_ranges": checks.get("numeric_ranges", {}),
            "allow_empty": checks.get("allow_empty", False),
        }
    )
    return envelope(
        request,
        "success" if validated["status"] == "pass" else "validation_failed",
        **_response_fields(compiled),
        sql_validation=sql_validation.as_dict(),
        result=result,
        result_validation=validated,
        warnings=list(sql_validation.warnings),
    )


def _response_fields(compiled: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "metric_source",
        "model",
        "grain",
        "result_grain",
        "result_columns",
        "sql",
        "parameters",
        "max_rows",
        "query_limit",
        "period",
        "normalized_plan",
        "metric_definitions",
        "unpromoted",
        "referenced_objects",
    )
    return {key: compiled[key] for key in keys if key in compiled}
