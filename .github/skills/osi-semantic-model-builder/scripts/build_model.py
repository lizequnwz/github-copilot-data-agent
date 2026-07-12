from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from data_agent.semantic.conversion import SUPPORTED_SOURCE_TYPES, convert_semantic  # noqa: E402


def _json_object(path: Path | None, label: str) -> dict[str, Any]:
    if path is None:
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert exported BI semantic metadata into an Apache Ossie model."
    )
    parser.add_argument("source")
    parser.add_argument("--model-name")
    parser.add_argument("--source-type", choices=sorted(SUPPORTED_SOURCE_TYPES), default="auto")
    parser.add_argument("--descriptor", type=Path)
    parser.add_argument("--source-map", type=Path)
    parser.add_argument("--field-map", type=Path)
    parser.add_argument("--request-id", default="osi-semantic-model-build")
    args = parser.parse_args()

    response = convert_semantic(
        {
            "request_id": args.request_id,
            "source_path": args.source,
            "source_type": args.source_type,
            "model_name": args.model_name,
            "descriptor_path": str(args.descriptor) if args.descriptor else None,
            "source_map": _json_object(args.source_map, "--source-map"),
            "field_map": _json_object(args.field_map, "--field-map"),
        }
    )
    summary = response.get("summary") or {}
    print(f"Source type: {response.get('source_type')}")
    print(f"Schema valid: {response.get('schema_valid')}")
    print(
        "Objects: "
        f"{summary.get('datasets', 0)} datasets, {summary.get('fields', 0)} fields, "
        f"{summary.get('relationships', 0)} relationships, {summary.get('metrics', 0)} metrics"
    )
    print(f"Blocking issues: {response.get('blocking_issue_count', 0)}")
    print(f"Model: {response.get('model_path')}")
    print(f"Manifest: {response.get('manifest_path')}")
    for warning in response.get("warnings", []):
        print(f"Review: {warning}")
    return 0 if response.get("status") == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
