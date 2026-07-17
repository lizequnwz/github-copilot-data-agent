from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from data_agent.setup.sources import extract_generic_ir, extract_powerbi_ir, extract_tableau_ir
from data_agent.io import ContractError, envelope, require_string, write_json_atomic
from data_agent.models import load_document
from data_agent.ossie import (
    EXPECTED_OSSIE_COMMIT,
    SCHEMA,
    schema_sha256,
    validate_osi_document,
)
from data_agent.setup.diff import semantic_changes
from data_agent.setup.ingestion import OSI_VERSION, build_osi_from_ir

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM_SCHEMA = (
    f"https://github.com/apache/ossie/blob/{EXPECTED_OSSIE_COMMIT}/core-spec/osi-schema.json"
)
SUPPORTED_SOURCE_TYPES = {"auto", "powerbi", "tableau", "generic", "semantic-ir", "osi"}


def detect_source_type(path: Path) -> str:
    if path.is_dir() and any(path.rglob("*.tmdl")):
        return "powerbi"
    if path.is_file() and path.suffix.lower() in {".twb", ".tds", ".tde"}:
        return "tableau"
    if path.is_file() and path.suffix.lower() in {".json", ".yaml", ".yml"}:
        try:
            document = load_document(path)
        except (OSError, ValueError):
            return "generic"
        if document.get("version") and document.get("semantic_model"):
            return "osi"
        if document.get("ir_version") and document.get("datasets"):
            return "semantic-ir"
        return "generic"
    raise ContractError(
        "could not detect semantic source; use a PBIP/TMDL directory, Tableau .twb/.tds/.tde, "
        "or JSON/YAML file"
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_") or "generated_model"


def _generated_root(request: dict[str, Any]) -> Path:
    configured = Path(str(request.get("output_dir", "workspaces/models")))
    root = (ROOT / configured).resolve() if not configured.is_absolute() else configured.resolve()
    generated = (ROOT / "workspaces/models").resolve()
    if root != generated and generated not in root.parents:
        raise ContractError("output_dir must be workspaces/models or a subdirectory")
    return root


def _load_ir(request: dict[str, Any], source_type: str) -> dict[str, Any]:
    if source_type == "powerbi":
        return extract_powerbi_ir(request)
    if source_type == "tableau":
        return extract_tableau_ir(request)
    if source_type in {"generic", "semantic-ir"}:
        return extract_generic_ir(request)
    raise ContractError(f"source type {source_type} does not produce semantic IR")


def _translation_counts(ir: dict[str, Any] | None) -> dict[str, int]:
    states = (
        "exact",
        "equivalent-with-assumptions",
        "partial",
        "unsupported",
        "reviewed-unsupported",
        "requires-human-review",
    )
    counts = {state: 0 for state in states}
    if ir is None:
        return counts
    elements: list[Any] = []
    elements.extend(ir.get("datasets", []))
    elements.extend(ir.get("relationships", []))
    elements.extend(ir.get("metrics", []))
    for dataset in ir.get("datasets", []):
        if isinstance(dataset, dict):
            elements.extend(dataset.get("fields", []))
    for element in elements:
        if not isinstance(element, dict):
            continue
        state = str(element.get("translation_status", ""))
        if state in counts:
            counts[state] += 1
    counts["unsupported"] += len(ir.get("unsupported", []))
    return counts


def _document_summary(document: dict[str, Any]) -> dict[str, int]:
    models = [item for item in document.get("semantic_model", []) if isinstance(item, dict)]
    datasets = [
        dataset
        for model in models
        for dataset in model.get("datasets", [])
        if isinstance(dataset, dict)
    ]
    return {
        "datasets": len(datasets),
        "fields": sum(len(dataset.get("fields", [])) for dataset in datasets),
        "relationships": sum(len(model.get("relationships", [])) for model in models),
        "metrics": sum(len(model.get("metrics", [])) for model in models),
        "unsupported": 0,
    }


def convert_semantic(request: dict[str, Any]) -> dict[str, Any]:
    source = Path(require_string(request, "source_path")).resolve()
    requested_type = str(request.get("source_type", "auto")).casefold()
    if requested_type not in SUPPORTED_SOURCE_TYPES:
        raise ContractError(
            f"source_type must be one of: {', '.join(sorted(SUPPORTED_SOURCE_TYPES))}"
        )
    source_type = detect_source_type(source) if requested_type == "auto" else requested_type
    output_root = _generated_root(request)
    output_root.mkdir(parents=True, exist_ok=True)

    issues: list[dict[str, Any]] = []
    if source_type == "osi":
        document = load_document(source)
        model = document.get("semantic_model", [{}])[0]
        model_name = str(request.get("model_name") or model.get("name") or source.stem)
        source_snapshot = hashlib.sha256(source.read_bytes()).hexdigest()
        ir_summary = _document_summary(document)
        ir: dict[str, Any] | None = None
    else:
        ir = _load_ir(request, source_type)
        document, issues = build_osi_from_ir(ir, request.get("model_name"))
        model_name = str(document["semantic_model"][0]["name"])
        source_snapshot = str(ir.get("snapshot_sha256") or "unknown")
        ir_summary = {
            "datasets": len(ir.get("datasets", [])),
            "fields": sum(len(item.get("fields", [])) for item in ir.get("datasets", [])),
            "relationships": len(ir.get("relationships", [])),
            "metrics": len(ir.get("metrics", [])),
            "unsupported": len(ir.get("unsupported", [])),
        }

    validation = validate_osi_document(document)
    for error in validation["official_errors"]:
        issues.append(
            {
                "severity": "blocking",
                "code": "OSI_SCHEMA_ERROR",
                "element": "document",
                "message": error,
            }
        )
    existing_issues = {(str(item.get("code")), str(item.get("element"))) for item in issues}
    for issue in validation["readiness_issues"]:
        key = (str(issue.get("code")), str(issue.get("element")))
        if key not in existing_issues:
            issues.append(issue)
    yaml_text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    slug = _slug(model_name)
    model_path = output_root / f"{slug}.raw.osi.yaml"
    manifest_path = output_root / f"{slug}.conversion.json"
    model_path.write_text(yaml_text, encoding="utf-8")

    promoted_path = ROOT / "semantic/models" / f"{slug}.yaml"
    previous_document = (
        load_document(promoted_path) if promoted_path.is_file() else {"semantic_model": []}
    )
    refresh = {
        "status": "refresh" if promoted_path.is_file() else "new_model",
        "previous_model_path": str(promoted_path.relative_to(ROOT)),
        **semantic_changes(previous_document, document),
    }

    state_counts = _translation_counts(ir)
    blockers = sum(issue.get("severity") == "blocking" for issue in issues)
    manifest = {
        "request_id": str(request.get("request_id", "unknown")),
        "status": "review_required",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "type": source_type,
            "path": str(source),
            "snapshot_sha256": source_snapshot,
        },
        "osi": {
            "specification": "Apache Ossie (formerly Open Semantic Interchange)",
            "version": OSI_VERSION,
            "schema_source": UPSTREAM_SCHEMA,
            "submodule_commit": EXPECTED_OSSIE_COMMIT,
            "schema_path": str(SCHEMA.relative_to(ROOT)),
            "schema_sha256": schema_sha256(),
            "raw_model_path": str(model_path.relative_to(ROOT)),
            "raw_model_sha256": _sha256_text(yaml_text),
            "schema_valid": validation["schema_valid"],
            "official_valid": validation["official_valid"],
            "analysis_ready_before_review": validation["analysis_ready"],
        },
        "summary": ir_summary,
        "translation_states": state_counts,
        "refresh": refresh,
        "issues": issues,
        "review_checklist": [
            "Resolve every blocking issue and physical source placeholder.",
            "Review source expressions and metadata retained in COMMON/vendor extensions.",
            "Verify primary keys and relationship many-to-one direction.",
            "Create an audited review patch with evidence, confidence, and assumptions.",
            "Apply the patch deterministically; clean reviewed models promote automatically.",
        ],
        "review": {"required": True, "patch_path": None, "final_model_path": None},
        "warehouse_verification": {"status": "not_requested"},
    }
    write_json_atomic(manifest_path, manifest)
    return envelope(
        request,
        "success" if validation["official_valid"] else "invalid",
        source_type=source_type,
        model_path=str(model_path),
        manifest_path=str(manifest_path),
        raw_model_path=str(model_path),
        schema_valid=validation["schema_valid"],
        official_valid=validation["official_valid"],
        issue_count=len(issues),
        blocking_issue_count=blockers,
        summary=ir_summary,
        refresh=refresh,
        warnings=[str(issue["message"]) for issue in issues],
    )
