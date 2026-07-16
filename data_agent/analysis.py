from __future__ import annotations

from typing import Any

from data_agent.ad_hoc import compile_ad_hoc
from data_agent.io import ContractError, envelope, require_string
from data_agent.security.sql import validate_sql
from data_agent.semantic.compiler import compile_plan
from data_agent.semantic.models import load_promoted_document
from data_agent.tools.result_validation import validate_result
from data_agent.tools.snowflake import execute_readonly, load_settings


def analyze(request: dict[str, Any]) -> dict[str, Any]:
    """Compile, validate, optionally execute, and validate one governed analysis."""

    requested_mode = str(request.get("analysis_mode", "semantic")).casefold()
    if requested_mode == "ad_hoc":
        settings = load_settings(request)
        compiled = compile_ad_hoc(request, settings)
    elif requested_mode in {"semantic", "promoted", "derived"}:
        model_path = require_string(request, "model_path")
        plan = request.get("plan")
        if not isinstance(plan, dict):
            raise ContractError("plan must be an object")
        compiled = compile_plan(load_promoted_document(model_path), plan)
    else:
        raise ContractError("analysis_mode must be semantic or ad_hoc")

    result: dict[str, Any]
    if request.get("execute") is True:
        settings = load_settings(request)
        require_parameterized = compiled["analysis_mode"] == "ad_hoc"
        sql_validation = validate_sql(
            compiled["sql"],
            blocked_schemas=settings.blocked_schemas,
            allowed_objects=(
                tuple(compiled.get("referenced_objects", []))
                if require_parameterized
                else settings.allowed_objects
            ),
            parameters=compiled["parameters"] if require_parameterized else None,
            require_parameterized_predicates=require_parameterized,
        )
        result = execute_readonly(
            {
                **request,
                "sql": compiled["sql"],
                "parameters": compiled["parameters"],
                "max_rows": min(compiled["max_rows"], settings.max_rows),
                "query_limit": compiled["query_limit"],
                "require_approved_sources": require_parameterized,
                "require_parameterized_predicates": require_parameterized,
            }
        )
    else:
        if compiled["analysis_mode"] == "ad_hoc":
            settings = load_settings(request)
            sql_validation = validate_sql(
                compiled["sql"],
                blocked_schemas=settings.blocked_schemas,
                allowed_objects=compiled.get("referenced_objects", []),
                parameters=compiled["parameters"],
                require_parameterized_predicates=True,
            )
        else:
            sql_validation = validate_sql(compiled["sql"])
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
        "analysis_mode",
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
