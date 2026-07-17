from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

from data_agent.io import ContractError, envelope
from data_agent.models import (
    ROOT,
    iter_models,
    load_document,
    load_promoted_document,
)

_FIELD_REFERENCE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_$]*\.[A-Za-z_][A-Za-z0-9_$]*)\b"
)


def plan_requirements(plan: dict[str, Any]) -> dict[str, list[str]]:
    metrics = _string_list(plan.get("metric_ids", []), "metric_ids")
    fields = _string_list(plan.get("dimensions", []), "dimensions")
    for item in plan.get("filters", []):
        if isinstance(item, dict) and isinstance(item.get("field"), str):
            fields.append(item["field"])
    for key in ("time_range",):
        item = plan.get(key)
        if isinstance(item, dict) and isinstance(item.get("field"), str):
            fields.append(item["field"])
    for item in plan.get("time_dimensions", []):
        if isinstance(item, dict) and isinstance(item.get("field"), str):
            fields.append(item["field"])
    for collection in ("derived_metrics", "derived_dimensions"):
        for item in plan.get(collection, []):
            if isinstance(item, dict) and isinstance(item.get("expression"), str):
                fields.extend(_FIELD_REFERENCE.findall(item["expression"]))
    return {
        "metrics": sorted(set(metrics)),
        "fields": sorted(set(fields)),
    }


def diagnose_document_coverage(
    document: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    requested_model = str(plan.get("semantic_model", ""))
    models = [model for model in iter_models(document) if model.get("name") == requested_model]
    if len(models) != 1:
        return {
            "status": "gap",
            "model": requested_model,
            "covered": {"metrics": [], "fields": []},
            "missing": {"metrics": [], "fields": []},
            "join_path_available": False,
            "suggestions": {},
            "reason": "semantic model is absent or ambiguous",
        }
    model = models[0]
    requirements = plan_requirements(plan)
    metric_names = {
        str(item.get("name"))
        for item in model.get("metrics", [])
        if isinstance(item, dict)
    }
    field_names = {
        f"{dataset.get('name')}.{field.get('name')}"
        for dataset in model.get("datasets", [])
        if isinstance(dataset, dict)
        for field in dataset.get("fields", [])
        if isinstance(field, dict)
    }
    covered_metrics = sorted(set(requirements["metrics"]).intersection(metric_names))
    covered_fields = sorted(set(requirements["fields"]).intersection(field_names))
    missing_metrics = sorted(set(requirements["metrics"]) - metric_names)
    missing_fields = sorted(set(requirements["fields"]) - field_names)
    referenced_datasets = sorted({field.split(".", 1)[0] for field in covered_fields})
    join_path = _join_path_available(model, referenced_datasets)
    status = "covered" if not missing_metrics and not missing_fields and join_path else "gap"
    return {
        "status": status,
        "model": requested_model,
        "covered": {"metrics": covered_metrics, "fields": covered_fields},
        "missing": {"metrics": missing_metrics, "fields": missing_fields},
        "join_path_available": join_path,
        "referenced_datasets": referenced_datasets,
        "suggestions": {
            "metrics": _suggest(missing_metrics, metric_names),
            "fields": _suggest(missing_fields, field_names),
        },
        "reason": (
            None
            if status == "covered"
            else "missing semantic coverage"
            if missing_metrics or missing_fields
            else "model-defined relationships do not connect the requested datasets"
        ),
    }


def diagnose_coverage(request: dict[str, Any]) -> dict[str, Any]:
    plan = request.get("plan")
    if not isinstance(plan, dict):
        raise ContractError("plan must be an object")
    model_path = request.get("model_path")
    candidates: list[dict[str, Any]] = []
    if isinstance(model_path, str) and model_path:
        paths = [Path(model_path)]
    else:
        paths = sorted(
            path
            for path in (ROOT / "semantic/models").rglob("*")
            if path.suffix.casefold() in {".yaml", ".yml", ".json"}
        )
    for path in paths:
        try:
            document = (
                load_promoted_document(path)
                if isinstance(model_path, str) and model_path
                else load_document(path)
            )
        except (OSError, ValueError):
            continue
        for model in iter_models(document):
            candidate_plan = {**plan, "semantic_model": str(model.get("name", ""))}
            coverage = diagnose_document_coverage(document, candidate_plan)
            score = (
                len(coverage["covered"]["metrics"])
                + len(coverage["covered"]["fields"])
                + (1 if coverage["join_path_available"] else 0)
            )
            candidates.append(
                {
                    **coverage,
                    "model_path": str(path),
                    "score": score,
                }
            )
    candidates.sort(
        key=lambda item: (
            item["status"] != "covered",
            -int(item["score"]),
            str(item["model"]),
        )
    )
    best = candidates[0] if candidates else None
    return envelope(
        request,
        "covered" if best and best["status"] == "covered" else "coverage_gap",
        best_match=best,
        candidates=candidates,
        next_action=(
            "compile_plan"
            if best and best["status"] == "covered"
            else "semantic_setup"
        ),
        warnings=[],
    )


def _join_path_available(model: dict[str, Any], datasets: list[str]) -> bool:
    if len(datasets) < 2:
        return True
    graph: dict[str, set[str]] = {}
    for relationship in model.get("relationships", []):
        if not isinstance(relationship, dict):
            continue
        left = str(relationship.get("from", ""))
        right = str(relationship.get("to", ""))
        if left and right:
            graph.setdefault(left, set()).add(right)
            graph.setdefault(right, set()).add(left)
    visited = {datasets[0]}
    queue = [datasets[0]]
    while queue:
        current = queue.pop(0)
        for neighbor in graph.get(current, set()) - visited:
            visited.add(neighbor)
            queue.append(neighbor)
    return set(datasets).issubset(visited)


def _suggest(missing: list[str], available: set[str]) -> dict[str, list[str]]:
    return {
        name: difflib.get_close_matches(name, sorted(available), n=3, cutoff=0.35)
        for name in missing
    }


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be an array")
    return [str(item) for item in value]
