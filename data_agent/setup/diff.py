from __future__ import annotations

import copy
from typing import Any

_BREAKING_PROPERTIES = {
    "name",
    "source",
    "primary_key",
    "unique_keys",
    "from",
    "to",
    "from_columns",
    "to_columns",
}
_SEMANTIC_PROPERTIES = {
    "aggregation",
    "dimension",
    "expression",
    "filter",
    "filters",
    "population",
}


def semantic_changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_objects = _objects(before)
    after_objects = _objects(after)
    changes: list[dict[str, Any]] = []
    added = sorted(set(after_objects) - set(before_objects))
    removed = sorted(set(before_objects) - set(after_objects))
    shared = sorted(set(before_objects).intersection(after_objects))

    for key in added:
        kind, name = key
        changes.append(_change(kind, name, "added", "semantic", None, after_objects[key]))
    for key in removed:
        kind, name = key
        changes.append(_change(kind, name, "removed", "breaking", before_objects[key], None))
    for key in shared:
        kind, name = key
        before_value, after_value = before_objects[key], after_objects[key]
        properties = sorted(set(before_value).union(after_value))
        for property_name in properties:
            old, new = before_value.get(property_name), after_value.get(property_name)
            if old == new:
                continue
            impact = (
                "breaking"
                if property_name in _BREAKING_PROPERTIES
                else "semantic"
                if property_name in _SEMANTIC_PROPERTIES
                else "metadata"
            )
            changes.append(
                _change(
                    kind,
                    name,
                    f"{property_name}_changed",
                    impact,
                    old,
                    new,
                )
            )

    return {
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changes) - len(added) - len(removed),
        },
        "changes": changes,
    }


def _objects(document: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for model in document.get("semantic_model", []):
        if not isinstance(model, dict):
            continue
        model_name = str(model.get("name", "<unnamed>"))
        result[("model", model_name)] = _without(model, {"datasets", "metrics", "relationships"})
        for dataset in model.get("datasets", []):
            if not isinstance(dataset, dict):
                continue
            dataset_name = str(dataset.get("name", "<unnamed>"))
            result[("dataset", f"{model_name}.{dataset_name}")] = _without(dataset, {"fields"})
            for field in dataset.get("fields", []):
                if isinstance(field, dict):
                    field_name = str(field.get("name", "<unnamed>"))
                    result[("field", f"{model_name}.{dataset_name}.{field_name}")] = copy.deepcopy(
                        field
                    )
        for kind, plural in (("metric", "metrics"), ("relationship", "relationships")):
            for item in model.get(plural, []):
                if isinstance(item, dict):
                    name = str(item.get("name", "<unnamed>"))
                    result[(kind, f"{model_name}.{name}")] = copy.deepcopy(item)
    return result


def _without(value: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    return {key: copy.deepcopy(item) for key, item in value.items() if key not in keys}


def _change(
    kind: str,
    name: str,
    change_type: str,
    impact: str,
    before: Any,
    after: Any,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "object": name,
        "change_type": change_type,
        "impact": impact,
        "before": copy.deepcopy(before),
        "after": copy.deepcopy(after),
    }
