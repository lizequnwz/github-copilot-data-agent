from __future__ import annotations

import copy
import html
import json
import re
import secrets
import threading
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from data_agent.io import ContractError, write_json_atomic
from data_agent.semantic.models import load_document
from data_agent.semantic.compiler import compile_plan
from data_agent.semantic.review import (
    preview_review_patch,
    review_semantic,
    sha256_text,
    validate_patch_document,
)

ROOT = Path(__file__).resolve().parents[2]
GENERATED_ROOT = (ROOT / "semantic/generated").resolve()
DECISION_VERSION = "1.0"
MAX_REQUEST_BYTES = 1_000_000
_DECISION_KEYS = {"decision_version", "base_model_sha256", "operations"}
_OPERATION_KEYS = {
    "op",
    "path",
    "value",
    "rationale",
    "evidence",
    "confidence",
    "assumptions",
    "intent",
}


@dataclass(frozen=True)
class ReviewPaths:
    raw: Path
    manifest: Path
    draft: Path
    html: Path


def review_paths(raw_path: str | Path, manifest_path: str | Path) -> ReviewPaths:
    raw = _restricted_generated_path(raw_path)
    manifest = _restricted_generated_path(manifest_path)
    stem = raw.name.removesuffix(".raw.osi.yaml")
    return ReviewPaths(
        raw=raw,
        manifest=manifest,
        draft=raw.with_name(f"{stem}.review.draft.json"),
        html=raw.with_name(f"{stem}.review.html"),
    )


def default_decisions(raw_path: str | Path) -> dict[str, Any]:
    raw = _restricted_generated_path(raw_path)
    raw_sha = sha256_text(raw.read_text(encoding="utf-8"))
    return {
        "decision_version": DECISION_VERSION,
        "base_model_sha256": raw_sha,
        "operations": [],
    }


def load_decisions(path: str | Path, raw_path: str | Path) -> dict[str, Any]:
    decision_path = Path(path).resolve()
    if decision_path.stat().st_size > MAX_REQUEST_BYTES:
        raise ContractError(f"review decisions exceed {MAX_REQUEST_BYTES} bytes")
    try:
        value = json.loads(decision_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"review decisions must be valid JSON: {exc}") from exc
    validate_decisions(value, raw_path)
    return cast(dict[str, Any], value)


def validate_decisions(value: Any, raw_path: str | Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("review decisions must contain a JSON object")
    unknown = set(value) - _DECISION_KEYS
    if unknown:
        raise ContractError(f"unknown review decision keys: {', '.join(sorted(unknown))}")
    if value.get("decision_version") != DECISION_VERSION:
        raise ContractError(f"decision_version must be {DECISION_VERSION}")
    raw = _restricted_generated_path(raw_path)
    raw_sha = sha256_text(raw.read_text(encoding="utf-8"))
    if value.get("base_model_sha256") != raw_sha:
        raise ContractError("review decisions are stale for the deterministic raw model")
    operations = value.get("operations")
    if not isinstance(operations, list):
        raise ContractError("review decision operations must be an array")
    patch_operations: list[dict[str, Any]] = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise ContractError(f"review decision {index} must be an object")
        extra = set(operation) - _OPERATION_KEYS
        if extra:
            raise ContractError(
                f"unknown keys in review decision {index}: {', '.join(sorted(extra))}"
            )
        normalized = copy.deepcopy(operation)
        normalized["base_model_sha256"] = raw_sha
        normalized.pop("intent", None)
        patch_operations.append(normalized)
    validate_patch_document(
        {
            "patch_version": "1.0",
            "base_model_sha256": raw_sha,
            "operations": patch_operations,
        },
        raw_sha,
    )
    return value


def compile_decisions(value: Any, paths: ReviewPaths) -> dict[str, Any]:
    decisions = validate_decisions(value, paths.raw)
    raw_document = load_document(paths.raw)
    raw_sha = str(decisions["base_model_sha256"])
    operations = _coordinate_renames(raw_document, decisions["operations"], raw_sha)
    patch = {
        "patch_version": "1.0",
        "base_model_sha256": raw_sha,
        "operations": operations,
    }
    validate_patch_document(patch, raw_sha)
    return patch


def save_draft(value: Any, paths: ReviewPaths) -> Path:
    decisions = validate_decisions(value, paths.raw)
    write_json_atomic(paths.draft, decisions)
    return paths.draft


def preview_decisions(
    value: Any, paths: ReviewPaths, *, metric_name: str | None = None
) -> dict[str, Any]:
    """Validate candidate review decisions without persisting any review artifact."""

    decisions = validate_decisions(value, paths.raw)
    raw_document = load_document(paths.raw)
    raw_sha = str(decisions["base_model_sha256"])
    patch = {
        "patch_version": "1.0",
        "base_model_sha256": raw_sha,
        "operations": _coordinate_renames(raw_document, decisions["operations"], raw_sha),
    }
    reviewed, validation = preview_review_patch(raw_document, patch, raw_sha)
    compilation: dict[str, Any] = {"status": "not_requested"}
    if metric_name:
        model = reviewed.get("semantic_model", [{}])[0]
        model_name = model.get("name") if isinstance(model, dict) else None
        compiled = compile_plan(
            reviewed,
            {
                "semantic_model": model_name,
                "metric_ids": [metric_name],
                "dimensions": [],
                "max_rows": 1,
            },
        )
        compilation = {
            "status": "success",
            "sql": compiled["sql"],
        }
    return {"validation": validation, "compilation": compilation}


def build_review_state(
    paths: ReviewPaths,
    *,
    decisions: dict[str, Any] | None = None,
    promotion_enabled: bool = True,
    verify_snowflake: bool = False,
) -> dict[str, Any]:
    raw_document = load_document(paths.raw)
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ContractError("conversion manifest must contain a JSON object")
    active = decisions or _latest_decisions(paths)
    validate_decisions(active, paths.raw)
    models = raw_document.get("semantic_model", [])
    model = models[0] if isinstance(models, list) and models else {}
    if not isinstance(model, dict):
        raise ContractError("raw model does not contain a semantic model object")
    current_issues = manifest.get("issues", [])
    original_issues = manifest.get("conversion_issues", current_issues)
    current_count = len(current_issues) if isinstance(current_issues, list) else 0
    total_count = len(original_issues) if isinstance(original_issues, list) else current_count
    resolved_count = max(total_count - current_count, 0)
    source = manifest.get("source", {})
    review = manifest.get("review", {})
    promotion = manifest.get("promotion", {})
    return {
        "model_name": str(model.get("name", "Semantic model")),
        "source": source if isinstance(source, dict) else {},
        "status": str(manifest.get("status", "review_required")),
        "progress": {
            "resolved": resolved_count,
            "total": total_count,
            "remaining": current_count,
            "pending_edits": len(active["operations"]),
        },
        "issues": current_issues if isinstance(current_issues, list) else [],
        "objects": _editable_objects(model),
        "decisions": active,
        "artifacts": {
            "raw": _relative(paths.raw),
            "manifest": _relative(paths.manifest),
            "draft": _relative(paths.draft),
            "html": _relative(paths.html),
        },
        "review_result": review if isinstance(review, dict) else {},
        "promotion": promotion if isinstance(promotion, dict) else {},
        "refresh": manifest.get("refresh", {}),
        "promotion_enabled": promotion_enabled,
        "verify_snowflake": verify_snowflake,
    }


def write_static_review(
    paths: ReviewPaths, *, promotion_enabled: bool = True, verify_snowflake: bool = False
) -> Path:
    state = build_review_state(
        paths,
        promotion_enabled=promotion_enabled,
        verify_snowflake=verify_snowflake,
    )
    paths.html.write_text(render_review_html(state), encoding="utf-8")
    return paths.html


class ReviewApplication:
    def __init__(
        self,
        paths: ReviewPaths,
        *,
        request_id: str,
        verify_snowflake: bool,
        config_path: str,
        configuration_confirmed: bool,
        promote_if_clean: bool,
    ) -> None:
        self.paths = paths
        self.request_id = request_id
        self.verify_snowflake = verify_snowflake
        self.config_path = config_path
        self.configuration_confirmed = configuration_confirmed
        self.promote_if_clean = promote_if_clean
        self.token = secrets.token_urlsafe(32)
        self.origin = ""
        self.finished = threading.Event()

    def state(self) -> dict[str, Any]:
        return build_review_state(
            self.paths,
            promotion_enabled=self.promote_if_clean,
            verify_snowflake=self.verify_snowflake,
        )

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        decisions = payload.get("decisions")
        if payload.get("confirm_promote") is not True and self.promote_if_clean:
            raise ContractError("confirm the promotion destination before applying decisions")
        patch = compile_decisions(decisions, self.paths)
        save_draft(decisions, self.paths)
        result = review_semantic(
            {
                "request_id": self.request_id,
                "raw_model_path": str(self.paths.raw),
                "manifest_path": str(self.paths.manifest),
                "patch": patch,
                "verify_snowflake": self.verify_snowflake,
                "config_path": self.config_path,
                "configuration_confirmed": self.configuration_confirmed,
                "promote_if_clean": self.promote_if_clean,
            }
        )
        write_static_review(
            self.paths,
            promotion_enabled=self.promote_if_clean,
            verify_snowflake=self.verify_snowflake,
        )
        return {"result": result, "state": self.state()}


def serve_review(
    paths: ReviewPaths,
    *,
    port: int,
    open_browser: bool,
    request_id: str,
    verify_snowflake: bool,
    config_path: str,
    configuration_confirmed: bool,
    promote_if_clean: bool,
) -> dict[str, Any]:
    if port < 0 or port > 65535:
        raise ContractError("review port must be between 0 and 65535")
    app = ReviewApplication(
        paths,
        request_id=request_id,
        verify_snowflake=verify_snowflake,
        config_path=config_path,
        configuration_confirmed=configuration_confirmed,
        promote_if_clean=promote_if_clean,
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler_for(app))
    actual_port = int(server.server_address[1])
    app.origin = f"http://127.0.0.1:{actual_port}"
    url = f"{app.origin}/?token={app.token}"
    write_static_review(
        paths,
        promotion_enabled=promote_if_clean,
        verify_snowflake=verify_snowflake,
    )
    print(f"Review workspace: {url}")
    print(f"Static fallback: {paths.html}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return {"url": url, "finished": app.finished.is_set(), "state": app.state()}


def render_review_html(state: dict[str, Any], *, token: str = "") -> str:
    from data_agent.semantic.review_ui import render_review_html_document

    return render_review_html_document(
        state,
        token=token,
        refresh_html=_refresh_summary_html(state.get("refresh")),
    )


def _refresh_summary_html(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    summary = value.get("summary", {})
    changes = value.get("changes", [])
    if not isinstance(summary, dict) or not isinstance(changes, list):
        return ""
    status = "Existing promoted model" if value.get("status") == "refresh" else "New model"
    items = []
    for change in changes:
        if not isinstance(change, dict):
            continue
        label = " ".join(
            [
                str(change.get("impact", "metadata")),
                str(change.get("kind", "object")),
                str(change.get("object", "unknown")),
                str(change.get("change_type", "changed")),
            ]
        )
        items.append(f"<li>{html.escape(label)}</li>")
    details = ""
    if items:
        details = (
            f"<details><summary>Review {len(items)} object-level changes</summary>"
            f"<ul>{''.join(items)}</ul></details>"
        )
    return (
        '<section class="panel" aria-labelledby="refresh-heading">'
        '<div class="eyebrow">Refresh impact</div>'
        '<h2 id="refresh-heading">Changes from the promoted model</h2>'
        f"<p>{html.escape(status)}: {int(summary.get('added', 0))} added, "
        f"{int(summary.get('removed', 0))} removed, "
        f"{int(summary.get('changed', 0))} changed.</p>"
        f"{details}</section>"
    )


def _handler_for(app: ReviewApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "SemanticReview/1.0"

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            supplied = parse_qs(parsed.query).get("token", [""])[0]
            if parsed.path == "/" and secrets.compare_digest(supplied, app.token):
                self._html(render_review_html(app.state(), token=app.token))
                return
            if parsed.path == "/api/state":
                if not self._authorized(require_origin=False):
                    return
                self._json(HTTPStatus.OK, app.state())
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized(require_origin=True):
                return
            try:
                payload = self._body()
                if self.path == "/api/draft":
                    save_draft(payload.get("decisions"), app.paths)
                    self._json(HTTPStatus.OK, {"status": "saved"})
                elif self.path == "/api/preview":
                    metric_name = payload.get("metric_name")
                    if metric_name is not None and not isinstance(metric_name, str):
                        raise ContractError("metric_name must be a string")
                    self._json(
                        HTTPStatus.OK,
                        preview_decisions(
                            payload.get("decisions"), app.paths, metric_name=metric_name
                        ),
                    )
                elif self.path == "/api/apply":
                    self._json(HTTPStatus.OK, app.apply(payload))
                elif self.path == "/api/finish":
                    app.finished.set()
                    self._json(HTTPStatus.OK, {"status": "finished"})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except (ContractError, OSError, ValueError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def _authorized(self, *, require_origin: bool) -> bool:
            token = self.headers.get("X-Review-Token", "")
            if not secrets.compare_digest(token, app.token):
                self._json(HTTPStatus.FORBIDDEN, {"error": "invalid review session token"})
                return False
            if require_origin and self.headers.get("Origin") != app.origin:
                self._json(HTTPStatus.FORBIDDEN, {"error": "invalid request origin"})
                return False
            return True

        def _body(self) -> dict[str, Any]:
            if self.headers.get_content_type() != "application/json":
                raise ContractError("requests must use application/json")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ContractError("invalid Content-Length") from exc
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ContractError(f"request body must be 1 to {MAX_REQUEST_BYTES} bytes")
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, dict):
                raise ContractError("request body must be a JSON object")
            return value

        def _headers(self, content_type: str, length: int) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
            )

        def _json(self, status: HTTPStatus, value: Any) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._headers("application/json; charset=utf-8", len(body))
            self.end_headers()
            self.wfile.write(body)

        def _html(self, value: str) -> None:
            body = value.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self._headers("text/html; charset=utf-8", len(body))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _editable_objects(model: dict[str, Any]) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    model_path = "/semantic_model/0"
    datasets: Any = [item for item in model.get("datasets", []) if isinstance(item, dict)]
    dataset_names = [str(item.get("name")) for item in datasets]
    relationships = [item for item in model.get("relationships", []) if isinstance(item, dict)]
    fields_by_dataset = {
        str(item.get("name")): _physical_reference_options(item, relationships) for item in datasets
    }
    objects.append(
        _object(
            "ai_context",
            "model",
            str(model.get("name", "Model context")),
            "Model-level descriptions, synonyms, examples, and AI guidance",
            model_path,
            model,
            ["name", "description", "ai_context"],
            protected=True,
        )
    )
    if isinstance(datasets, list):
        for dataset_index, dataset in enumerate(datasets):
            if not isinstance(dataset, dict):
                continue
            dataset_path = f"{model_path}/datasets/{dataset_index}"
            dataset_name = str(dataset.get("name", f"Dataset {dataset_index + 1}"))
            objects.append(
                _object(
                    "datasets",
                    f"dataset-{dataset_index}",
                    dataset_name,
                    str(dataset.get("source", "No physical source")),
                    dataset_path,
                    dataset,
                    [
                        "name",
                        "description",
                        "source",
                        "primary_key",
                        "unique_keys",
                        "ai_context",
                    ],
                    options={
                        "primary_key": fields_by_dataset.get(dataset_name, []),
                        "unique_keys": fields_by_dataset.get(dataset_name, []),
                    },
                )
            )
            fields = dataset.get("fields", [])
            if isinstance(fields, list):
                for field_index, field in enumerate(fields):
                    if not isinstance(field, dict):
                        continue
                    field_path = f"{dataset_path}/fields/{field_index}"
                    objects.append(
                        _object(
                            "fields",
                            f"field-{dataset_index}-{field_index}",
                            str(field.get("name", f"Field {field_index + 1}")),
                            dataset_name,
                            field_path,
                            field,
                            [
                                "name",
                                "description",
                                "expression",
                                "dimension",
                                "ai_context",
                            ],
                        )
                    )
    metrics = model.get("metrics", [])
    if isinstance(metrics, list):
        for index, metric in enumerate(metrics):
            if isinstance(metric, dict):
                objects.append(
                    _object(
                        "metrics",
                        f"metric-{index}",
                        str(metric.get("name", f"Metric {index + 1}")),
                        "Model metric",
                        f"{model_path}/metrics/{index}",
                        metric,
                        ["name", "description", "expression", "ai_context"],
                    )
                )
    for index, relationship in enumerate(relationships):
        context = f"{relationship.get('from', '?')} to {relationship.get('to', '?')}"
        objects.append(
            _object(
                "relationships",
                f"relationship-{index}",
                str(relationship.get("name", f"Relationship {index + 1}")),
                context,
                f"{model_path}/relationships/{index}",
                relationship,
                [
                    "name",
                    "from",
                    "to",
                    "from_columns",
                    "to_columns",
                ],
                options={
                    "from": dataset_names,
                    "to": dataset_names,
                    "from_columns": fields_by_dataset.get(str(relationship.get("from", "")), []),
                    "to_columns": fields_by_dataset.get(str(relationship.get("to", "")), []),
                },
            )
        )
    return objects


def _physical_reference_options(
    dataset: dict[str, Any], relationships: list[dict[str, Any]]
) -> list[str]:
    """Return physical columns suitable for OSI key and relationship references."""

    dataset_name = str(dataset.get("name", ""))
    values: list[str] = []
    for field in dataset.get("fields", []):
        if not isinstance(field, dict):
            continue
        expression = field.get("expression")
        if not isinstance(expression, dict):
            continue
        for dialect in expression.get("dialects", []):
            if not isinstance(dialect, dict):
                continue
            value = dialect.get("expression")
            if not isinstance(value, str):
                continue
            match = re.fullmatch(r"[A-Za-z_]\w*\.([A-Za-z_]\w*)", value.strip())
            if match:
                values.append(match.group(1))
                break

    for key in dataset.get("primary_key", []):
        if isinstance(key, str):
            values.append(key)
    for unique_key in dataset.get("unique_keys", []):
        if isinstance(unique_key, list):
            values.extend(key for key in unique_key if isinstance(key, str))
    for relationship in relationships:
        if relationship.get("from") == dataset_name:
            values.extend(
                key for key in relationship.get("from_columns", []) if isinstance(key, str)
            )
        if relationship.get("to") == dataset_name:
            values.extend(key for key in relationship.get("to_columns", []) if isinstance(key, str))

    return list(dict.fromkeys(values))


def _object(
    section: str,
    identifier: str,
    name: str,
    context: str,
    path: str,
    value: dict[str, Any],
    properties: list[str],
    *,
    protected: bool = False,
    options: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    labels = {
        "ai_context": "AI context",
        "primary_key": "Primary key",
        "unique_keys": "Unique keys",
        "from_columns": "From columns",
        "to_columns": "To columns",
        "custom_extensions": "Source and review metadata",
    }
    result = []
    for key in properties:
        exists = key in value
        current = value.get(key, "" if key in {"name", "description", "source"} else None)
        kind = "text"
        if key == "ai_context":
            kind = "ai_context"
        elif key == "expression":
            kind = "expression"
        elif key == "dimension":
            kind = "dimension"
        elif key in {"primary_key", "from_columns", "to_columns"}:
            kind = "multi_select" if options and key in options else "string_list"
        elif key == "unique_keys":
            kind = "key_selects" if options and key in options else "key_lists"
        elif options and key in options:
            kind = "select"
        result.append(
            {
                "label": labels.get(key, key.replace("_", " ").title()),
                "path": f"{path}/{_escape_pointer(key)}",
                "value": current,
                "exists": exists,
                "kind": kind,
                "options": (options or {}).get(key, []),
                "help": _property_help(key),
            }
        )
    return {
        "section": section,
        "id": identifier,
        "name": name,
        "context": context,
        "path": path,
        "properties": result,
        "protected": protected,
        "translation": _translation_info(value, path),
    }


def _translation_info(value: dict[str, Any], path: str) -> dict[str, Any] | None:
    extensions = value.get("custom_extensions", [])
    if not isinstance(extensions, list):
        return None
    for index, extension in enumerate(extensions):
        if not isinstance(extension, dict) or not isinstance(extension.get("data"), str):
            continue
        try:
            data = json.loads(extension["data"])
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or data.get("kind") not in {
            "source_metadata",
            "unsupported_review",
        }:
            continue
        status = str(data.get("translation_status", "exact"))
        if status in {"exact", "reviewed-unsupported"}:
            return None
        accepted_data = {**data, "translation_status": "exact"}
        unsupported_data = {**data, "translation_status": "reviewed-unsupported"}
        requested_data = {
            **data,
            "review_request": "Additional business or technical evidence is required.",
        }
        return {
            "status": status,
            "source_expression": data.get("source_expression"),
            "can_accept": data.get("kind") == "source_metadata",
            "path": f"{path}/custom_extensions/{index}",
            "accepted_value": {
                **extension,
                "data": json.dumps(accepted_data, sort_keys=True),
            },
            "unsupported_value": {
                **extension,
                "data": json.dumps(unsupported_data, sort_keys=True),
            },
            "requested_value": {
                **extension,
                "data": json.dumps(requested_data, sort_keys=True),
            },
        }
    return None


def _property_help(key: str) -> str:
    return {
        "name": "Stable semantic name used by analysts and downstream references.",
        "description": "Plain-language business meaning, scope, and exclusions.",
        "source": "Qualified physical source or source expression.",
        "primary_key": "Select the physical source columns that form the primary key.",
        "unique_keys": "Select physical source columns for each alternate unique key.",
        "expression": "OSI expression object, including dialect-specific SQL when applicable.",
        "dimension": "OSI dimension metadata such as time or categorical behavior.",
        "ai_context": "Structured synonyms, examples, instructions, and other AI context.",
        "from": "Source dataset semantic name.",
        "to": "Target dataset semantic name.",
        "from_columns": "Select physical foreign-key columns from the many-side dataset.",
        "to_columns": "Select physical primary/unique-key columns from the one-side dataset.",
        "custom_extensions": (
            "Source and review metadata. Preserve unrelated entries; change translation status "
            "only when the supplied evidence fully resolves the source issue."
        ),
    }.get(key, "Review this semantic value against source evidence.")


def _coordinate_renames(
    document: dict[str, Any], operations: list[Any], raw_sha: str
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    explicit_paths = {
        str(item.get("path")) for item in operations if isinstance(item, dict) and item.get("path")
    }
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        normalized = copy.deepcopy(operation)
        intent = normalized.pop("intent", None)
        normalized["base_model_sha256"] = raw_sha
        result.append(normalized)
        if intent != "rename" or normalized.get("op") != "replace":
            continue
        path = str(normalized["path"])
        match = re.fullmatch(r"/semantic_model/0/datasets/(\d+)/name", path)
        if match:
            dataset_index = int(match.group(1))
            model = document["semantic_model"][0]
            old_name = str(model["datasets"][dataset_index]["name"])
            new_name = str(normalized["value"])
            _reject_ambiguous_expression_rewrite(document, old_name, path, explicit_paths)
            for index, relationship in enumerate(model.get("relationships", [])):
                for side in ("from", "to"):
                    if relationship.get(side) == old_name:
                        ref_path = f"/semantic_model/0/relationships/{index}/{side}"
                        if ref_path not in explicit_paths:
                            result.append(_derived_operation(normalized, ref_path, new_name))
            continue
        match = re.fullmatch(r"/semantic_model/0/datasets/(\d+)/fields/(\d+)/name", path)
        if match:
            # Field names are semantic identifiers. OSI keys and relationship columns are
            # physical source-column identifiers, so a semantic rename must not rewrite them.
            continue
    return result


def _derived_operation(source: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    return {
        "base_model_sha256": source["base_model_sha256"],
        "op": "replace",
        "path": path,
        "value": value,
        "rationale": f"Coordinated reference update: {source['rationale']}",
        "evidence": copy.deepcopy(source["evidence"]),
        "confidence": source["confidence"],
        "assumptions": copy.deepcopy(source["assumptions"]),
    }


def _reject_ambiguous_expression_rewrite(
    document: dict[str, Any],
    old_name: str,
    rename_path: str,
    explicit_paths: set[str],
) -> None:
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(old_name)}(?![A-Za-z0-9_])", re.IGNORECASE)

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}/{_escape_pointer(str(key))}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}/{index}")
        elif isinstance(value, str) and "/expression" in path and pattern.search(value):
            if not path.startswith(rename_path.rsplit("/name", 1)[0] + "/expression"):
                expression_path = path.split("/dialects/", 1)[0]
                if expression_path in explicit_paths or path in explicit_paths:
                    return
                raise ContractError(
                    f"rename is ambiguous because expression {path} references {old_name!r}; "
                    "add an explicit reviewed expression correction"
                )

    walk(document, "")


def _latest_decisions(paths: ReviewPaths) -> dict[str, Any]:
    if paths.draft.is_file():
        try:
            return load_decisions(paths.draft, paths.raw)
        except ContractError:
            pass
    return default_decisions(paths.raw)


def _restricted_generated_path(value: str | Path) -> Path:
    path = Path(value).resolve()
    if path != GENERATED_ROOT and GENERATED_ROOT not in path.parents:
        raise ContractError("review artifacts must remain under semantic/generated")
    return path


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")
