from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from data_agent.analysis import analyze
from data_agent.io import ContractError, envelope, read_json, write_json_atomic
from data_agent.reporting.render import render_chart, render_report
from data_agent.security.sql import SQLSafetyError, validate_sql
from data_agent.semantic.compiler import compile_plan
from data_agent.semantic.competency import run_competency_tests
from data_agent.semantic.conversion import convert_semantic
from data_agent.semantic.diff import semantic_changes
from data_agent.semantic.models import (
    SemanticError,
    load_document,
    search_documents,
)
from data_agent.semantic.ossie import validate_osi_document
from data_agent.semantic.review import review_semantic
from data_agent.tools.result_validation import validate_result
from data_agent.tools.snowflake import (
    cancel_query,
    config_check,
    connection_check,
    describe_object,
    execute_readonly,
    profile_table,
    sample_values,
    search_objects,
)

Handler = Callable[[dict[str, Any]], dict[str, Any]]


def handle_validate_sql(request: dict[str, Any]) -> dict[str, Any]:
    result = validate_sql(
        str(request.get("sql", "")),
        blocked_schemas=request.get("blocked_schemas", []),
        allowed_objects=request.get("allowed_objects", []),
    )
    return envelope(request, "success", validation=result.as_dict(), warnings=list(result.warnings))


def handle_osi_validate(request: dict[str, Any]) -> dict[str, Any]:
    document = load_document(str(request.get("model_path")))
    validation = validate_osi_document(document)
    return envelope(
        request,
        "valid" if validation["official_valid"] else "invalid",
        **validation,
        warnings=[issue["message"] for issue in validation["readiness_issues"]],
    )


def handle_osi_search(request: dict[str, Any]) -> dict[str, Any]:
    roots = request.get("roots", ["semantic/models"])
    paths = [
        path
        for root in roots
        for path in Path(root).rglob("*")
        if path.suffix.lower() in {".yaml", ".yml", ".json"}
    ]
    matches = search_documents(paths, str(request.get("query", "")))
    return envelope(
        request, "success", matches=matches[: int(request.get("limit", 20))], warnings=[]
    )


def handle_osi_compile(request: dict[str, Any]) -> dict[str, Any]:
    document = load_document(str(request.get("model_path")))
    plan = request.get("plan")
    if not isinstance(plan, dict):
        raise ContractError("plan must be an object")
    compiled = compile_plan(document, plan)
    return envelope(request, "success", **compiled, warnings=[])


def handle_semantic_diff(request: dict[str, Any]) -> dict[str, Any]:
    before = load_document(str(request.get("before_path")))
    after = load_document(str(request.get("after_path")))
    before_text = json.dumps(before, sort_keys=True, separators=(",", ":"))
    after_text = json.dumps(after, sort_keys=True, separators=(",", ":"))
    diff = semantic_changes(before, after)
    return envelope(
        request,
        "success",
        changed=before_text != after_text,
        before_sha256=_sha(before_text),
        after_sha256=_sha(after_text),
        **diff,
        warnings=[],
    )


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()


HANDLERS: dict[str, Handler] = {
    "analyze": analyze,
    "config-check": config_check,
    "connection-check": connection_check,
    "execute-readonly": execute_readonly,
    "search-objects": search_objects,
    "describe-object": describe_object,
    "sample-values": sample_values,
    "profile-table": profile_table,
    "cancel-query": cancel_query,
    "validate-sql": handle_validate_sql,
    "osi-validate": handle_osi_validate,
    "osi-search": handle_osi_search,
    "osi-test": run_competency_tests,
    "osi-compile": handle_osi_compile,
    "semantic-convert": convert_semantic,
    "semantic-review": review_semantic,
    "semantic-diff": handle_semantic_diff,
    "validate-result": validate_result,
    "render-chart": render_chart,
    "render-report": render_report,
}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Snowflake data agent local command runner")
    result.add_argument("command", choices=sorted(HANDLERS))
    result.add_argument("--input", required=True, help="JSON request path")
    result.add_argument("--output", required=True, help="JSON response path")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    request: dict[str, Any] = {"request_id": "unreadable"}
    try:
        request = read_json(args.input)
        response = HANDLERS[args.command](request)
        exit_code = (
            0
            if response.get("status")
            not in {
                "invalid",
                "fail",
                "context_mismatch",
                "configuration_required",
                "validation_failed",
            }
            else 2
        )
    except (ContractError, SQLSafetyError, SemanticError, ValueError, OSError) as exc:
        response = envelope(
            request, "error", error_type=type(exc).__name__, message=str(exc), warnings=[]
        )
        exit_code = 2
    except Exception as exc:  # Defensive boundary: return no traceback/secrets to the caller.
        response = envelope(
            request,
            "error",
            error_type="InternalError",
            message="tool failed; inspect local diagnostics",
            warnings=[],
        )
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        exit_code = 3
    write_json_atomic(args.output, response)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
