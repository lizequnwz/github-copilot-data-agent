from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from data_agent.semantic.conversion import SUPPORTED_SOURCE_TYPES, convert_semantic  # noqa: E402
from data_agent.semantic.review import review_semantic  # noqa: E402


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
    parser.add_argument("--review-patch", type=Path)
    parser.add_argument("--verify-snowflake", action="store_true")
    parser.add_argument("--no-promote", action="store_true")
    parser.add_argument("--config-path", default="snowflake_config.yaml")
    parser.add_argument("--configuration-confirmed", action="store_true")
    parser.add_argument("--request-id", default="osi-semantic-model-build")
    args = parser.parse_args()
    if args.verify_snowflake and args.review_patch is None:
        parser.error("--verify-snowflake requires --review-patch")

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
    print(f"Raw model: {response.get('raw_model_path')}")
    print(f"Manifest: {response.get('manifest_path')}")
    for warning in response.get("warnings", []):
        print(f"Review: {warning}")
    if response.get("status") != "success":
        return 2
    if args.review_patch is not None:
        reviewed = review_semantic(
            {
                "request_id": args.request_id,
                "raw_model_path": response["raw_model_path"],
                "manifest_path": response["manifest_path"],
                "patch_path": str(args.review_patch),
                "verify_snowflake": args.verify_snowflake,
                "config_path": args.config_path,
                "configuration_confirmed": args.configuration_confirmed,
                "promote_if_clean": not args.no_promote,
            }
        )
        print(f"Reviewed model: {reviewed.get('final_model_path')}")
        print(f"Analysis ready: {reviewed.get('analysis_ready')}")
        print(f"Promoted: {reviewed.get('promoted')}")
        if reviewed.get("promoted_model_path"):
            print(f"Promoted model: {reviewed.get('promoted_model_path')}")
        print(f"Snowflake verification: {reviewed.get('warehouse_verification', {}).get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
