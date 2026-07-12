from __future__ import annotations

from typing import Any

from data_agent.io import ContractError, envelope, require_string
from data_agent.security.sql import validate_sql
from data_agent.semantic.compiler import compile_plan
from data_agent.semantic.models import load_document
from data_agent.tools.result_validation import validate_result
from data_agent.tools.snowflake import execute_readonly, load_settings


def analyze(request: dict[str, Any]) -> dict[str, Any]:
    """Compile, validate, optionally execute, and validate one semantic analysis plan."""

    model_path = require_string(request, "model_path")
    plan = request.get("plan")
    if not isinstance(plan, dict):
        raise ContractError("plan must be an object")

    compiled = compile_plan(load_document(model_path), plan)
    result: dict[str, Any]
    if request.get("execute") is True:
        settings = load_settings(request)
        sql_validation = validate_sql(
            compiled["sql"],
            blocked_schemas=settings.blocked_schemas,
            allowed_objects=settings.allowed_objects,
        )
        result = execute_readonly(
            {
                **request,
                "sql": compiled["sql"],
                "parameters": compiled["parameters"],
                "max_rows": plan.get("max_rows", settings.max_rows),
            }
        )
    else:
        sql_validation = validate_sql(compiled["sql"])
        example_result = request.get("example_result")
        if example_result is None:
            return envelope(
                request,
                "planned",
                model=compiled["model"],
                grain=compiled["grain"],
                sql=compiled["sql"],
                parameters=compiled["parameters"],
                sql_validation=sql_validation.as_dict(),
                warnings=list(sql_validation.warnings),
            )
        if not isinstance(example_result, dict):
            raise ContractError("example_result must be an object")
        result = example_result

    checks = request.get("result_checks", {})
    if not isinstance(checks, dict):
        raise ContractError("result_checks must be an object")
    validated = validate_result(
        {
            "request_id": request.get("request_id", "analysis"),
            "result": result,
            "grain": checks.get("grain", compiled["grain"]),
            "required_columns": checks.get("required_columns", []),
            "required_non_null": checks.get("required_non_null", []),
            "numeric_ranges": checks.get("numeric_ranges", {}),
        }
    )
    return envelope(
        request,
        "success" if validated["status"] == "pass" else "validation_failed",
        model=compiled["model"],
        grain=compiled["grain"],
        sql=compiled["sql"],
        parameters=compiled["parameters"],
        sql_validation=sql_validation.as_dict(),
        result=result,
        result_validation=validated,
        warnings=list(sql_validation.warnings),
    )
