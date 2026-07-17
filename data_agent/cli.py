from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from data_agent.ask.analysis import analyze
from data_agent.ask.compiler import compile_plan
from data_agent.ask.coverage import diagnose_coverage
from data_agent.ask.report import render_chart, render_report
from data_agent.ask.service import ask_data
from data_agent.ask.validation import validate_result
from data_agent.ask.workspace import render_analysis_workspace
from data_agent.diagnostics import run_check
from data_agent.io import ContractError, envelope, read_json, write_json_atomic
from data_agent.models import (
    SemanticError,
    load_document,
    load_promoted_document,
    search_documents,
)
from data_agent.ossie import validate_osi_document
from data_agent.setup.competency import run_competency_tests
from data_agent.setup.conversion import convert_semantic
from data_agent.setup.diff import semantic_changes
from data_agent.setup.review import review_semantic
from data_agent.setup.review_workspace import (
    compile_decisions,
    load_decisions,
    review_paths,
    serve_review,
)
from data_agent.snowflake import (
    cancel_query,
    config_check,
    connection_check,
    describe_object,
    execute_readonly,
    profile_table,
    sample_values,
    search_objects,
)
from data_agent.sql_safety import SQLSafetyError, validate_sql

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
    document = load_promoted_document(str(request.get("model_path")))
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
    "ask": ask_data,
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
    "model-coverage": diagnose_coverage,
    "semantic-convert": convert_semantic,
    "semantic-review": review_semantic,
    "semantic-diff": handle_semantic_diff,
    "validate-result": validate_result,
    "render-chart": render_chart,
    "render-report": render_report,
    "render-workspace": render_analysis_workspace,
}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Semantic-model-first Snowflake data agent")
    commands = result.add_subparsers(
        dest="command",
        required=True,
        metavar="{ask,doctor,model}",
    )

    ask = commands.add_parser("ask", help="Run Ask Data and create a workspace by default")
    ask.add_argument("--input", required=True, help="Analysis JSON path")
    ask.add_argument("--output", help="Optional response JSON path; defaults to stdout")
    ask.add_argument("--workspace-dir", help="Override the default analysis workspace")
    ask.add_argument("--no-workspace", action="store_true")
    ask.add_argument("--report", action="store_true", help="Also create an HTML report")

    doctor = commands.add_parser("doctor", help="Check Snowflake configuration and connection")
    doctor.add_argument("--config-path", default="snowflake_config.yaml")
    doctor.add_argument(
        "--connect",
        action="store_true",
        help="Connect after displaying the non-secret configured context",
    )

    model = commands.add_parser("model", help="Set up or inspect semantic-model coverage")
    model_commands = model.add_subparsers(dest="model_command", required=True)
    setup = model_commands.add_parser("setup", help="Convert a BI export and open model review")
    setup.add_argument("source")
    setup.add_argument("--model-name")
    setup.add_argument("--source-type", default="auto")
    setup.add_argument("--source-map")
    setup.add_argument("--field-map")
    setup.add_argument("--descriptor")
    setup.add_argument("--output-dir", default="workspaces/models")
    setup.add_argument("--review", action=argparse.BooleanOptionalAction, default=True)
    replay = setup.add_mutually_exclusive_group()
    replay.add_argument(
        "--review-decisions",
        help="Replay guided review decisions instead of opening the review workspace",
    )
    replay.add_argument(
        "--review-patch",
        help="Apply an advanced audited JSON patch instead of opening the review workspace",
    )
    setup.add_argument("--review-port", type=int, default=0)
    setup.add_argument("--no-open", action="store_true")
    setup.add_argument("--no-promote", action="store_true")
    setup.add_argument("--verify-snowflake", action="store_true")
    setup.add_argument("--configuration-confirmed", action="store_true")
    setup.add_argument("--config-path", default="snowflake_config.yaml")
    setup.add_argument("--output", help="Optional response JSON path")

    coverage = model_commands.add_parser(
        "coverage", help="Diagnose whether promoted models cover a semantic plan"
    )
    coverage.add_argument("--input", required=True)
    coverage.add_argument("--output")

    advanced = commands.add_parser("advanced", help=argparse.SUPPRESS)
    advanced.add_argument("operation", choices=sorted(HANDLERS))
    advanced.add_argument("--input", required=True)
    advanced.add_argument("--output", required=True)
    commands._choices_actions = [
        choice
        for choice in commands._choices_actions
        if choice.dest != "advanced"
    ]
    return result


def main(argv: list[str] | None = None) -> int:
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    if raw_args and raw_args[0] in HANDLERS and raw_args[0] != "ask":
        raw_args = ["advanced", *raw_args]
    args = parser().parse_args(raw_args)
    if args.command == "doctor":
        return _doctor(args.config_path, connect=args.connect)
    if args.command == "model" and args.model_command == "setup":
        return _model_setup(args)
    if args.command == "model" and args.model_command == "coverage":
        request = read_json(args.input)
        return _emit(diagnose_coverage(request), args.output)
    if args.command == "ask":
        request = read_json(args.input)
        if args.workspace_dir:
            request["workspace_dir"] = args.workspace_dir
        if args.no_workspace:
            request["workspace"] = False
        if args.report:
            request["report"] = True
        return _emit(ask_data(request), args.output)
    return _run_advanced(args.operation, args.input, args.output)


def _run_advanced(command: str, input_path: str, output_path: str) -> int:
    request: dict[str, Any] = {"request_id": "unreadable"}
    try:
        request = read_json(input_path)
        response = HANDLERS[command](request)
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
    write_json_atomic(output_path, response)
    return exit_code


def _doctor(config_path: str, *, connect: bool) -> int:
    if not connect:
        request = {"request_id": "doctor", "config_path": config_path}
        try:
            checked = config_check(request)
        except (ContractError, ValueError, OSError) as exc:
            print(json.dumps({"status": "configuration_required", "message": str(exc)}, indent=2))
            return 2
        print(json.dumps(checked, indent=2, sort_keys=True))
        return 0 if checked["status"] == "ready" else 2
    exit_code, lines = run_check(config_path)
    print("\n".join(lines), flush=True)
    return exit_code


def _model_setup(args: argparse.Namespace) -> int:
    request = {
        "request_id": "semantic-model-setup",
        "source_path": args.source,
        "source_type": args.source_type,
        "model_name": args.model_name,
        "descriptor_path": args.descriptor,
        "source_map": _json_object(args.source_map, "--source-map"),
        "field_map": _json_object(args.field_map, "--field-map"),
        "output_dir": args.output_dir,
    }
    converted = convert_semantic(request)
    response: dict[str, Any] = converted
    if converted["status"] != "success":
        return _emit(response, args.output)

    paths = review_paths(converted["raw_model_path"], converted["manifest_path"])
    review_request = {
        "request_id": request["request_id"],
        "raw_model_path": converted["raw_model_path"],
        "manifest_path": converted["manifest_path"],
        "verify_snowflake": args.verify_snowflake,
        "config_path": args.config_path,
        "configuration_confirmed": args.configuration_confirmed,
        "promote_if_clean": not args.no_promote,
    }
    if args.review_decisions:
        decisions = load_decisions(args.review_decisions, paths.raw)
        review_result = review_semantic(
            {**review_request, "patch": compile_decisions(decisions, paths)}
        )
        response = {**converted, "review_result": review_result}
    elif args.review_patch:
        review_result = review_semantic(
            {**review_request, "patch_path": args.review_patch}
        )
        response = {**converted, "review_result": review_result}
    elif args.review:
        review = serve_review(
            paths,
            port=args.review_port,
            open_browser=not args.no_open,
            request_id=request["request_id"],
            verify_snowflake=args.verify_snowflake,
            config_path=args.config_path,
            configuration_confirmed=args.configuration_confirmed,
            promote_if_clean=not args.no_promote,
        )
        response = {**converted, "review_workspace": review}
    return _emit(response, args.output)


def _json_object(path: str | None, label: str) -> dict[str, Any]:
    if path is None:
        return {}
    value = read_json(path)
    if not isinstance(value, dict):
        raise ContractError(f"{label} must contain a JSON object")
    return value


def _emit(response: dict[str, Any], output_path: str | None) -> int:
    if output_path:
        write_json_atomic(output_path, response)
    else:
        print(json.dumps(response, indent=2, sort_keys=True, default=str))
    return (
        0
        if response.get("status")
        not in {
            "invalid",
            "fail",
            "context_mismatch",
            "configuration_required",
            "validation_failed",
            "coverage_gap",
            "error",
        }
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
