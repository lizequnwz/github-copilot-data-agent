from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from data_agent.bi.extract import extract_generic_ir, extract_powerbi_ir, extract_tableau_ir
from data_agent.io import ContractError, envelope, require_string, write_json_atomic
from data_agent.semantic.ingestion import OSI_VERSION, build_osi_from_ir
from data_agent.semantic.models import load_document, validate_document

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "semantic/schemas/osi-0.2.0.dev0.schema.json"
UPSTREAM_SCHEMA = "https://github.com/apache/ossie/blob/main/core-spec/osi-schema.json"
SUPPORTED_SOURCE_TYPES = {"auto", "powerbi", "tableau", "generic", "semantic-ir", "osi"}


def detect_source_type(path: Path) -> str:
    if path.is_dir() and any(path.rglob("*.tmdl")):
        return "powerbi"
    if path.is_file() and path.suffix.lower() == ".twb":
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
        "could not detect semantic source; use a PBIP/TMDL directory, .twb, or JSON/YAML file"
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_") or "candidate_model"


def _candidate_root(request: dict[str, Any]) -> Path:
    configured = Path(str(request.get("output_dir", "semantic/candidates")))
    root = (ROOT / configured).resolve() if not configured.is_absolute() else configured.resolve()
    candidates = (ROOT / "semantic/candidates").resolve()
    if root != candidates and candidates not in root.parents:
        raise ContractError("output_dir must be semantic/candidates or a subdirectory")
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


def convert_semantic(request: dict[str, Any]) -> dict[str, Any]:
    source = Path(require_string(request, "source_path")).resolve()
    requested_type = str(request.get("source_type", "auto")).casefold()
    if requested_type not in SUPPORTED_SOURCE_TYPES:
        raise ContractError(
            f"source_type must be one of: {', '.join(sorted(SUPPORTED_SOURCE_TYPES))}"
        )
    source_type = detect_source_type(source) if requested_type == "auto" else requested_type
    output_root = _candidate_root(request)
    output_root.mkdir(parents=True, exist_ok=True)

    issues: list[dict[str, Any]] = []
    if source_type == "osi":
        document = load_document(source)
        model = document.get("semantic_model", [{}])[0]
        model_name = str(request.get("model_name") or model.get("name") or source.stem)
        source_snapshot = hashlib.sha256(source.read_bytes()).hexdigest()
        ir_summary = None
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

    schema_errors = validate_document(document, SCHEMA)
    for error in schema_errors:
        issues.append(
            {
                "severity": "blocking",
                "code": "OSI_SCHEMA_ERROR",
                "element": "document",
                "message": error,
            }
        )
    yaml_text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    slug = _slug(model_name)
    model_path = output_root / f"{slug}.osi.yaml"
    manifest_path = output_root / f"{slug}.conversion.json"
    model_path.write_text(yaml_text, encoding="utf-8")

    state_counts = _translation_counts(ir)
    blockers = sum(issue.get("severity") == "blocking" for issue in issues)
    manifest = {
        "request_id": str(request.get("request_id", "unknown")),
        "status": "review_required" if blockers or issues else "ready_for_review",
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
            "vendored_schema": str(SCHEMA.relative_to(ROOT)),
            "model_path": str(model_path.relative_to(ROOT)),
            "model_sha256": _sha256_text(yaml_text),
            "schema_valid": not schema_errors,
        },
        "summary": ir_summary,
        "translation_states": state_counts,
        "issues": issues,
        "review_checklist": [
            "Resolve every blocking issue and physical source placeholder.",
            "Review vendor expressions retained in ENTERPRISE_DATA_AGENT extensions.",
            "Verify primary keys and relationship many-to-one direction.",
            "Compile representative metrics and compare them with the source BI model.",
            "Move the model to semantic/certified only after human review.",
        ],
    }
    write_json_atomic(manifest_path, manifest)
    return envelope(
        request,
        "success" if not schema_errors else "invalid",
        source_type=source_type,
        candidate_path=str(model_path),
        manifest_path=str(manifest_path),
        schema_valid=not schema_errors,
        issue_count=len(issues),
        blocking_issue_count=blockers,
        summary=ir_summary,
        warnings=[str(issue["message"]) for issue in issues],
    )
