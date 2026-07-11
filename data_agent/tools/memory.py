from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from data_agent.io import ContractError, envelope, require_string


def propose(request: dict[str, Any]) -> dict[str, Any]:
    concept = require_string(request, "concept")
    evidence = request.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ContractError("evidence must be a non-empty array")
    if any(key in str(request).casefold() for key in ("password=", "private_key", "access_token")):
        raise ContractError("proposal appears to contain secret material")
    proposal_id = str(
        request.get("proposal_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", concept.casefold()).strip("-")[:60]
    root = Path(str(request.get("pending_dir", "memory/pending"))).resolve()
    if root.name != "pending" or root.parent.name != "memory":
        raise ContractError("pending_dir must be memory/pending")
    target = root / f"{proposal_id}-{slug}.yaml"
    if target.exists():
        raise ContractError("proposal already exists")
    record = {
        "id": proposal_id,
        "status": "pending",
        "concept": concept,
        "scope": request.get("scope", "domain"),
        "candidate_definitions": request.get("candidate_definitions", []),
        "evidence": evidence,
        "confidence": request.get("confidence", "low"),
        "likely_owner": request.get("likely_owner"),
        "request_id": request.get("request_id"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    root.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    return envelope(
        request, "success", proposal_id=proposal_id, proposal_path=str(target), warnings=[]
    )
