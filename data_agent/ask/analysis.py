from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from data_agent.io import ContractError, envelope, require_string
from data_agent.ask.compiler import compile_plan
from data_agent.ask.coverage import diagnose_document_coverage
from data_agent.ask.validation import validate_result
from data_agent.models import load_promoted_document
from data_agent.snowflake import execute_readonly, load_settings
from data_agent.sql_safety import validate_sql


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
    document = load_promoted_document(model_path)
    coverage = diagnose_document_coverage(document, plan)
    if coverage["status"] != "covered":
        return envelope(
            request,
            "coverage_gap",
            coverage=coverage,
            next_action="semantic_setup",
            model_path=model_path,
            plan=plan,
            warnings=[],
        )
    compiled = compile_plan(document, plan)
    compiled.update(_provenance(model_path, document, compiled["normalized_plan"]))

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
        "request_scoped_logic",
        "referenced_objects",
        "model_path",
        "semantic_model",
        "plan_sha256",
    )
    return {key: compiled[key] for key in keys if key in compiled}


def _provenance(
    model_path: str, document: dict[str, Any], normalized_plan: dict[str, Any]
) -> dict[str, Any]:
    source = Path(model_path).resolve()
    plan_text = json.dumps(normalized_plan, sort_keys=True, separators=(",", ":"), default=str)
    model = document.get("semantic_model", [{}])[0]
    return {
        "model_path": str(source),
        "semantic_model": {
            "name": model.get("name"),
            "path": str(source),
            "version": document.get("version"),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        },
        "plan_sha256": hashlib.sha256(plan_text.encode("utf-8")).hexdigest(),
    }
