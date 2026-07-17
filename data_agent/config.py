from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Settings:
    account: str | None
    user: str | None
    authenticator: str
    role: str | None
    warehouse: str | None
    database: str | None
    schema: str | None
    query_tag: str
    max_rows: int
    max_bytes: int
    timeout_seconds: int
    blocked_schemas: tuple[str, ...]
    allowed_objects: tuple[str, ...]
    allow_sensitive_sampling: bool
    oauth_token_env: str = "SNOWFLAKE_OAUTH_TOKEN"
    oauth_url: str | None = None
    region: str | None = None

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
        access = _mapping(raw.get("access", {}), "access")
        oauth_url = _optional_string(sf.get("oauth_url"))
        return cls(
            account=_optional_string(sf.get("account")),
            user=_optional_string(sf.get("user")),
            authenticator=(
                oauth_url
                or str(sf.get("authenticator", "externalbrowser")).strip().casefold()
            ),
            role=_optional_string(sf.get("role")),
            warehouse=_optional_string(
                sf.get("default_warehouse", sf.get("warehouse"))
            ),
            database=_optional_string(sf.get("database")),
            schema=_optional_string(sf.get("schema")),
            query_tag=str(sf.get("query_tag", "copilot_data_agent")),
            max_rows=_config_positive_int(limits, "max_rows", 5000),
            max_bytes=_config_positive_int(limits, "max_result_bytes", 5_000_000),
            timeout_seconds=_config_positive_int(limits, "timeout_seconds", 60),
            blocked_schemas=tuple(
                str(v).upper()
                for v in access.get(
                    "blocked_schemas",
                    ["SNOWFLAKE.ACCOUNT_USAGE", "RAW_PII"],
                )
            ),
            allowed_objects=tuple(str(v).upper() for v in access.get("allowed_objects", [])),
            allow_sensitive_sampling=bool(access.get("allow_sensitive_sampling", False)),
            oauth_token_env=str(
                sf.get("oauth_token_env", "SNOWFLAKE_OAUTH_TOKEN")
            ).strip(),
            oauth_url=oauth_url,
            region=_optional_string(sf.get("region")),
        )

    def readiness_errors(self) -> list[str]:
        fields = {
            "snowflake.account": self.account,
        }
        optional_fields = {
            "snowflake.oauth_url": self.oauth_url,
            "snowflake.region": self.region,
            "snowflake.default_warehouse": self.warehouse,
            "snowflake.database": self.database,
            "snowflake.schema": self.schema,
            "snowflake.role": self.role,
        }
        fields.update(
            (name, value) for name, value in optional_fields.items() if value is not None
        )
        errors = [name for name, value in fields.items() if not value or "REPLACE_WITH" in value]
        if (
            self.authenticator not in {"externalbrowser", "oauth"}
            and not self.authenticator.startswith(("https://", "http://"))
        ):
            errors.append(
                "snowflake.oauth_url must be an HTTP(S) URL, or "
                "snowflake.authenticator must be externalbrowser or oauth"
            )
        if self.authenticator == "oauth":
            if not self.oauth_token_env:
                errors.append("snowflake.oauth_token_env must name an environment variable")
            elif not os.environ.get(self.oauth_token_env):
                errors.append(f"environment variable {self.oauth_token_env} is not set")
        return errors

    def public_context(self) -> dict[str, str | None]:
        return {
            "oauth_url": self.oauth_url,
            "account": self.account,
            "region": self.region,
            "user": self.user,
            "authenticator": self.authenticator,
            "role": self.role,
            "default_warehouse": self.warehouse,
            "warehouse": self.warehouse,
            "database": self.database,
            "schema": self.schema,
        }

    def public_authentication(self) -> dict[str, str | bool | None]:
        """Return authentication readiness without ever exposing credential material."""

        return {
            "mode": self.authenticator,
            "token_env": self.oauth_token_env if self.authenticator == "oauth" else None,
            "token_available": (
                bool(os.environ.get(self.oauth_token_env)) if self.authenticator == "oauth" else None
            ),
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
