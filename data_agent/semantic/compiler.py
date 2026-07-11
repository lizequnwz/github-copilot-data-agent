from __future__ import annotations

import re
from typing import Any, cast

from data_agent.semantic.models import SemanticError, iter_models

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_QUALIFIED = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*){1,2}$")


def _find(items: list[dict[str, Any]], name: str, kind: str) -> dict[str, Any]:
    matches = [item for item in items if item.get("name") == name]
    if len(matches) != 1:
        raise SemanticError(f"expected exactly one {kind} named {name!r}")
    return matches[0]


def _snowflake_expression(item: dict[str, Any]) -> str:
    dialects = item.get("expression", {}).get("dialects", [])
    for wanted in ("SNOWFLAKE", "ANSI_SQL"):
        for dialect in dialects:
            if dialect.get("dialect") == wanted and isinstance(dialect.get("expression"), str):
                return cast(str, dialect["expression"])
    raise SemanticError(f"{item.get('name')} has no Snowflake/ANSI expression")


def compile_plan(document: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    models = list(iter_models(document))
    model = _find(models, str(plan.get("semantic_model")), "semantic model")
    datasets = [item for item in model.get("datasets", []) if isinstance(item, dict)]
    metrics = [item for item in model.get("metrics", []) if isinstance(item, dict)]
    metric_names = plan.get("metric_ids")
    if not isinstance(metric_names, list) or not metric_names:
        raise SemanticError("metric_ids must be a non-empty array")
    selected_metrics = [_find(metrics, str(name), "metric") for name in metric_names]
    dimension_names = plan.get("dimensions", [])
    if not isinstance(dimension_names, list):
        raise SemanticError("dimensions must be an array")

    fields: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for dataset in datasets:
        for field in dataset.get("fields", []):
            if isinstance(field, dict):
                fields[f"{dataset.get('name')}.{field.get('name')}"] = (dataset, field)
    selected_fields = []
    for name in dimension_names:
        qualified = str(name)
        if qualified not in fields:
            raise SemanticError(f"unknown or unqualified dimension: {qualified}")
        selected_fields.append((qualified, *fields[qualified]))

    referenced: set[str] = set()
    for expression in [_snowflake_expression(metric) for metric in selected_metrics] + [
        _snowflake_expression(field) for _, _, field in selected_fields
    ]:
        referenced.update(token for token in re.findall(r"\b([A-Za-z_]\w*)\.", expression))
    referenced.update(str(dataset["name"]) for _, dataset, _ in selected_fields)
    used = [dataset for dataset in datasets if dataset.get("name") in referenced]
    if not used:
        raise SemanticError("expressions do not identify a source dataset")
    for dataset in used:
        if not _NAME.fullmatch(str(dataset.get("name"))) or not _QUALIFIED.fullmatch(
            str(dataset.get("source"))
        ):
            raise SemanticError("dataset names and sources must be safe qualified identifiers")

    from_sql = f"{used[0]['source']} AS {used[0]['name']}"
    joined = {used[0]["name"]}
    relationships = [r for r in model.get("relationships", []) if isinstance(r, dict)]
    while len(joined) < len(used):
        progress = False
        for relationship in relationships:
            left, right = relationship.get("from"), relationship.get("to")
            target = right if left in joined else left if right in joined else None
            if target is None or target in joined or target not in {d["name"] for d in used}:
                continue
            left_cols, right_cols = (
                relationship.get("from_columns", []),
                relationship.get("to_columns", []),
            )
            if len(left_cols) != len(right_cols) or not left_cols:
                raise SemanticError(f"invalid relationship columns: {relationship.get('name')}")
            target_dataset = _find(datasets, target, "dataset")
            conditions = " AND ".join(
                f"{left}.{a} = {right}.{b}" for a, b in zip(left_cols, right_cols)
            )
            from_sql += f"\nJOIN {target_dataset['source']} AS {target} ON {conditions}"
            joined.add(target)
            progress = True
        if not progress:
            raise SemanticError("no governed join path connects all referenced datasets")

    select_parts = [
        f"{_snowflake_expression(field)} AS {field['name']}" for _, _, field in selected_fields
    ]
    select_parts += [
        f"{_snowflake_expression(metric)} AS {metric['name']}" for metric in selected_metrics
    ]
    filters = plan.get("filters", [])
    where_parts: list[str] = []
    parameters: list[Any] = []
    for item in filters:
        if (
            not isinstance(item, dict)
            or item.get("field") not in fields
            or item.get("operator") not in {"=", "!=", ">", ">=", "<", "<="}
        ):
            raise SemanticError("filter must use a governed field and supported operator")
        _, field = fields[item["field"]]
        where_parts.append(f"{_snowflake_expression(field)} {item['operator']} %s")
        parameters.append(item.get("value"))
    sql = "SELECT\n  " + ",\n  ".join(select_parts) + "\nFROM " + from_sql
    if where_parts:
        sql += "\nWHERE " + " AND ".join(where_parts)
    if selected_fields:
        sql += "\nGROUP BY " + ", ".join(str(index + 1) for index in range(len(selected_fields)))
    sql += "\nLIMIT " + str(min(int(plan.get("max_rows", 5000)), 5000))
    return {"sql": sql, "parameters": parameters, "grain": dimension_names, "model": model["name"]}
