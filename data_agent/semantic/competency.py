from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from data_agent.io import ContractError, envelope
from data_agent.semantic.compiler import compile_plan
from data_agent.semantic.models import load_document


def run_competency_tests(request: dict[str, Any]) -> dict[str, Any]:
    model_path = request.get("model_path")
    cases_path = request.get("cases_path")
    if not isinstance(model_path, str) or not model_path:
        raise ContractError("model_path must be a non-empty string")
    if not isinstance(cases_path, str) or not cases_path:
        raise ContractError("cases_path must be a non-empty string")
    result = test_document(load_document(model_path), Path(cases_path))
    return envelope(
        request,
        "pass" if result["passed"] else "fail",
        **result,
        warnings=[],
    )


def test_document(document: dict[str, Any], cases_path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(cases_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        raise ContractError("competency fixture must contain a cases array")
    results: list[dict[str, Any]] = []
    for index, case in enumerate(raw["cases"]):
        if not isinstance(case, dict):
            raise ContractError(f"competency case {index} must be an object")
        identifier = str(case.get("id") or f"case_{index + 1}")
        plan = case.get("plan")
        expected = case.get("expected", {})
        if not isinstance(plan, dict) or not isinstance(expected, dict):
            raise ContractError(f"competency case {identifier} requires plan and expected objects")
        errors: list[str] = []
        try:
            compiled = compile_plan(document, plan)
        except ValueError as exc:
            results.append(
                {
                    "id": identifier,
                    "question": case.get("question"),
                    "passed": False,
                    "errors": [str(exc)],
                }
            )
            continue
        for key in ("grain", "result_grain"):
            wanted = expected.get(key)
            if wanted is not None and compiled[key] != wanted:
                errors.append(f"{key} expected {wanted!r}, got {compiled[key]!r}")
        for fragment in expected.get("sql_contains", []):
            if str(fragment) not in compiled["sql"]:
                errors.append(f"SQL is missing expected fragment: {fragment}")
        for fragment in expected.get("sql_excludes", []):
            if str(fragment) in compiled["sql"]:
                errors.append(f"SQL contains excluded fragment: {fragment}")
        results.append(
            {
                "id": identifier,
                "question": case.get("question"),
                "passed": not errors,
                "errors": errors,
                "grain": compiled["grain"],
                "result_grain": compiled["result_grain"],
            }
        )
    return {
        "passed": all(item["passed"] for item in results),
        "case_count": len(results),
        "failed_count": sum(not item["passed"] for item in results),
        "results": results,
        "cases_path": str(cases_path),
    }
