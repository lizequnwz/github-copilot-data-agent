from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable

import sqlglot
from sqlglot import exp


class SQLSafetyError(ValueError):
    pass


@dataclass(frozen=True)
class SQLValidation:
    valid: bool
    statement_type: str
    referenced_objects: tuple[str, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


_FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Merge,
    exp.Command,
    exp.Transaction,
)
_UNSAFE_TEXT = re.compile(
    r"(?is)(?:@[%~\w]|\b(?:PUT|GET|COPY|REMOVE|LIST)\s+@|\bSYSTEM\$|\bEXECUTE\s+IMMEDIATE\b)"
)


def _normalize_object(table: exp.Table) -> str:
    parts = [table.catalog, table.db, table.name]
    return ".".join(str(part).upper() for part in parts if part)


def validate_sql(
    sql: str,
    *,
    blocked_schemas: Iterable[str] = (),
    allowed_objects: Iterable[str] = (),
) -> SQLValidation:
    if not isinstance(sql, str) or not sql.strip():
        raise SQLSafetyError("sql must be a non-empty string")
    if len(sql.encode("utf-8")) > 500_000:
        raise SQLSafetyError("sql exceeds 500000 bytes")
    parse_sql = re.sub(r"%s\b", "NULL", sql)
    try:
        statements = sqlglot.parse(parse_sql, read="snowflake")
    except sqlglot.errors.ParseError as exc:
        raise SQLSafetyError(f"Snowflake SQL parse failed: {exc}") from exc
    if len(statements) != 1:
        raise SQLSafetyError("exactly one SQL statement is required")
    statement = statements[0]
    if statement is None:
        raise SQLSafetyError("empty SQL statement")
    if any(statement.find(node_type) is not None for node_type in _FORBIDDEN_NODES):
        raise SQLSafetyError("only read-only SELECT/WITH queries are executable")
    if not isinstance(statement, exp.Query):
        raise SQLSafetyError("only parsed SELECT/WITH queries are executable")
    if _UNSAFE_TEXT.search(sql):
        raise SQLSafetyError(
            "stages, file operations, dynamic SQL, and system functions are blocked"
        )
    if any(isinstance(star, exp.Star) for star in statement.find_all(exp.Star)):
        raise SQLSafetyError("SELECT * is not allowed")

    cte_names = {cte.alias_or_name.upper() for cte in statement.find_all(exp.CTE)}
    objects = tuple(
        sorted(
            {
                name
                for table in statement.find_all(exp.Table)
                if (name := _normalize_object(table)) and name not in cte_names
            }
        )
    )
    blocked = tuple(item.upper() for item in blocked_schemas)
    for name in objects:
        if any(
            name == item or name.startswith(f"{item}.") or f".{item}." in f".{name}."
            for item in blocked
        ):
            raise SQLSafetyError(f"referenced object is blocked: {name}")
    allowed = {item.upper() for item in allowed_objects}
    if allowed and any(name not in allowed for name in objects):
        unknown = sorted(name for name in objects if name not in allowed)
        raise SQLSafetyError(f"referenced object is not allowlisted: {', '.join(unknown)}")
    warnings: list[str] = []
    if statement.args.get("limit") is None:
        warnings.append("no explicit LIMIT; execution tool will enforce the row cap")
    return SQLValidation(True, "SELECT", objects, tuple(warnings))
