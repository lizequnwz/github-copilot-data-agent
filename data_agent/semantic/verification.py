from __future__ import annotations

import re
from typing import Any

from data_agent.io import ContractError
from data_agent.security.sql import validate_sql
from data_agent.semantic.compiler import compile_plan
from data_agent.tools.snowflake import _connect, load_settings
from data_agent.tools.snowflake import _context_warnings

_QUALIFIED_OBJECT = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_$]*\.[A-Za-z_][A-Za-z0-9_$]*\.[A-Za-z_][A-Za-z0-9_$]*$"
)


def verify_semantic_model(request: dict[str, Any]) -> dict[str, Any]:
    """Verify OSI sources and expressions in Snowflake without executing model queries."""

    document = request.get("document")
    if not isinstance(document, dict):
        raise ContractError("Snowflake semantic verification requires an OSI document")
    settings = load_settings(request)
    errors: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    checked_objects: list[dict[str, Any]] = []
    checked_expressions: list[dict[str, Any]] = []
    query_ids: list[str] = []
    context_warnings: list[str] = []

    with _connect(request, settings) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE(), "
                "CURRENT_DATABASE(), CURRENT_SCHEMA()"
            )
            context_row = cursor.fetchone()
            if cursor.sfqid:
                query_ids.append(str(cursor.sfqid))
            actual_context = dict(
                zip(["user", "role", "warehouse", "database", "schema"], context_row)
            )
            context_warnings = _context_warnings(settings, actual_context)

            for model in document.get("semantic_model", []):
                if not isinstance(model, dict):
                    continue
                for dataset in model.get("datasets", []):
                    if not isinstance(dataset, dict):
                        continue
                    _verify_dataset(
                        cursor,
                        dataset,
                        settings,
                        checked_objects,
                        checked_expressions,
                        query_ids,
                        errors,
                        skipped,
                    )
                for metric in model.get("metrics", []):
                    if not isinstance(metric, dict):
                        continue
                    _verify_metric(
                        cursor,
                        document,
                        model,
                        metric,
                        settings,
                        checked_expressions,
                        errors,
                        skipped,
                    )
        finally:
            cursor.close()

    status = "failed" if errors else "partial" if skipped else "passed"
    return {
        "status": status,
        "role": settings.role,
        "actual_context": actual_context,
        "checked_objects": checked_objects,
        "checked_expressions": checked_expressions,
        "errors": errors,
        "skipped": skipped,
        "query_ids": query_ids,
        "warnings": context_warnings,
    }


def _verify_dataset(
    cursor: Any,
    dataset: dict[str, Any],
    settings: Any,
    checked_objects: list[dict[str, Any]],
    checked_expressions: list[dict[str, Any]],
    query_ids: list[str],
    errors: list[dict[str, str]],
    skipped: list[dict[str, str]],
) -> None:
    dataset_name = str(dataset.get("name") or "<unnamed>")
    source = str(dataset.get("source") or "")
    if not _QUALIFIED_OBJECT.fullmatch(source):
        errors.append(
            _result(dataset_name, "source", "Source must be an unquoted database.schema.object.")
        )
        return
    database, schema, table = source.split(".")
    if schema.upper() in {str(value).upper() for value in settings.blocked_schemas}:
        errors.append(_result(dataset_name, "source", "Source schema is blocked by configuration."))
        return
    if settings.allowed_objects and source.upper() not in settings.allowed_objects:
        errors.append(_result(dataset_name, "source", "Source is not included in allowed_objects."))
        return
    cursor.execute(
        f"SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COMMENT "
        f"FROM {database}.INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION LIMIT 500",
        (schema.upper(), table.upper()),
    )
    columns = cursor.fetchall()
    if cursor.sfqid:
        query_ids.append(str(cursor.sfqid))
    if not columns:
        errors.append(_result(dataset_name, "source", "Snowflake object has no visible columns."))
        return
    visible_columns = {str(column[0]).upper() for column in columns}
    checked_objects.append(
        {
            "dataset": dataset_name,
            "source": source,
            "column_count": len(columns),
            "query_id": str(cursor.sfqid) if cursor.sfqid else None,
        }
    )

    expressions: list[str] = []
    names: list[str] = []
    for field in dataset.get("fields", []):
        if not isinstance(field, dict):
            continue
        expression = _executable_expression(field)
        if expression is None:
            skipped.append(
                _result(
                    f"{dataset_name}.{field.get('name')}",
                    "expression",
                    "No ANSI_SQL or SNOWFLAKE expression.",
                )
            )
            continue
        physical_reference = re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_$]*\.([A-Za-z_][A-Za-z0-9_$]*)", expression
        )
        if physical_reference and physical_reference.group(1).upper() not in visible_columns:
            errors.append(
                _result(
                    f"{dataset_name}.{field.get('name')}",
                    "column",
                    f"Column {physical_reference.group(1)} is not visible in INFORMATION_SCHEMA.",
                )
            )
        names.append(str(field.get("name") or f"field_{len(names)}"))
        expressions.append(expression)
    if not expressions:
        return
    projections = ", ".join(
        f"{expression} AS CHECK_{index}" for index, expression in enumerate(expressions)
    )
    sql = f"SELECT {projections} FROM {source} AS {dataset_name} LIMIT 0"
    try:
        validate_sql(
            sql,
            blocked_schemas=settings.blocked_schemas,
            allowed_objects=settings.allowed_objects,
        )
        metadata = cursor.describe(sql)
        checked_expressions.append(
            {
                "kind": "dataset_fields",
                "dataset": dataset_name,
                "fields": names,
                "result_column_count": len(metadata),
            }
        )
    except Exception as exc:
        errors.append(_result(dataset_name, "expression", f"{type(exc).__name__}: {exc}"))


def _verify_metric(
    cursor: Any,
    document: dict[str, Any],
    model: dict[str, Any],
    metric: dict[str, Any],
    settings: Any,
    checked_expressions: list[dict[str, Any]],
    errors: list[dict[str, str]],
    skipped: list[dict[str, str]],
) -> None:
    metric_name = str(metric.get("name") or "<unnamed>")
    if _executable_expression(metric) is None:
        skipped.append(_result(metric_name, "metric", "No ANSI_SQL or SNOWFLAKE expression."))
        return
    try:
        compiled = compile_plan(
            document,
            {
                "semantic_model": model.get("name"),
                "metric_ids": [metric_name],
                "dimensions": [],
                "max_rows": 1,
            },
        )
        validate_sql(
            compiled["sql"],
            blocked_schemas=settings.blocked_schemas,
            allowed_objects=settings.allowed_objects,
        )
        metadata = cursor.describe(compiled["sql"])
        checked_expressions.append(
            {
                "kind": "metric",
                "metric": metric_name,
                "result_column_count": len(metadata),
            }
        )
    except Exception as exc:
        errors.append(_result(metric_name, "metric", f"{type(exc).__name__}: {exc}"))


def _executable_expression(item: dict[str, Any]) -> str | None:
    dialects = item.get("expression", {}).get("dialects", [])
    for wanted in ("SNOWFLAKE", "ANSI_SQL"):
        for dialect in dialects if isinstance(dialects, list) else []:
            if (
                isinstance(dialect, dict)
                and dialect.get("dialect") == wanted
                and isinstance(dialect.get("expression"), str)
            ):
                return str(dialect["expression"])
    return None


def _result(element: str, kind: str, message: str) -> dict[str, str]:
    return {"element": element, "kind": kind, "message": message}
