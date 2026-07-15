from __future__ import annotations

import re
from collections import Counter
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


def _positive_row_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SemanticError("max_rows must be an integer") from exc
    if parsed <= 0:
        raise SemanticError("max_rows must be positive")
    return min(parsed, 5000)


def _projection_aliases(
    dimensions: list[tuple[str, dict[str, Any], dict[str, Any]]],
    metrics: list[dict[str, Any]],
) -> dict[str, str]:
    candidates = [str(field.get("name")) for _, _, field in dimensions]
    candidates.extend(str(metric.get("name")) for metric in metrics)
    collisions = {name for name, count in Counter(candidates).items() if count > 1}
    result: dict[str, str] = {}
    for qualified, dataset, field in dimensions:
        name = str(field.get("name"))
        alias = f"{dataset.get('name')}__{name}" if name in collisions else name
        result[qualified] = alias
    for metric in metrics:
        name = str(metric.get("name"))
        result[name] = f"metric__{name}" if name in collisions else name
    aliases = list(result.values())
    if len(set(aliases)) != len(aliases) or any(not _NAME.fullmatch(alias) for alias in aliases):
        raise SemanticError("selected output names cannot be represented as unique SQL aliases")
    return result


def compile_plan(document: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    models = list(iter_models(document))
    model = _find(models, str(plan.get("semantic_model")), "semantic model")
    datasets = [item for item in model.get("datasets", []) if isinstance(item, dict)]
    metrics = [item for item in model.get("metrics", []) if isinstance(item, dict)]
    metric_names = plan.get("metric_ids")
    if not isinstance(metric_names, list) or not metric_names:
        raise SemanticError("metric_ids must be a non-empty array")
    metric_ids = [str(name) for name in metric_names]
    selected_metrics = [_find(metrics, name, "metric") for name in metric_ids]
    dimension_names = plan.get("dimensions", [])
    if not isinstance(dimension_names, list):
        raise SemanticError("dimensions must be an array")

    fields: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for dataset in datasets:
        for field in dataset.get("fields", []):
            if isinstance(field, dict):
                fields[f"{dataset.get('name')}.{field.get('name')}"] = (dataset, field)
    selected_fields: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
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
            raise SemanticError("no model-defined join path connects all referenced datasets")

    result_columns = _projection_aliases(selected_fields, selected_metrics)
    result_grain = [result_columns[str(name)] for name in dimension_names]
    select_parts = [
        f"{_snowflake_expression(field)} AS {result_columns[qualified]}"
        for qualified, _, field in selected_fields
    ]
    select_parts += [
        f"{_snowflake_expression(metric)} AS {result_columns[str(metric['name'])]}"
        for metric in selected_metrics
    ]
    filters = plan.get("filters", [])
    if not isinstance(filters, list):
        raise SemanticError("filters must be an array")
    where_parts: list[str] = []
    parameters: list[Any] = []
    for item in filters:
        if (
            not isinstance(item, dict)
            or item.get("field") not in fields
            or item.get("operator") not in {"=", "!=", ">", ">=", "<", "<="}
        ):
            raise SemanticError("filter must use a model-defined field and supported operator")
        _, field = fields[item["field"]]
        where_parts.append(f"{_snowflake_expression(field)} {item['operator']} %s")
        parameters.append(item.get("value"))

    normalized_time_range: dict[str, str] | None = None
    time_range = plan.get("time_range")
    if time_range is not None:
        if not isinstance(time_range, dict):
            raise SemanticError("time_range must be an object")
        field_name = str(time_range.get("field", ""))
        if field_name not in fields:
            raise SemanticError("time_range must use a model-defined field")
        start = time_range.get("start")
        end_exclusive = time_range.get("end_exclusive")
        label = time_range.get("label", "")
        if not isinstance(start, str) or not start.strip():
            raise SemanticError("time_range.start must be a non-empty string")
        if not isinstance(end_exclusive, str) or not end_exclusive.strip():
            raise SemanticError("time_range.end_exclusive must be a non-empty string")
        if not isinstance(label, str):
            raise SemanticError("time_range.label must be a string")
        _, time_field = fields[field_name]
        expression = _snowflake_expression(time_field)
        where_parts.extend([f"{expression} >= %s", f"{expression} < %s"])
        parameters.extend([start, end_exclusive])
        normalized_time_range = {
            "field": field_name,
            "start": start,
            "end_exclusive": end_exclusive,
            "label": label,
        }

    order_by = plan.get("order_by", [])
    if not isinstance(order_by, list):
        raise SemanticError("order_by must be an array")
    alias_to_identifier = {alias: identifier for identifier, alias in result_columns.items()}
    normalized_order: list[dict[str, str]] = []
    order_parts: list[str] = []
    for item in order_by:
        if not isinstance(item, dict):
            raise SemanticError("each order_by item must be an object")
        requested = str(item.get("field", ""))
        identifier = (
            requested if requested in result_columns else alias_to_identifier.get(requested)
        )
        direction = str(item.get("direction", "asc")).casefold()
        if identifier is None:
            raise SemanticError("order_by fields must be selected dimensions or metrics")
        if direction not in {"asc", "desc"}:
            raise SemanticError("order_by direction must be asc or desc")
        order_parts.append(f"{result_columns[identifier]} {direction.upper()}")
        normalized_order.append({"field": identifier, "direction": direction})

    max_rows = _positive_row_limit(plan.get("max_rows", 5000))
    query_limit = max_rows + 1
    sql = "SELECT\n  " + ",\n  ".join(select_parts) + "\nFROM " + from_sql
    if where_parts:
        sql += "\nWHERE " + " AND ".join(where_parts)
    if selected_fields:
        sql += "\nGROUP BY " + ", ".join(str(index + 1) for index in range(len(selected_fields)))
    if order_parts:
        sql += "\nORDER BY " + ", ".join(order_parts)
    sql += "\nLIMIT " + str(query_limit)
    normalized_plan = {
        "semantic_model": str(model["name"]),
        "metric_ids": metric_ids,
        "dimensions": [str(name) for name in dimension_names],
        "filters": filters,
        "time_range": normalized_time_range,
        "order_by": normalized_order,
        "max_rows": max_rows,
    }
    return {
        "sql": sql,
        "parameters": parameters,
        "grain": [str(name) for name in dimension_names],
        "result_grain": result_grain,
        "result_columns": result_columns,
        "model": model["name"],
        "max_rows": max_rows,
        "query_limit": query_limit,
        "period": normalized_time_range,
        "normalized_plan": normalized_plan,
    }
