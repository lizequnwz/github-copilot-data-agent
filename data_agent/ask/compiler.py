from __future__ import annotations

import re
from collections import Counter
from typing import Any, cast

import sqlglot
from sqlglot import exp

from data_agent.models import SemanticError, iter_models

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_QUALIFIED = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*){1,2}$")
_FILTER_OPERATORS = {"=", "!=", ">", ">=", "<", "<="}
_LIST_FILTER_OPERATORS = {"in", "not_in"}
_NULL_FILTER_OPERATORS = {"is_null", "is_not_null"}
_TEXT_FILTER_OPERATORS = {"contains", "starts_with", "ends_with"}
_TIME_GRAINS = {"day", "week", "month", "quarter", "year"}
_CALCULATION_TYPES = {"percent_of_total", "rank", "running_total"}


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


def _derived_metrics(
    value: Any,
    fields: dict[str, tuple[dict[str, Any], dict[str, Any]]],
    promoted_names: set[str],
) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SemanticError("derived_metrics must be an array")
    if len(value) > 20:
        raise SemanticError("derived_metrics cannot contain more than 20 metrics")
    result: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise SemanticError(f"derived metric {index} must be an object")
        name = str(item.get("name", ""))
        if not _NAME.fullmatch(name):
            raise SemanticError(f"derived metric {index} requires a safe SQL name")
        if name in promoted_names or name in names:
            raise SemanticError(f"derived metric name is not unique: {name}")
        expression = item.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            raise SemanticError(f"derived metric {name} requires an expression")
        if len(expression.encode("utf-8")) > 50_000:
            raise SemanticError(f"derived metric expression is too large: {name}")
        normalized, references = _compile_derived_expression(expression, fields, name)
        assumptions = item.get("assumptions", [])
        if not isinstance(assumptions, list) or not all(
            isinstance(assumption, str) for assumption in assumptions
        ):
            raise SemanticError(f"derived metric {name} assumptions must be an array of strings")
        description = item.get("description")
        if not isinstance(description, str) or not description.strip():
            raise SemanticError(f"derived metric {name} requires a description")
        result.append(
            {
                "name": name,
                "description": description.strip(),
                "assumptions": assumptions,
                "unpromoted": True,
                "referenced_fields": references,
                "expression": {
                    "dialects": [{"dialect": "SNOWFLAKE", "expression": normalized}]
                },
            }
        )
        names.add(name)
    return result


def _compile_derived_expression(
    value: str,
    fields: dict[str, tuple[dict[str, Any], dict[str, Any]]],
    metric_name: str,
) -> tuple[str, list[str]]:
    try:
        statement = sqlglot.parse_one(f"SELECT {value}", read="snowflake")
    except sqlglot.errors.ParseError as exc:
        raise SemanticError(f"derived metric {metric_name} expression is invalid: {exc}") from exc
    if not isinstance(statement, exp.Select) or len(statement.expressions) != 1:
        raise SemanticError(f"derived metric {metric_name} must be one SQL expression")
    projection = statement.expressions[0]
    if projection.find(exp.Subquery) is not None or projection.find(exp.Select) is not None:
        raise SemanticError(f"derived metric {metric_name} cannot contain a query")
    if projection.find(exp.Star) is not None:
        raise SemanticError(
            f"derived metric {metric_name} must reference explicit model fields instead of *"
        )
    references: list[str] = []
    replacements: dict[int, exp.Expression] = {}
    for column in projection.find_all(exp.Column):
        qualified = f"{column.table}.{column.name}" if column.table else column.name
        if not column.table or qualified not in fields:
            raise SemanticError(
                f"derived metric {metric_name} references unknown or unqualified field: {qualified}"
            )
        _, field = fields[qualified]
        try:
            replacement = cast(
                exp.Expression,
                sqlglot.parse_one(_snowflake_expression(field), read="snowflake"),
            )
        except sqlglot.errors.ParseError as exc:
            raise SemanticError(f"model field expression is invalid: {qualified}") from exc
        replacements[id(column)] = replacement
        references.append(qualified)

    if not references:
        raise SemanticError(f"derived metric {metric_name} must reference a qualified model field")

    compiled = projection.transform(
        lambda node: replacements[id(node)].copy() if id(node) in replacements else node
    )
    return compiled.sql(dialect="snowflake"), sorted(set(references))


def _derived_dimensions(
    value: Any,
    fields: dict[str, tuple[dict[str, Any], dict[str, Any]]],
    reserved_names: set[str],
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SemanticError("derived_dimensions must be an array")
    if len(value) > 20:
        raise SemanticError("derived_dimensions cannot contain more than 20 dimensions")
    result: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    names: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise SemanticError(f"derived dimension {index} must be an object")
        name = str(item.get("name", ""))
        if not _NAME.fullmatch(name):
            raise SemanticError(f"derived dimension {index} requires a safe name")
        if name in names or name in reserved_names:
            raise SemanticError(f"derived dimension name is not unique: {name}")
        expression = item.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            raise SemanticError(f"derived dimension {name} requires an expression")
        normalized, references = _compile_derived_expression(expression, fields, name)
        parsed = sqlglot.parse_one(normalized, read="snowflake")
        if parsed.find(exp.AggFunc) is not None or parsed.find(exp.Window) is not None:
            raise SemanticError(
                f"derived dimension {name} cannot contain aggregate or window functions"
            )
        description = item.get("description")
        if not isinstance(description, str) or not description.strip():
            raise SemanticError(f"derived dimension {name} requires a description")
        assumptions = item.get("assumptions", [])
        if not isinstance(assumptions, list) or not all(
            isinstance(assumption, str) for assumption in assumptions
        ):
            raise SemanticError(f"derived dimension {name} assumptions must be strings")
        datasets = {fields[reference][0]["name"] for reference in references}
        if len(datasets) != 1:
            raise SemanticError(
                f"derived dimension {name} must resolve to fields from one model dataset"
            )
        dataset = fields[references[0]][0]
        result.append(
            (
                name,
                dataset,
                {
                    "name": name,
                    "description": description.strip(),
                    "assumptions": assumptions,
                    "unpromoted": True,
                    "referenced_fields": references,
                    "expression": {
                        "dialects": [{"dialect": "SNOWFLAKE", "expression": normalized}]
                    },
                },
            )
        )
        names.add(name)
    return result


def _time_dimensions(
    value: Any,
    fields: dict[str, tuple[dict[str, Any], dict[str, Any]]],
    reserved_names: set[str],
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SemanticError("time_dimensions must be an array")
    result: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    names: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise SemanticError(f"time dimension {index} must be an object")
        field_name = str(item.get("field", ""))
        if field_name not in fields:
            raise SemanticError(f"time dimension {index} must use a model-defined field")
        grain = str(item.get("grain", "")).casefold()
        if grain not in _TIME_GRAINS:
            raise SemanticError(
                f"time dimension {index} grain must be one of: {', '.join(sorted(_TIME_GRAINS))}"
            )
        _, source_field = fields[field_name]
        default_name = f"{source_field.get('name')}_{grain}"
        name = str(item.get("name") or default_name)
        if not _NAME.fullmatch(name) or name in names or name in reserved_names:
            raise SemanticError(f"time dimension name is invalid or not unique: {name}")
        dataset, _ = fields[field_name]
        expression = f"DATE_TRUNC('{grain}', {_snowflake_expression(source_field)})"
        result.append(
            (
                name,
                dataset,
                {
                    "name": name,
                    "description": f"{field_name} grouped by {grain}",
                    "source_field": field_name,
                    "grain": grain,
                    "expression": {
                        "dialects": [{"dialect": "SNOWFLAKE", "expression": expression}]
                    },
                },
            )
        )
        names.add(name)
    return result


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


def _compile_filter(
    item: Any,
    fields: dict[str, tuple[dict[str, Any], dict[str, Any]]],
) -> tuple[str, list[Any], str]:
    if not isinstance(item, dict) or item.get("field") not in fields:
        raise SemanticError("filter must use a model-defined field")
    field_name = str(item["field"])
    operator = str(item.get("operator", "")).casefold()
    expression = _snowflake_expression(fields[field_name][1])
    if operator in _FILTER_OPERATORS:
        return f"{expression} {operator} %s", [item.get("value")], field_name
    if operator in _LIST_FILTER_OPERATORS:
        values = item.get("values", item.get("value"))
        if (
            not isinstance(values, list)
            or not values
            or len(values) > 500
        ):
            raise SemanticError(f"{operator} filter requires 1 to 500 values")
        keyword = "IN" if operator == "in" else "NOT IN"
        placeholders = ", ".join("%s" for _ in values)
        return f"{expression} {keyword} ({placeholders})", values, field_name
    if operator in _NULL_FILTER_OPERATORS:
        keyword = "IS NULL" if operator == "is_null" else "IS NOT NULL"
        return f"{expression} {keyword}", [], field_name
    if operator in _TEXT_FILTER_OPERATORS:
        value = item.get("value")
        if not isinstance(value, str):
            raise SemanticError(f"{operator} filter requires a string value")
        pattern = (
            f"%{value}%"
            if operator == "contains"
            else f"{value}%"
            if operator == "starts_with"
            else f"%{value}"
        )
        return f"{expression} ILIKE %s", [pattern], field_name
    supported = sorted(
        _FILTER_OPERATORS
        | _LIST_FILTER_OPERATORS
        | _NULL_FILTER_OPERATORS
        | _TEXT_FILTER_OPERATORS
    )
    raise SemanticError(f"unsupported filter operator; use one of: {', '.join(supported)}")


def _compile_calculations(
    value: Any,
    result_columns: dict[str, str],
    metric_identifiers: set[str],
    default_order: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    if value is None:
        return [], []
    if not isinstance(value, list):
        raise SemanticError("calculations must be an array")
    if len(value) > 20:
        raise SemanticError("calculations cannot contain more than 20 items")
    normalized: list[dict[str, Any]] = []
    projections: list[str] = []
    used_names = set(result_columns.values())
    aliases_to_identifiers = {alias: identifier for identifier, alias in result_columns.items()}
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise SemanticError(f"calculation {index} must be an object")
        name = str(item.get("name", ""))
        calculation_type = str(item.get("type", "")).casefold()
        source = str(item.get("metric", ""))
        source_identifier = source if source in metric_identifiers else aliases_to_identifiers.get(source)
        if not _NAME.fullmatch(name) or name in used_names:
            raise SemanticError(f"calculation {index} requires a unique safe name")
        if calculation_type not in _CALCULATION_TYPES:
            raise SemanticError(
                f"calculation type must be one of: {', '.join(sorted(_CALCULATION_TYPES))}"
            )
        if source_identifier not in metric_identifiers:
            raise SemanticError(f"calculation {name} must reference a selected metric")
        source_alias = result_columns[source_identifier]
        direction = str(item.get("direction", "desc")).casefold()
        if direction not in {"asc", "desc"}:
            raise SemanticError(f"calculation {name} direction must be asc or desc")
        if calculation_type == "percent_of_total":
            sql = f"{source_alias} / NULLIF(SUM({source_alias}) OVER (), 0)"
        elif calculation_type == "rank":
            sql = f"RANK() OVER (ORDER BY {source_alias} {direction.upper()})"
        else:
            requested_order = item.get("order_by", default_order)
            if not isinstance(requested_order, list) or not requested_order:
                raise SemanticError(f"running_total calculation {name} requires order_by")
            order_aliases: list[str] = []
            for requested in requested_order:
                identifier = (
                    str(requested)
                    if str(requested) in result_columns
                    else aliases_to_identifiers.get(str(requested))
                )
                if identifier is None:
                    raise SemanticError(
                        f"running_total calculation {name} uses an unselected order field"
                    )
                order_aliases.append(result_columns[identifier])
            sql = (
                f"SUM({source_alias}) OVER (ORDER BY {', '.join(order_aliases)} "
                "ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)"
            )
        projections.append(f"{sql} AS {name}")
        normalized.append(
            {
                "name": name,
                "type": calculation_type,
                "metric": source_identifier,
                "direction": direction,
                **(
                    {"order_by": item.get("order_by", default_order)}
                    if calculation_type == "running_total"
                    else {}
                ),
            }
        )
        result_columns[name] = name
        used_names.add(name)
    return normalized, projections


def compile_plan(document: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    models = list(iter_models(document))
    model = _find(models, str(plan.get("semantic_model")), "semantic model")
    datasets = [item for item in model.get("datasets", []) if isinstance(item, dict)]
    metrics = [item for item in model.get("metrics", []) if isinstance(item, dict)]
    fields: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for dataset in datasets:
        for field in dataset.get("fields", []):
            if isinstance(field, dict):
                fields[f"{dataset.get('name')}.{field.get('name')}"] = (dataset, field)
    derived_metrics = _derived_metrics(
        plan.get("derived_metrics"), fields, {str(item.get("name")) for item in metrics}
    )
    metric_names = plan.get("metric_ids", [])
    if not isinstance(metric_names, list):
        raise SemanticError("metric_ids must be an array")
    metric_ids = [str(name) for name in metric_names]
    selected_metrics = [_find(metrics, name, "metric") for name in metric_ids] + derived_metrics
    dimension_names = plan.get("dimensions", [])
    if not isinstance(dimension_names, list):
        raise SemanticError("dimensions must be an array")

    selected_fields: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for name in dimension_names:
        qualified = str(name)
        if qualified not in fields:
            raise SemanticError(f"unknown or unqualified dimension: {qualified}")
        selected_fields.append((qualified, *fields[qualified]))
    reserved_names = {str(metric.get("name")) for metric in selected_metrics}
    derived_dimensions = _derived_dimensions(
        plan.get("derived_dimensions"), fields, reserved_names
    )
    reserved_names.update(str(item[2]["name"]) for item in derived_dimensions)
    time_dimensions = _time_dimensions(plan.get("time_dimensions"), fields, reserved_names)
    selected_fields.extend(derived_dimensions)
    selected_fields.extend(time_dimensions)
    if not selected_metrics and not selected_fields:
        raise SemanticError("select at least one model dimension or metric")

    filters = plan.get("filters", [])
    if not isinstance(filters, list):
        raise SemanticError("filters must be an array")
    where_parts: list[str] = []
    parameters: list[Any] = []
    filter_fields: list[str] = []
    for item in filters:
        sql_filter, filter_parameters, field_name = _compile_filter(item, fields)
        where_parts.append(sql_filter)
        parameters.extend(filter_parameters)
        filter_fields.append(field_name)

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
        filter_fields.append(field_name)
        normalized_time_range = {
            "field": field_name,
            "start": start,
            "end_exclusive": end_exclusive,
            "label": label,
        }

    referenced: set[str] = set()
    for expression in [_snowflake_expression(metric) for metric in selected_metrics] + [
        _snowflake_expression(field) for _, _, field in selected_fields
    ]:
        referenced.update(token for token in re.findall(r"\b([A-Za-z_]\w*)\.", expression))
    referenced.update(str(dataset["name"]) for _, dataset, _ in selected_fields)
    referenced.update(str(fields[name][0]["name"]) for name in filter_fields)
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
    dimension_identifiers = [identifier for identifier, _, _ in selected_fields]
    result_grain = [result_columns[identifier] for identifier in dimension_identifiers]
    select_parts = [
        f"{_snowflake_expression(field)} AS {result_columns[qualified]}"
        for qualified, _, field in selected_fields
    ]
    select_parts += [
        f"{_snowflake_expression(metric)} AS {result_columns[str(metric['name'])]}"
        for metric in selected_metrics
    ]
    having = plan.get("having", [])
    if not isinstance(having, list):
        raise SemanticError("having must be an array")
    having_parts: list[str] = []
    metric_by_name = {str(metric["name"]): metric for metric in selected_metrics}
    metric_alias_to_name = {
        result_columns[name]: name for name in metric_by_name if name in result_columns
    }
    normalized_having: list[dict[str, Any]] = []
    for item in having:
        if not isinstance(item, dict):
            raise SemanticError("each having item must be an object")
        requested = str(item.get("metric", ""))
        metric_name = requested if requested in metric_by_name else metric_alias_to_name.get(requested)
        operator = str(item.get("operator", "")).casefold()
        if metric_name is None or operator not in _FILTER_OPERATORS:
            raise SemanticError(
                "having must reference a selected metric and use a comparison operator"
            )
        having_parts.append(f"{_snowflake_expression(metric_by_name[metric_name])} {operator} %s")
        parameters.append(item.get("value"))
        normalized_having.append(
            {"metric": metric_name, "operator": operator, "value": item.get("value")}
        )

    base_sql = "SELECT\n  " + ",\n  ".join(select_parts) + "\nFROM " + from_sql
    if where_parts:
        base_sql += "\nWHERE " + " AND ".join(where_parts)
    if selected_metrics and selected_fields:
        base_sql += "\nGROUP BY " + ", ".join(
            str(index + 1) for index in range(len(selected_fields))
        )
    if having_parts:
        base_sql += "\nHAVING " + " AND ".join(having_parts)

    normalized_calculations, calculation_projections = _compile_calculations(
        plan.get("calculations"),
        result_columns,
        set(metric_by_name),
        dimension_identifiers,
    )
    if calculation_projections:
        base_aliases = [result_columns[identifier] for identifier in dimension_identifiers] + [
            result_columns[name] for name in metric_by_name
        ]
        sql = (
            "WITH base AS (\n"
            + "\n".join(f"  {line}" for line in base_sql.splitlines())
            + "\n)\nSELECT\n  "
            + ",\n  ".join([*base_aliases, *calculation_projections])
            + "\nFROM base"
        )
    else:
        sql = base_sql

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
            raise SemanticError(
                "order_by fields must be selected dimensions, metrics, or calculations"
            )
        if direction not in {"asc", "desc"}:
            raise SemanticError("order_by direction must be asc or desc")
        order_parts.append(f"{result_columns[identifier]} {direction.upper()}")
        normalized_order.append({"field": identifier, "direction": direction})
    if order_parts:
        sql += "\nORDER BY " + ", ".join(order_parts)

    max_rows = _positive_row_limit(plan.get("max_rows", 5000))
    query_limit = max_rows + 1
    sql += "\nLIMIT " + str(query_limit)
    normalized_plan = {
        "semantic_model": str(model["name"]),
        "metric_ids": metric_ids,
        "derived_metrics": [
            {
                "name": metric["name"],
                "description": metric["description"],
                "assumptions": metric["assumptions"],
                "expression": _snowflake_expression(metric),
                "referenced_fields": metric["referenced_fields"],
                "unpromoted": True,
            }
            for metric in derived_metrics
        ],
        "dimensions": [str(name) for name in dimension_names],
        "derived_dimensions": [
            {
                "name": item["name"],
                "description": item["description"],
                "assumptions": item["assumptions"],
                "expression": _snowflake_expression(item),
                "referenced_fields": item["referenced_fields"],
                "unpromoted": True,
            }
            for _, _, item in derived_dimensions
        ],
        "time_dimensions": [
            {
                "name": item["name"],
                "field": item["source_field"],
                "grain": item["grain"],
            }
            for _, _, item in time_dimensions
        ],
        "filters": filters,
        "time_range": normalized_time_range,
        "having": normalized_having,
        "calculations": normalized_calculations,
        "order_by": normalized_order,
        "max_rows": max_rows,
    }
    request_scoped_logic = [
        *[str(metric["name"]) for metric in derived_metrics],
        *[str(item["name"]) for _, _, item in derived_dimensions],
        *[str(item["name"]) for item in normalized_calculations],
    ]
    return {
        "sql": sql,
        "parameters": parameters,
        "grain": dimension_identifiers,
        "result_grain": result_grain,
        "result_columns": result_columns,
        "model": model["name"],
        "max_rows": max_rows,
        "query_limit": query_limit,
        "period": normalized_time_range,
        "normalized_plan": normalized_plan,
        "metric_definitions": [
            {
                "name": str(metric["name"]),
                "description": metric.get("description"),
                "expression": _snowflake_expression(metric),
                "unpromoted": bool(metric.get("unpromoted", False)),
                "assumptions": metric.get("assumptions", []),
            }
            for metric in selected_metrics
        ],
        "metric_source": (
            "derived" if derived_metrics else "promoted" if selected_metrics else "none"
        ),
        "unpromoted": bool(request_scoped_logic),
        "request_scoped_logic": request_scoped_logic,
        "referenced_objects": sorted(str(dataset["source"]).upper() for dataset in used),
    }
