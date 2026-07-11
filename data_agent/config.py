from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Settings:
    account: str | None
    user: str | None
    authenticator: str
    role: str
    warehouse: str
    database: str | None
    schema: str | None
    query_tag: str
    max_rows: int
    max_bytes: int
    timeout_seconds: int
    blocked_schemas: tuple[str, ...]
    allowed_objects: tuple[str, ...]
    allow_sensitive_sampling: bool

    @classmethod
    def from_file(cls, path: str | Path = "snowflake_config.yaml") -> "Settings":
        source = Path(path)
        if not source.is_file():
            raise ValueError(f"Snowflake configuration not found: {source}")
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Snowflake configuration must be a YAML object")
        sf = _mapping(raw.get("snowflake"), "snowflake")
        limits = _mapping(raw.get("limits", {}), "limits")
        policy = _mapping(raw.get("policy", {}), "policy")
        return cls(
            account=_optional_string(sf.get("account")),
            user=_optional_string(sf.get("user")),
            authenticator=str(sf.get("authenticator", "externalbrowser")),
            role=str(sf.get("role", "DATA_AGENT_ANALYST_READONLY")),
            warehouse=str(sf.get("warehouse", "DATA_AGENT_WH")),
            database=_optional_string(sf.get("database")),
            schema=_optional_string(sf.get("schema")),
            query_tag=str(sf.get("query_tag", "enterprise_data_agent")),
            max_rows=_config_positive_int(limits, "max_rows", 5000),
            max_bytes=_config_positive_int(limits, "max_result_bytes", 5_000_000),
            timeout_seconds=_config_positive_int(limits, "timeout_seconds", 60),
            blocked_schemas=tuple(str(v).upper() for v in policy.get("blocked_schemas", [])),
            allowed_objects=tuple(str(v).upper() for v in policy.get("allowed_objects", [])),
            allow_sensitive_sampling=bool(policy.get("allow_sensitive_sampling", False)),
        )

    def readiness_errors(self) -> list[str]:
        fields = {
            "snowflake.account": self.account,
            "snowflake.user": self.user,
            "snowflake.database": self.database,
            "snowflake.schema": self.schema,
        }
        return [name for name, value in fields.items() if not value or "REPLACE_WITH" in value]

    def public_context(self) -> dict[str, str | None]:
        return {
            "account": self.account,
            "user": self.user,
            "authenticator": self.authenticator,
            "role": self.role,
            "warehouse": self.warehouse,
            "database": self.database,
            "schema": self.schema,
        }


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def _optional_string(value: Any) -> str | None:
    return str(value).strip() if value is not None else None


def _config_positive_int(values: dict[str, Any], name: str, default: int) -> int:
    try:
        value = int(values.get(name, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value
