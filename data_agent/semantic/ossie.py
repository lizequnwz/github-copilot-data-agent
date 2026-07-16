from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OSSIE_ROOT = ROOT / "ossie-main"
SCHEMA = OSSIE_ROOT / "core-spec/osi-schema.json"
VALIDATOR = OSSIE_ROOT / "validation/validate.py"
EXPECTED_OSSIE_COMMIT = "5c8a2a5f7e09e046e2055e5759e7df4a928b7a88"
EXPECTED_SCHEMA_SHA256 = "273131e029ff3c1c2823214f265d435a4f36f6e0486f645c614e257505926884"

_EXECUTABLE_DIALECTS = {"ANSI_SQL", "SNOWFLAKE"}
_PLACEHOLDER = re.compile(r"(?:UNRESOLVED|REPLACE_WITH)", re.IGNORECASE)


def schema_sha256() -> str:
    return hashlib.sha256(SCHEMA.read_bytes()).hexdigest()


def assert_ossie_checkout() -> None:
    if not SCHEMA.is_file() or not VALIDATOR.is_file():
        raise RuntimeError(
            "Apache Ossie submodule is not initialized; run git submodule update --init --recursive"
        )
    actual = schema_sha256()
    if actual != EXPECTED_SCHEMA_SHA256:
        raise RuntimeError(
            f"Apache Ossie schema hash changed: expected {EXPECTED_SCHEMA_SHA256}, got {actual}"
        )


@lru_cache(maxsize=1)
def _official_validator() -> ModuleType:
    assert_ossie_checkout()
    spec = importlib.util.spec_from_file_location("data_agent_official_ossie_validator", VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load official Ossie validator: {VALIDATOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _schema_document() -> dict[str, Any]:
    value = json.loads(SCHEMA.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("official Ossie schema must be a JSON object")
    return value


def official_validation_errors(document: dict[str, Any]) -> list[str]:
    """Run the exact validation functions shipped by the pinned Apache Ossie revision."""

    validator = _official_validator()
    errors: list[str] = []
    errors.extend(validator.validate_schema(document, _schema_document()))
    if document.get("semantic_model"):
        errors.extend(validator.validate_unique_names(document))
        errors.extend(validator.validate_references(document))
        errors.extend(validator.validate_sql(document))
    return errors


def readiness_issues(document: dict[str, Any]) -> list[dict[str, str]]:
    """Check data-agent usability requirements that are intentionally outside the core spec."""

    issues: list[dict[str, str]] = []
    models = [item for item in document.get("semantic_model", []) if isinstance(item, dict)]
    _check_normalized_names(models, "document", "semantic models", issues)
    for model_index, model in enumerate(models):
        model_name = str(model.get("name") or f"model_{model_index}")
        datasets = [item for item in model.get("datasets", []) if isinstance(item, dict)]
        _check_normalized_names(datasets, model_name, "datasets", issues)
        dataset_by_name = {str(item.get("name")): item for item in datasets}

        if not model.get("description"):
            issues.append(
                _issue(
                    "review",
                    "MISSING_MODEL_DESCRIPTION",
                    model_name,
                    "Add a source-backed description or an explicitly reviewed business description.",
                )
            )

        for dataset in datasets:
            dataset_name = str(dataset.get("name") or "<unnamed>")
            source = str(dataset.get("source") or "")
            if not source or _PLACEHOLDER.search(source):
                issues.append(
                    _issue(
                        "blocking",
                        "UNRESOLVED_PHYSICAL_SOURCE",
                        f"{model_name}.{dataset_name}",
                        "Map the dataset to a real physical table or view.",
                    )
                )
            _check_extensions(dataset, f"{model_name}.{dataset_name}", issues)
            fields = [item for item in dataset.get("fields", []) if isinstance(item, dict)]
            _check_normalized_names(fields, f"{model_name}.{dataset_name}", "fields", issues)
            available_columns: set[str] = set()
            for field in fields:
                field_name = str(field.get("name") or "<unnamed>")
                element = f"{model_name}.{dataset_name}.{field_name}"
                available_columns.add(field_name)
                dialects = _dialects(field)
                for expression in dialects.values():
                    terminal = re.fullmatch(r"[A-Za-z_]\w*\.([A-Za-z_]\w*)", expression)
                    if terminal:
                        available_columns.add(terminal.group(1))
                if not _EXECUTABLE_DIALECTS.intersection(dialects):
                    issues.append(
                        _issue(
                            "review",
                            "NO_EXECUTABLE_SQL_DIALECT",
                            element,
                            "The field has no ANSI_SQL or SNOWFLAKE expression for analysis.",
                        )
                    )
                _check_extensions(field, element, issues)
            dataset["__available_columns_for_validation"] = sorted(available_columns)

        relationships = [item for item in model.get("relationships", []) if isinstance(item, dict)]
        _check_normalized_names(relationships, model_name, "relationships", issues)
        for relationship in relationships:
            relationship_name = str(relationship.get("name") or "<unnamed>")
            element = f"{model_name}.{relationship_name}"
            from_name = str(relationship.get("from") or "")
            to_name = str(relationship.get("to") or "")
            from_columns = relationship.get("from_columns", [])
            to_columns = relationship.get("to_columns", [])
            if (
                not isinstance(from_columns, list)
                or not isinstance(to_columns, list)
                or not from_columns
                or len(from_columns) != len(to_columns)
            ):
                issues.append(
                    _issue(
                        "blocking",
                        "RELATIONSHIP_COLUMN_MISMATCH",
                        element,
                        "Relationship key arrays must be non-empty and have equal cardinality.",
                    )
                )
            for side, dataset_name, columns in (
                ("from", from_name, from_columns),
                ("to", to_name, to_columns),
            ):
                relationship_dataset = dataset_by_name.get(dataset_name)
                if relationship_dataset is None or not isinstance(columns, list):
                    continue
                available = set(relationship_dataset.get("__available_columns_for_validation", []))
                missing = [str(column) for column in columns if str(column) not in available]
                if missing:
                    issues.append(
                        _issue(
                            "blocking",
                            "UNKNOWN_RELATIONSHIP_COLUMN",
                            element,
                            f"Unknown {side}-side columns in {dataset_name}: {', '.join(missing)}.",
                        )
                    )
            _check_extensions(relationship, element, issues)

        metrics = [item for item in model.get("metrics", []) if isinstance(item, dict)]
        _check_normalized_names(metrics, model_name, "metrics", issues)
        for metric in metrics:
            metric_name = str(metric.get("name") or "<unnamed>")
            element = f"{model_name}.{metric_name}"
            if not _EXECUTABLE_DIALECTS.intersection(_dialects(metric)):
                issues.append(
                    _issue(
                        "review",
                        "NO_EXECUTABLE_SQL_DIALECT",
                        element,
                        "The metric has no ANSI_SQL or SNOWFLAKE expression for analysis.",
                    )
                )
            _check_extensions(metric, element, issues)
        _check_extensions(model, model_name, issues)

        for dataset in datasets:
            dataset.pop("__available_columns_for_validation", None)
    return issues


def validate_osi_document(document: dict[str, Any]) -> dict[str, Any]:
    official = official_validation_errors(document)
    readiness = readiness_issues(document) if not official else []
    return {
        "schema_valid": not any(error.startswith("[Schema]") for error in official),
        "official_valid": not official,
        "analysis_ready": not official and not readiness,
        "official_errors": official,
        "readiness_issues": readiness,
    }


def _dialects(item: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    expression = item.get("expression", {})
    if not isinstance(expression, dict):
        return result
    for dialect in expression.get("dialects", []):
        if not isinstance(dialect, dict):
            continue
        name, value = dialect.get("dialect"), dialect.get("expression")
        if isinstance(name, str) and isinstance(value, str):
            result[name] = value
    return result


def _check_extensions(item: dict[str, Any], element: str, issues: list[dict[str, str]]) -> None:
    parsed_extensions: list[dict[str, Any]] = []
    for extension in item.get("custom_extensions", []):
        if not isinstance(extension, dict):
            continue
        data = extension.get("data")
        if not isinstance(data, str):
            continue
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            issues.append(
                _issue(
                    "blocking",
                    "INVALID_EXTENSION_JSON",
                    element,
                    "custom_extensions.data must contain valid serialized JSON.",
                )
            )
            continue
        if not isinstance(parsed, dict):
            continue
        parsed_extensions.append(parsed)

    unsupported_reviewed = any(
        parsed.get("kind") == "unsupported_review"
        and parsed.get("translation_status") == "reviewed-unsupported"
        for parsed in parsed_extensions
    )
    for parsed in parsed_extensions:
        if (
            parsed.get("kind") == "conversion_provenance"
            and parsed.get("unsupported")
            and not unsupported_reviewed
        ):
            issues.append(
                _issue(
                    "review",
                    "UNSUPPORTED_SOURCE_CONSTRUCTS",
                    element,
                    "The source contains constructs that are preserved but not translated.",
                )
            )
        if parsed.get("kind") in {"source_metadata", "unsupported_review"} and parsed.get(
            "translation_status"
        ) in {
            "equivalent-with-assumptions",
            "partial",
            "unsupported",
            "requires-human-review",
        }:
            issues.append(
                _issue(
                    "review",
                    "UNREVIEWED_TRANSLATION",
                    element,
                    "The source-to-OSI translation still has an unresolved review status.",
                )
            )


def _issue(severity: str, code: str, element: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "element": element, "message": message}


def _check_normalized_names(
    items: list[dict[str, Any]],
    scope: str,
    kind: str,
    issues: list[dict[str, str]],
) -> None:
    seen: dict[str, str] = {}
    for item in items:
        name = str(item.get("name") or "")
        normalized = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
        if not normalized:
            continue
        previous = seen.get(normalized)
        if previous is not None and previous != name:
            issues.append(
                _issue(
                    "blocking",
                    "DUPLICATE_NORMALIZED_NAME",
                    scope,
                    f"{kind.capitalize()} {previous!r} and {name!r} normalize to the same name.",
                )
            )
        else:
            seen[normalized] = name
