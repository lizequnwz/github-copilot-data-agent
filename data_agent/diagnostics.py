from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from data_agent.config import Settings
from data_agent.snowflake import connection_check


def _value(value: Any) -> str:
    return str(value) if value not in {None, ""} else "session default"


def _safe_error(error: Exception, settings: Settings | None) -> str:
    message = str(error).strip() or type(error).__name__
    if settings and settings.authenticator == "oauth":
        token = os.environ.get(settings.oauth_token_env)
        if token:
            message = message.replace(token, "[redacted]")
    return message


def _fix(error: str, config_path: str) -> str:
    if error.startswith("snowflake.") and " " not in error:
        return f"set {error} in {config_path}"
    return error


def run_check(
    config_path: str,
    *,
    connect: Callable[[dict[str, Any]], dict[str, Any]] = connection_check,
) -> tuple[int, list[str]]:
    lines = ["Snowflake connection check"]
    settings: Settings | None = None
    try:
        settings = Settings.from_file(config_path)
    except (ValueError, OSError) as error:
        return 2, [*lines, f"Configuration: {_safe_error(error, None)}"]

    authentication = settings.public_authentication()
    if settings.oauth_url:
        lines.append(f"OAuth URL: {settings.oauth_url}")
    else:
        lines.append(f"Authentication: {authentication['mode']}")
    lines.extend(
        [
            f"Account: {_value(settings.account)}",
            f"Region: {_value(settings.region)}",
        ]
    )
    if settings.user:
        lines.append(f"User: {settings.user}")
    if settings.authenticator == "oauth":
        availability = "available" if authentication["token_available"] else "missing"
        lines.append(f"OAuth token: {settings.oauth_token_env} ({availability})")
    preferred = ", ".join(
        f"{name}={value}"
        for name in ("role", "warehouse", "database", "schema")
        if (value := getattr(settings, name))
    )
    lines.append(f"Preferred context: {preferred or 'Snowflake session defaults'}")

    errors = settings.readiness_errors()
    if errors:
        lines.append("Status: configuration required")
        lines.extend(f"Fix: {_fix(error, config_path)}" for error in errors)
        return 2, lines

    try:
        result = connect(
            {
                "request_id": "snowflake-connection-check",
                "config_path": config_path,
                # Running this explicit command confirms the displayed non-secret context.
                "configuration_confirmed": True,
            }
        )
    except Exception as error:  # Connector errors vary by installed connector version.
        lines.extend(["Status: connection failed", f"Fix: {_safe_error(error, settings)}"])
        return 2, lines

    actual = result.get("actual_context", {})
    lines.append("Status: connected")
    lines.append(
        "Effective context: "
        + ", ".join(
            f"{name}={_value(actual.get(name))}"
            for name in ("user", "role", "warehouse", "database", "schema")
        )
    )
    lines.extend(f"Warning: {warning}" for warning in result.get("warnings", []))
    return 0, lines
