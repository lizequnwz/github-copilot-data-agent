from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

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
    parameters: list[Any] | None = None,
    require_parameterized_predicates: bool = False,
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
    if _has_projection_wildcard(statement):
        raise SQLSafetyError("SELECT * is not allowed")
    if require_parameterized_predicates:
        if parameters is None:
            raise SQLSafetyError("parameterized SQL requires a parameters array")
        placeholder_count = len(re.findall(r"(?<!%)%s\b", sql))
        if placeholder_count != len(parameters):
            raise SQLSafetyError(
                "positional placeholder count must match the parameters array"
            )
        if _has_unparameterized_predicate_value(statement):
            raise SQLSafetyError("filter and join values must use positional parameters")

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


def query_projection_names(sql: str) -> tuple[str, ...]:
    """Return explicit top-level output names for a validated query."""

    statement = _parse_single_query(sql)
    if not isinstance(statement, exp.Select):
        raise SQLSafetyError("ad hoc SQL must have a SELECT as its outer query")
    names: list[str] = []
    for projection in statement.expressions:
        name = projection.alias_or_name
        if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", name):
            raise SQLSafetyError("every ad hoc projection must have a safe output name or alias")
        names.append(name)
    if len(set(name.casefold() for name in names)) != len(names):
        raise SQLSafetyError("ad hoc projection names must be unique")
    return tuple(names)


def explicit_query_limit(sql: str) -> int | None:
    statement = _parse_single_query(sql)
    limit = statement.args.get("limit")
    if limit is None:
        return None
    value = limit.expression
    if not isinstance(value, exp.Literal) or not value.is_int:
        raise SQLSafetyError("LIMIT must be a literal integer")
    return int(value.this)


def _parse_single_query(sql: str) -> exp.Query:
    parse_sql = re.sub(r"%s\b", "NULL", sql)
    try:
        statements = sqlglot.parse(parse_sql, read="snowflake")
    except sqlglot.errors.ParseError as exc:
        raise SQLSafetyError(f"Snowflake SQL parse failed: {exc}") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise SQLSafetyError("exactly one SELECT/WITH query is required")
    return statements[0]


def _has_projection_wildcard(statement: Any) -> bool:
    for star in statement.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            return True
    return False


def _has_unparameterized_predicate_value(statement: Any) -> bool:
    comparisons = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Like, exp.ILike)
    for comparison in statement.find_all(*comparisons):
        right = comparison.expression
        left = comparison.this
        if _contains_literal(right) or isinstance(left, (exp.Literal, exp.Interval)):
            return True
    for between in statement.find_all(exp.Between):
        if _contains_literal(between.args.get("low")) or _contains_literal(
            between.args.get("high")
        ):
            return True
    for item in statement.find_all(exp.In):
        if any(_contains_literal(value) for value in item.expressions):
            return True
    return False


def _contains_literal(value: exp.Expression | None) -> bool:
    if value is None:
        return False
    return isinstance(value, (exp.Literal, exp.Interval)) or value.find(exp.Literal) is not None
