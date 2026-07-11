from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

MAX_REQUEST_BYTES = 2_000_000


class ContractError(ValueError):
    """Raised when a typed tool request violates its contract."""


def read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise ContractError(f"input file does not exist: {source}")
    if source.stat().st_size > MAX_REQUEST_BYTES:
        raise ContractError(f"input exceeds {MAX_REQUEST_BYTES} bytes")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON input: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("request must be a JSON object")
    return value


def require_string(request: dict[str, Any], name: str) -> str:
    value = request.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")
    return value.strip()


def envelope(request: dict[str, Any], status: str, **payload: Any) -> dict[str, Any]:
    request_id = request.get("request_id", "unknown")
    return {"request_id": str(request_id), "status": status, **payload}


def write_json_atomic(path: str | Path, value: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
