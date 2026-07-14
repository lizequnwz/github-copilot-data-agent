from __future__ import annotations

import json
import re
from typing import Any

from data_agent.io import ContractError, envelope

OSI_VERSION = "0.2.0.dev0"
EXTENSION_VENDOR = "COMMON"
TRANSLATION_STATES = {
    "exact",
    "equivalent-with-assumptions",
    "partial",
    "unsupported",
    "requires-human-review",
}


def _slug(value: Any, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or fallback)).strip("_").lower()
    return normalized or fallback


def _extension(data: dict[str, Any], vendor: str = EXTENSION_VENDOR) -> dict[str, str]:
    return {"vendor_name": vendor, "data": json.dumps(data, sort_keys=True)}


def _state(value: Any) -> str:
    candidate = str(value or "requires-human-review")
    return candidate if candidate in TRANSLATION_STATES else "requires-human-review"


def _expression(value: str, dialect: str = "ANSI_SQL") -> dict[str, Any]:
    return {"dialects": [{"dialect": dialect, "expression": value}]}


def _expressions(item: dict[str, Any], normalized: Any = None) -> dict[str, Any] | None:
    dialects: list[dict[str, str]] = []
    supplied = item.get("dialect_expressions", [])
    if isinstance(supplied, list):
        for value in supplied:
            if not isinstance(value, dict):
                continue
            dialect, expression = value.get("dialect"), value.get("expression")
            if isinstance(dialect, str) and isinstance(expression, str) and expression.strip():
                dialects.append({"dialect": dialect, "expression": expression})
    if normalized:
        dialect = str(item.get("dialect") or "ANSI_SQL")
        expression = str(normalized)
        if not any(
            value["dialect"] == dialect and value["expression"] == expression for value in dialects
        ):
            dialects.insert(0, {"dialect": dialect, "expression": expression})
    return {"dialects": dialects} if dialects else None


def _ai_context(
    item: dict[str, Any], normalized_name: str | None = None
) -> dict[str, Any] | str | None:
    supplied = item.get("ai_context")
    if isinstance(supplied, str) and supplied.strip():
        return supplied
    context = dict(supplied) if isinstance(supplied, dict) else {}
    synonyms = list(item.get("synonyms", [])) if isinstance(item.get("synonyms"), list) else []
    explicit_name = item.get("display_name") or item.get("name")
    if (
        normalized_name
        and isinstance(explicit_name, str)
        and explicit_name.casefold() != normalized_name.casefold()
    ):
        synonyms.append(explicit_name)
    if isinstance(synonyms, list) and synonyms:
        existing = context.get("synonyms", [])
        values = [str(value) for value in existing] if isinstance(existing, list) else []
        for synonym in synonyms:
            candidate = str(synonym).strip()
            if candidate and candidate not in values:
                values.append(candidate)
        if values:
            context["synonyms"] = values
    return context or None


def build_osi_from_ir(
    ir: dict[str, Any], model_name: str | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Convert neutral semantic IR into Ossie core metadata plus conversion issues.

    Vendor expressions that are not valid Ossie dialect expressions are retained in
    custom extensions. Only reviewed/translated SQL expressions enter the core model.
    """

    name = _slug(model_name or ir.get("model_name") or ir.get("source_artifact"), "generated_model")
    issues: list[dict[str, Any]] = []
    datasets: list[dict[str, Any]] = []
    dataset_names: set[str] = set()

    source_datasets = ir.get("datasets", [])
    if not isinstance(source_datasets, list) or not source_datasets:
        raise ContractError("semantic_ir.datasets must be a non-empty array")

    for source_dataset in source_datasets:
        if not isinstance(source_dataset, dict):
            raise ContractError("each semantic_ir dataset must be an object")
        dataset_name = _slug(source_dataset.get("name"), "dataset")
        if dataset_name in dataset_names:
            raise ContractError(f"duplicate normalized dataset name: {dataset_name}")
        dataset_names.add(dataset_name)
        physical_source = str(
            source_dataset.get("physical_source")
            or source_dataset.get("source")
            or f"UNRESOLVED.UNRESOLVED.{dataset_name.upper()}"
        )
        if physical_source.startswith("UNRESOLVED."):
            issues.append(
                {
                    "severity": "blocking",
                    "code": "UNRESOLVED_PHYSICAL_SOURCE",
                    "element": dataset_name,
                    "message": "Map this dataset to a physical table or view before using it for analysis.",
                }
            )

        fields: list[dict[str, Any]] = []
        field_names: set[str] = set()
        for source_field in source_dataset.get("fields", []):
            if not isinstance(source_field, dict):
                continue
            field_name = _slug(source_field.get("name"), "field")
            if field_name in field_names:
                issues.append(
                    {
                        "severity": "blocking",
                        "code": "DUPLICATE_FIELD",
                        "element": f"{dataset_name}.{field_name}",
                        "message": "Two source fields normalize to the same Ossie field name.",
                    }
                )
                continue
            field_names.add(field_name)
            normalized = source_field.get("normalized_expression")
            expressions = _expressions(source_field, normalized)
            translation_state = _state(
                source_field.get(
                    "translation_status",
                    "exact" if normalized else "equivalent-with-assumptions",
                )
            )
            if expressions is None:
                if source_field.get("prevent_physical_fallback") or (
                    source_field.get("source_expression") is not None
                    and translation_state in {"partial", "unsupported", "requires-human-review"}
                ):
                    issues.append(
                        {
                            "severity": "review",
                            "code": "UNTRANSLATED_CALCULATED_FIELD",
                            "element": f"{dataset_name}.{field_name}",
                            "message": "The calculated field is preserved in provenance but was not emitted as executable SQL.",
                        }
                    )
                    continue
                expressions = _expression(f"{dataset_name}.{field_name}")
            field: dict[str, Any] = {
                "name": field_name,
                "expression": expressions,
                "custom_extensions": [
                    _extension(
                        {
                            "kind": "source_metadata",
                            "source_id": source_field.get("id"),
                            "source_name": source_field.get("name"),
                            "source_expression": source_field.get("source_expression"),
                            "source_data_type": source_field.get("data_type"),
                            "source_format": source_field.get("format"),
                            "semantic_role": source_field.get("semantic_role"),
                            "translation_status": translation_state,
                        },
                        str(source_field.get("extension_vendor") or EXTENSION_VENDOR),
                    )
                ],
            }
            if source_field.get("description"):
                field["description"] = str(source_field["description"])
            if source_field.get("label"):
                field["label"] = str(source_field["label"])
            if source_field.get("is_dimension") or source_field.get("is_time"):
                field["dimension"] = {"is_time": bool(source_field.get("is_time"))}
            ai_context = _ai_context(source_field, field_name)
            if ai_context is not None:
                field["ai_context"] = ai_context
            fields.append(field)

        dataset: dict[str, Any] = {
            "name": dataset_name,
            "source": physical_source,
            "fields": fields,
            "custom_extensions": [
                _extension(
                    {
                        "kind": "source_metadata",
                        "source_id": source_dataset.get("id"),
                        "source_name": source_dataset.get("name"),
                        "source_file": source_dataset.get("source_file"),
                        "translation_status": _state(
                            source_dataset.get("translation_status", "exact")
                        ),
                    },
                    str(source_dataset.get("extension_vendor") or EXTENSION_VENDOR),
                )
            ],
        }
        if source_dataset.get("description"):
            dataset["description"] = str(source_dataset["description"])
        dataset_ai_context = _ai_context(source_dataset, dataset_name)
        if dataset_ai_context is not None:
            dataset["ai_context"] = dataset_ai_context
        primary_key = source_dataset.get("primary_key")
        if isinstance(primary_key, list) and primary_key:
            dataset["primary_key"] = [_slug(item, "key") for item in primary_key]
        unique_keys = source_dataset.get("unique_keys")
        if isinstance(unique_keys, list) and unique_keys:
            dataset["unique_keys"] = [
                [_slug(item, "key") for item in key]
                for key in unique_keys
                if isinstance(key, list) and key
            ]
        datasets.append(dataset)

    relationships: list[dict[str, Any]] = []
    for source_relationship in ir.get("relationships", []):
        if not isinstance(source_relationship, dict):
            continue
        from_name = _slug(
            source_relationship.get("from") or source_relationship.get("from_dataset"), "from"
        )
        to_name = _slug(
            source_relationship.get("to") or source_relationship.get("to_dataset"), "to"
        )
        from_columns = source_relationship.get("from_columns", [])
        to_columns = source_relationship.get("to_columns", [])
        if (
            from_name not in dataset_names
            or to_name not in dataset_names
            or not isinstance(from_columns, list)
            or not isinstance(to_columns, list)
            or not from_columns
            or len(from_columns) != len(to_columns)
        ):
            issues.append(
                {
                    "severity": "blocking",
                    "code": "UNUSABLE_RELATIONSHIP",
                    "element": str(source_relationship.get("name") or "relationship"),
                    "message": "Relationship endpoints and equally sized key arrays must resolve to datasets.",
                }
            )
            continue
        relationship_name = _slug(
            source_relationship.get("name") or f"{from_name}_to_{to_name}", "relationship"
        )
        relationships.append(
            {
                "name": relationship_name,
                "from": from_name,
                "to": to_name,
                "from_columns": [_slug(item, "key") for item in from_columns],
                "to_columns": [_slug(item, "key") for item in to_columns],
                "custom_extensions": [
                    _extension(
                        {
                            "kind": "source_metadata",
                            "source_id": source_relationship.get("id"),
                            "source_expression": source_relationship.get("source_expression"),
                            "active": source_relationship.get("active", True),
                            "translation_status": _state(
                                source_relationship.get("translation_status", "exact")
                            ),
                        }
                    )
                ],
            }
        )
        relationship_ai_context = _ai_context(source_relationship)
        if relationship_ai_context is not None:
            relationships[-1]["ai_context"] = relationship_ai_context

    metrics: list[dict[str, Any]] = []
    metric_names: set[str] = set()
    for source_metric in ir.get("metrics", []):
        if not isinstance(source_metric, dict):
            continue
        metric_name = _slug(source_metric.get("name"), "metric")
        normalized = source_metric.get("normalized_expression")
        expressions = _expressions(source_metric, normalized)
        if expressions is None:
            issues.append(
                {
                    "severity": "review",
                    "code": "UNTRANSLATED_METRIC",
                    "element": metric_name,
                    "message": "Vendor expression was preserved but no equivalent Ossie SQL expression was emitted.",
                }
            )
            continue
        if metric_name in metric_names:
            issues.append(
                {
                    "severity": "blocking",
                    "code": "DUPLICATE_METRIC",
                    "element": metric_name,
                    "message": "Two source metrics normalize to the same Ossie metric name.",
                }
            )
            continue
        metric_names.add(metric_name)
        metric: dict[str, Any] = {
            "name": metric_name,
            "expression": expressions,
            "custom_extensions": [
                _extension(
                    {
                        "kind": "source_metadata",
                        "source_id": source_metric.get("id"),
                        "source_name": source_metric.get("name"),
                        "source_expression": source_metric.get("source_expression"),
                        "source_format": source_metric.get("source_format"),
                        "source_display_folder": source_metric.get("label"),
                        "source_display_format": source_metric.get("format"),
                        "translation_status": _state(source_metric.get("translation_status")),
                    },
                    str(source_metric.get("extension_vendor") or EXTENSION_VENDOR),
                )
            ],
        }
        if source_metric.get("description"):
            metric["description"] = str(source_metric["description"])
        metric_ai_context = _ai_context(source_metric, metric_name)
        if metric_ai_context is not None:
            metric["ai_context"] = metric_ai_context
        metrics.append(metric)

    for unsupported in ir.get("unsupported", []):
        issues.append(
            {
                "severity": "review",
                "code": "UNSUPPORTED_SOURCE_CONSTRUCT",
                "element": str(
                    unsupported.get("field") or unsupported.get("source_file") or "source"
                ),
                "message": str(unsupported.get("construct") or unsupported),
            }
        )

    extension = {
        "kind": "conversion_provenance",
        "producer": "github-copilot-data-agent",
        "lifecycle": "generated",
        "source_type": ir.get("source_type"),
        "source_format": ir.get("source_format"),
        "source_artifact": ir.get("source_artifact"),
        "source_files": ir.get("source_files", []),
        "snapshot_sha256": ir.get("snapshot_sha256"),
        "ir_version": ir.get("ir_version"),
        "unsupported": ir.get("unsupported", []),
    }
    semantic_model: dict[str, Any] = {
        "name": name,
        "datasets": datasets,
        "relationships": relationships,
        "metrics": metrics,
        "custom_extensions": [_extension(extension)],
    }
    if ir.get("description"):
        semantic_model["description"] = str(ir["description"])
    else:
        issues.append(
            {
                "severity": "review",
                "code": "MISSING_MODEL_DESCRIPTION",
                "element": name,
                "message": "Add a source-backed description during semantic review.",
            }
        )
    model_ai_context = _ai_context(ir)
    if model_ai_context is not None:
        semantic_model["ai_context"] = model_ai_context
    document = {
        "version": OSI_VERSION,
        "semantic_model": [semantic_model],
    }
    return document, issues


def ir_to_osi(request: dict[str, Any]) -> dict[str, Any]:
    ir = request.get("semantic_ir")
    if not isinstance(ir, dict):
        raise ContractError("semantic_ir must be an object")
    document, issues = build_osi_from_ir(ir, request.get("model_name"))
    warnings = [issue["message"] for issue in issues if issue["severity"] != "blocking"]
    return envelope(
        request,
        "success",
        osi=document,
        lifecycle="generated",
        issues=issues,
        warnings=warnings,
    )
