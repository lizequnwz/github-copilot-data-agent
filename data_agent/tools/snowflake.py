from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from typing import Any

from data_agent.config import Settings
from data_agent.io import ContractError, envelope, require_string
from data_agent.security.sql import validate_sql

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_QUALIFIED_OBJECT = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_$]*\.[A-Za-z_][A-Za-z0-9_$]*\.[A-Za-z_][A-Za-z0-9_$]*$"
)
_SENSITIVE_NAME = re.compile(
    r"(?i)(?:^|_)(?:email|phone|address|ssn|social_security|tax_id|birth|dob|password|token|secret|first_name|last_name|full_name)(?:$|_)"
)


def load_settings(request: dict[str, Any]) -> Settings:
    path = request.get("config_path", "snowflake_config.yaml")
    return Settings.from_file(str(path))


def config_check(request: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings(request)
    errors = settings.readiness_errors()
    if settings.authenticator != "externalbrowser":
        errors.append("snowflake.authenticator must be externalbrowser for the preferred SSO flow")
    return envelope(
        request,
        "ready" if not errors else "configuration_required",
        configuration=settings.public_context(),
        errors=errors,
        confirmation_required=True,
        warnings=[],
    )


def _connect(request: dict[str, Any], settings: Settings) -> Any:
    if request.get("configuration_confirmed") is not True:
        raise ContractError(
            "configuration_confirmed must be true after the user confirms the displayed context"
        )
    errors = settings.readiness_errors()
    if errors:
        raise ContractError(f"Snowflake configuration has placeholders: {', '.join(errors)}")
    if settings.authenticator != "externalbrowser":
        raise ContractError("only externalbrowser authentication is enabled by this project")
    try:
        import snowflake.connector  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ContractError("Snowflake connector missing; run uv sync --extra snowflake") from exc
    return snowflake.connector.connect(
        account=settings.account,
        user=settings.user,
        authenticator="externalbrowser",
        role=settings.role,
        warehouse=settings.warehouse,
        database=settings.database,
        schema=settings.schema,
        login_timeout=settings.timeout_seconds,
        network_timeout=settings.timeout_seconds,
        session_parameters={
            "QUERY_TAG": settings.query_tag,
            "STATEMENT_TIMEOUT_IN_SECONDS": settings.timeout_seconds,
            "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": settings.timeout_seconds,
        },
    )


def connection_check(request: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings(request)
    started = time.monotonic()
    with _connect(request, settings) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE(), "
                "CURRENT_DATABASE(), CURRENT_SCHEMA()"
            )
            row = cursor.fetchone()
            query_id = cursor.sfqid
        finally:
            cursor.close()
    actual = dict(zip(["user", "role", "warehouse", "database", "schema"], row))
    if str(actual["role"]).upper() != settings.role.upper():
        return envelope(
            request,
            "context_mismatch",
            query_id=query_id,
            actual_context=actual,
            warnings=["effective role differs from configured role"],
        )
    return envelope(
        request,
        "success",
        query_id=query_id,
        actual_context=actual,
        execution_seconds=round(time.monotonic() - started, 3),
        warnings=[],
    )


def execute_readonly(request: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings(request)
    sql = require_string(request, "sql")
    validation = validate_sql(
        sql, blocked_schemas=settings.blocked_schemas, allowed_objects=settings.allowed_objects
    )
    requested_rows = int(request.get("max_rows", settings.max_rows))
    max_rows = min(max(requested_rows, 1), settings.max_rows)
    parameters = request.get("parameters", [])
    if not isinstance(parameters, (list, dict)):
        raise ContractError("parameters must be an array or object")
    started = time.monotonic()
    with _connect(request, settings) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(sql, parameters=params_to_tuple(parameters))
            columns = [item[0] for item in cursor.description or []]
            fetched = cursor.fetchmany(max_rows + 1)
            query_id = cursor.sfqid
        finally:
            cursor.close()
    truncated = len(fetched) > max_rows
    rows = [[serialize(value) for value in row] for row in fetched[:max_rows]]
    result_bytes = len(json.dumps(rows, default=str).encode("utf-8"))
    if result_bytes > settings.max_bytes:
        raise ContractError(f"result exceeds configured byte cap ({settings.max_bytes})")
    return envelope(
        request,
        "success",
        query_id=query_id,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        execution_seconds=round(time.monotonic() - started, 3),
        role=settings.role,
        validation=validation.as_dict(),
        warnings=list(validation.warnings),
    )


def search_objects(request: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings(request)
    term = require_string(request, "query")
    database = _identifier(settings.database, "configured database")
    sql = f"""SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE, COMMENT
FROM {database}.INFORMATION_SCHEMA.TABLES
WHERE TABLE_NAME ILIKE %s OR COMMENT ILIKE %s
ORDER BY TABLE_SCHEMA, TABLE_NAME
LIMIT 200"""
    generated = {**request, "sql": sql, "parameters": [f"%{term}%", f"%{term}%"], "max_rows": 200}
    return _execute_generated(generated, settings)


def describe_object(request: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings(request)
    object_name = require_string(request, "object")
    _validate_requested_object(object_name, settings)
    database, schema, name = _qualified_parts(object_name)
    sql = f"""SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME,
ORDINAL_POSITION, DATA_TYPE, IS_NULLABLE, COMMENT
FROM {database}.INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
ORDER BY ORDINAL_POSITION
LIMIT 500"""
    generated = {
        **request,
        "sql": sql,
        "parameters": [schema.upper(), name.upper()],
        "max_rows": 500,
    }
    return _execute_generated(generated, settings)


def sample_values(request: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings(request)
    object_name = require_string(request, "object")
    _validate_requested_object(object_name, settings)
    column = _identifier(require_string(request, "column"), "column")
    if _SENSITIVE_NAME.search(column) and not (
        settings.allow_sensitive_sampling and request.get("sensitive_authorized") is True
    ):
        raise ContractError("sensitive-looking column sampling is not enabled in configuration")
    limit = min(max(int(request.get("limit", 20)), 1), 100)
    sql = (
        f"SELECT {column} AS SAMPLE_VALUE, COUNT({column}) AS VALUE_COUNT "
        f"FROM {object_name} WHERE {column} IS NOT NULL GROUP BY {column} "
        f"ORDER BY VALUE_COUNT DESC LIMIT {limit}"
    )
    return _execute_generated(
        {**request, "sql": sql, "parameters": [], "max_rows": limit}, settings
    )


def profile_table(request: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings(request)
    object_name = require_string(request, "object")
    _validate_requested_object(object_name, settings)
    columns = request.get("columns", [])
    if not isinstance(columns, list) or not columns or len(columns) > 20:
        raise ContractError("columns must contain 1 to 20 selected column names")
    safe_columns = [_identifier(str(column), "column") for column in columns]
    expressions = ["COUNT(1) AS ROW_COUNT"]
    for column in safe_columns:
        expressions.extend(
            [
                f"COUNT_IF({column} IS NULL) AS {column}_NULL_COUNT",
                f"APPROX_COUNT_DISTINCT({column}) AS {column}_APPROX_DISTINCT",
            ]
        )
    sql = "SELECT " + ", ".join(expressions) + f" FROM {object_name} LIMIT 1"
    return _execute_generated({**request, "sql": sql, "parameters": [], "max_rows": 1}, settings)


def cancel_query(request: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings(request)
    query_id = require_string(request, "query_id")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", query_id):
        raise ContractError("query_id format is invalid")
    with _connect(request, settings) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT SYSTEM$CANCEL_QUERY(%s)", (query_id,))
            result = cursor.fetchone()
        finally:
            cursor.close()
    return envelope(
        request, "success", cancelled_query_id=query_id, result=serialize(result[0]), warnings=[]
    )


def _execute_generated(request: dict[str, Any], settings: Settings) -> dict[str, Any]:
    # Generated metadata/profiling SQL is built only from validated identifiers and fixed templates.
    sql = require_string(request, "sql")
    validation = validate_sql(sql, blocked_schemas=settings.blocked_schemas)
    max_rows = min(max(int(request.get("max_rows", settings.max_rows)), 1), settings.max_rows)
    parameters = request.get("parameters", [])
    with _connect(request, settings) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(sql, params_to_tuple(parameters))
            columns = [item[0] for item in cursor.description or []]
            fetched = cursor.fetchmany(max_rows + 1)
            query_id = cursor.sfqid
        finally:
            cursor.close()
    rows = [[serialize(value) for value in row] for row in fetched[:max_rows]]
    if len(json.dumps(rows, default=str).encode()) > settings.max_bytes:
        raise ContractError("result exceeds configured byte cap")
    return envelope(
        request,
        "success",
        query_id=query_id,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=len(fetched) > max_rows,
        role=settings.role,
        validation=validation.as_dict(),
        warnings=list(validation.warnings),
    )


def _identifier(value: str | None, label: str) -> str:
    if not value or not _IDENTIFIER.fullmatch(value):
        raise ContractError(f"{label} must be an unquoted Snowflake identifier")
    return value


def _qualified_parts(value: str) -> tuple[str, str, str]:
    if not _QUALIFIED_OBJECT.fullmatch(value):
        raise ContractError("object must be DATABASE.SCHEMA.OBJECT using unquoted identifiers")
    database, schema, name = value.split(".")
    return database, schema, name


def _validate_requested_object(value: str, settings: Settings) -> None:
    database, _, _ = _qualified_parts(value)
    if settings.database and database.upper() != settings.database.upper():
        raise ContractError("object database must match the configured database")
    if settings.allowed_objects and value.upper() not in settings.allowed_objects:
        raise ContractError("object is not included in configured allowed_objects")


def params_to_tuple(value: list[Any] | dict[str, Any]) -> Any:
    return tuple(value) if isinstance(value, list) else value


def serialize(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "as_tuple"):
        return str(value)
    return value
