from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from data_agent.io import ContractError, envelope, require_string, write_json_atomic
from data_agent.semantic.models import load_document
from data_agent.semantic.ossie import ROOT, validate_osi_document

PATCH_VERSION = "1.0"
_OPS = {"add", "replace", "remove"}
_CONFIDENCE = {"high", "medium", "low"}
_LOGIC_SEGMENTS = {
    "name",
    "source",
    "primary_key",
    "unique_keys",
    "relationships",
    "metrics",
    "fields",
    "expression",
    "dimension",
    "from",
    "to",
    "from_columns",
    "to_columns",
}
_STRONG_EVIDENCE = {"source_metadata", "snowflake_metadata", "user", "official_spec"}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def review_semantic(request: dict[str, Any]) -> dict[str, Any]:
    raw_path = Path(require_string(request, "raw_model_path")).resolve()
    patch_path = Path(require_string(request, "patch_path")).resolve()
    manifest_path = Path(str(request.get("manifest_path") or _manifest_for_raw(raw_path))).resolve()
    raw_text = raw_path.read_text(encoding="utf-8")
    raw_sha = sha256_text(raw_text)
    raw_document = load_document(raw_path)
    patch = _load_patch(patch_path)
    validate_patch_document(patch, raw_sha)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ContractError("conversion manifest must contain a JSON object")
    recorded_sha = manifest.get("osi", {}).get("raw_model_sha256")
    if recorded_sha != raw_sha:
        raise ContractError("conversion manifest raw model hash does not match the raw model")

    reviewed = copy.deepcopy(raw_document)
    original_provenance = _conversion_provenance(reviewed)
    operation_audit: list[dict[str, Any]] = []
    unresolved_assumptions: list[str] = []
    for index, operation in enumerate(patch["operations"]):
        before = _pointer_get(reviewed, operation["path"], missing_ok=True)
        _apply_operation(reviewed, operation)
        after = _pointer_get(reviewed, operation["path"], missing_ok=True)
        logic_change = _is_logic_change(operation["path"]) or _resolves_translation_issue(
            before, after
        )
        assumptions = [str(item) for item in operation.get("assumptions", [])]
        confidence = str(operation["confidence"])
        evidence_types = _evidence_types(operation["evidence"])
        if assumptions:
            unresolved_assumptions.extend(assumptions)
        if confidence == "low":
            unresolved_assumptions.append(f"operation {index} has low confidence")
        if logic_change and (
            confidence != "high" or not evidence_types.intersection(_STRONG_EVIDENCE)
        ):
            unresolved_assumptions.append(
                f"operation {index} changes semantic logic without high-confidence direct evidence"
            )
        operation_audit.append(
            {
                **operation,
                "logic_change": logic_change,
                "before": before,
                "after": after,
            }
        )

    if _conversion_provenance(reviewed) != original_provenance:
        raise ContractError("review patches cannot change converter provenance")

    validation = validate_osi_document(reviewed)
    if validation["official_errors"]:
        joined = "; ".join(validation["official_errors"][:5])
        raise ContractError(f"reviewed model failed official Ossie validation: {joined}")

    verification = {"status": "not_requested"}
    if request.get("verify_snowflake") is True:
        from data_agent.semantic.verification import verify_semantic_model

        verification = verify_semantic_model({**request, "document": reviewed})

    model_name = str(reviewed["semantic_model"][0]["name"])
    competency_path = ROOT / "semantic/tests" / f"{_slug(model_name)}.yaml"
    competency: dict[str, Any] = {"status": "not_configured"}
    if competency_path.is_file():
        from data_agent.semantic.competency import test_document

        competency_result = test_document(reviewed, competency_path)
        competency = {
            "status": "passed" if competency_result["passed"] else "failed",
            **competency_result,
        }

    clean = (
        validation["analysis_ready"]
        and not unresolved_assumptions
        and verification.get("status") in {"not_requested", "passed"}
        and competency.get("status") in {"not_configured", "passed"}
    )
    final_path = _final_for_raw(raw_path)
    final_text = yaml.safe_dump(reviewed, sort_keys=False, allow_unicode=True)
    final_path.write_text(final_text, encoding="utf-8")
    final_sha = sha256_text(final_text)

    promoted_path: Path | None = None
    if clean and request.get("promote_if_clean", True) is True:
        promoted_path = ROOT / "semantic/models" / f"{_slug(model_name)}.yaml"
        promoted_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = promoted_path.with_suffix(".yaml.tmp")
        temporary.write_text(final_text, encoding="utf-8")
        temporary.replace(promoted_path)

    previous_issues = manifest.get("issues", [])
    if "conversion_issues" not in manifest:
        manifest["conversion_issues"] = previous_issues
    manifest["issues"] = validation["readiness_issues"]
    manifest["status"] = (
        "promoted" if promoted_path else "reviewed_clean" if clean else "reviewed_with_assumptions"
    )
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    manifest["warehouse_verification"] = verification
    manifest["competency_tests"] = competency
    manifest["review"] = {
        "required": True,
        "patch_path": _relative_or_absolute(patch_path),
        "patch_sha256": hashlib.sha256(patch_path.read_bytes()).hexdigest(),
        "raw_model_sha256": raw_sha,
        "final_model_path": _relative_or_absolute(final_path),
        "final_model_sha256": final_sha,
        "operations": operation_audit,
        "unresolved_assumptions": sorted(set(unresolved_assumptions)),
        "validation": validation,
        "clean": clean,
    }
    manifest["promotion"] = {
        "eligible": clean,
        "promoted": promoted_path is not None,
        "model_path": _relative_or_absolute(promoted_path) if promoted_path else None,
    }
    write_json_atomic(manifest_path, manifest)
    return envelope(
        request,
        "success",
        final_model_path=str(final_path),
        final_model_sha256=final_sha,
        manifest_path=str(manifest_path),
        clean=clean,
        promoted=promoted_path is not None,
        promoted_model_path=str(promoted_path) if promoted_path else None,
        unresolved_assumptions=sorted(set(unresolved_assumptions)),
        official_valid=validation["official_valid"],
        analysis_ready=validation["analysis_ready"],
        warehouse_verification=verification,
        competency_tests=competency,
        warnings=[issue["message"] for issue in validation["readiness_issues"]],
    )


def preview_review_patch(
    raw_document: dict[str, Any], patch: dict[str, Any], raw_sha: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply an audited patch in memory and validate it without writing artifacts."""

    validate_patch_document(patch, raw_sha)
    reviewed = copy.deepcopy(raw_document)
    original_provenance = _conversion_provenance(reviewed)
    for operation in patch["operations"]:
        _apply_operation(reviewed, operation)
    if _conversion_provenance(reviewed) != original_provenance:
        raise ContractError("review patches cannot change converter provenance")
    return reviewed, validate_osi_document(reviewed)


def validate_patch_document(patch: dict[str, Any], raw_sha: str) -> None:
    """Validate a complete audited patch before it is persisted or applied."""
    if patch.get("patch_version") != PATCH_VERSION:
        raise ContractError(f"review patch_version must be {PATCH_VERSION}")
    if patch.get("base_model_sha256") != raw_sha:
        raise ContractError(
            "review patch base_model_sha256 does not match the deterministic raw model"
        )
    operations = patch.get("operations")
    if not isinstance(operations, list):
        raise ContractError("review patch operations must be an array")
    for index, operation in enumerate(operations):
        _validate_operation(operation, index, raw_sha)


def _load_patch(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"review patch must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("review patch must contain a JSON object")
    if value.get("patch_version") != PATCH_VERSION:
        raise ContractError(f"review patch_version must be {PATCH_VERSION}")
    if not isinstance(value.get("base_model_sha256"), str):
        raise ContractError("review patch requires base_model_sha256")
    if not isinstance(value.get("operations"), list):
        raise ContractError("review patch operations must be an array")
    return value


def _validate_operation(operation: Any, index: int, raw_sha: str) -> None:
    if not isinstance(operation, dict):
        raise ContractError(f"review operation {index} must be an object")
    if operation.get("op") not in _OPS:
        raise ContractError(f"review operation {index} op must be add, replace, or remove")
    if operation.get("base_model_sha256") != raw_sha:
        raise ContractError(
            f"review operation {index} base_model_sha256 must match the deterministic raw model"
        )
    path = operation.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ContractError(f"review operation {index} path must be a JSON Pointer")
    if path == "/version" or path.startswith("/version/"):
        raise ContractError("review patches cannot change the Ossie version")
    if operation["op"] != "remove" and "value" not in operation:
        raise ContractError(f"review operation {index} requires value")
    if not isinstance(operation.get("rationale"), str) or not operation["rationale"].strip():
        raise ContractError(f"review operation {index} requires rationale")
    if not isinstance(operation.get("evidence"), list) or not operation["evidence"]:
        raise ContractError(f"review operation {index} requires evidence")
    for evidence_index, evidence in enumerate(operation["evidence"]):
        if not isinstance(evidence, dict):
            raise ContractError(
                f"review operation {index} evidence {evidence_index} must be an object"
            )
        if not isinstance(evidence.get("type"), str) or not evidence["type"].strip():
            raise ContractError(f"review operation {index} evidence {evidence_index} requires type")
        if not isinstance(evidence.get("reference"), str) or not evidence["reference"].strip():
            raise ContractError(
                f"review operation {index} evidence {evidence_index} requires reference"
            )
    if operation.get("confidence") not in _CONFIDENCE:
        raise ContractError(f"review operation {index} confidence is invalid")
    if not isinstance(operation.get("assumptions"), list):
        raise ContractError(f"review operation {index} assumptions must be an array")


def _apply_operation(document: dict[str, Any], operation: dict[str, Any]) -> None:
    parts = _pointer_parts(operation["path"])
    if not parts:
        raise ContractError("review operations cannot replace the document root")
    parent = _walk(document, parts[:-1])
    key = parts[-1]
    op = operation["op"]
    if isinstance(parent, list):
        if key == "-" and op == "add":
            parent.append(copy.deepcopy(operation["value"]))
            return
        try:
            index = int(key)
        except ValueError as exc:
            raise ContractError(f"invalid array index in review path: {key}") from exc
        if op == "add":
            if index < 0 or index > len(parent):
                raise ContractError(f"review add index out of range: {index}")
            parent.insert(index, copy.deepcopy(operation["value"]))
        elif op == "replace":
            if index < 0 or index >= len(parent):
                raise ContractError(f"review replace index out of range: {index}")
            parent[index] = copy.deepcopy(operation["value"])
        else:
            if index < 0 or index >= len(parent):
                raise ContractError(f"review remove index out of range: {index}")
            parent.pop(index)
        return
    if not isinstance(parent, dict):
        raise ContractError("review path parent must be an object or array")
    if op == "add":
        parent[key] = copy.deepcopy(operation["value"])
    elif op == "replace":
        if key not in parent:
            raise ContractError(f"review replace target does not exist: {operation['path']}")
        parent[key] = copy.deepcopy(operation["value"])
    else:
        if key not in parent:
            raise ContractError(f"review remove target does not exist: {operation['path']}")
        del parent[key]


def _pointer_get(document: dict[str, Any], path: str, *, missing_ok: bool) -> Any:
    try:
        return copy.deepcopy(_walk(document, _pointer_parts(path)))
    except ContractError:
        if missing_ok:
            return None
        raise


def _walk(value: Any, parts: list[str]) -> Any:
    current = value
    for part in parts:
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise ContractError(f"review path does not exist at array segment {part}") from exc
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise ContractError(f"review path does not exist at segment {part}")
    return current


def _pointer_parts(path: str) -> list[str]:
    if not path.startswith("/"):
        raise ContractError("review path must start with /")
    return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]


def _conversion_provenance(document: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for model in document.get("semantic_model", []):
        if not isinstance(model, dict):
            continue
        for extension in model.get("custom_extensions", []):
            if not isinstance(extension, dict) or not isinstance(extension.get("data"), str):
                continue
            try:
                parsed = json.loads(extension["data"])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and parsed.get("kind") == "conversion_provenance":
                result.append(json.dumps(extension, sort_keys=True))
    return result


def _is_logic_change(path: str) -> bool:
    parts = set(_pointer_parts(path))
    if parts.intersection({"description", "ai_context", "label", "custom_extensions"}):
        return False
    return bool(parts.intersection(_LOGIC_SEGMENTS))


def _evidence_types(values: list[Any]) -> set[str]:
    result: set[str] = set()
    for value in values:
        if isinstance(value, dict) and isinstance(value.get("type"), str):
            result.add(value["type"])
    return result


def _resolves_translation_issue(before: Any, after: Any) -> bool:
    unresolved = {
        "equivalent-with-assumptions",
        "partial",
        "unsupported",
        "requires-human-review",
    }

    def statuses(value: Any) -> list[str]:
        found: list[str] = []
        if isinstance(value, dict):
            status = value.get("translation_status")
            if isinstance(status, str):
                found.append(status)
            for child in value.values():
                found.extend(statuses(child))
        elif isinstance(value, list):
            for child in value:
                found.extend(statuses(child))
        elif isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return found
            found.extend(statuses(parsed))
        return found

    before_unresolved = sum(status in unresolved for status in statuses(before))
    after_unresolved = sum(status in unresolved for status in statuses(after))
    return before_unresolved > after_unresolved


def _manifest_for_raw(raw_path: Path) -> Path:
    name = raw_path.name.removesuffix(".raw.osi.yaml")
    return raw_path.with_name(f"{name}.conversion.json")


def _final_for_raw(raw_path: Path) -> Path:
    name = raw_path.name.removesuffix(".raw.osi.yaml")
    return raw_path.with_name(f"{name}.osi.yaml")


def _relative_or_absolute(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def _slug(value: str) -> str:
    import re as regex

    return regex.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_") or "model"
