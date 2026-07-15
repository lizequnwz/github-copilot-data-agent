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
from data_agent.semantic.review_workspace import (  # noqa: E402
    compile_decisions,
    load_decisions,
    review_paths,
    serve_review,
    write_static_review,
)


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
    parser.add_argument("--review-ui", action="store_true")
    parser.add_argument("--review-port", type=int, default=0)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--review-decisions", type=Path)
    parser.add_argument("--verify-snowflake", action="store_true")
    parser.add_argument("--no-promote", action="store_true")
    parser.add_argument("--config-path", default="snowflake_config.yaml")
    parser.add_argument("--configuration-confirmed", action="store_true")
    parser.add_argument("--request-id", default="osi-semantic-model-build")
    args = parser.parse_args()
    review_modes = sum(
        bool(value) for value in (args.review_patch, args.review_ui, args.review_decisions)
    )
    if review_modes > 1:
        parser.error("use only one of --review-patch, --review-ui, or --review-decisions")
    if args.verify_snowflake and review_modes == 0:
        parser.error("--verify-snowflake requires a review mode")
    if args.review_port and not args.review_ui:
        parser.error("--review-port requires --review-ui")
    if args.no_open and not args.review_ui:
        parser.error("--no-open requires --review-ui")

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
    warnings = response.get("warnings", [])
    for warning in warnings[:10]:
        print(f"Review: {warning}")
    if len(warnings) > 10:
        print(f"Review: {len(warnings) - 10} additional issues are listed in the manifest.")
    if response.get("status") != "success":
        return 2
    paths = review_paths(response["raw_model_path"], response["manifest_path"])
    if args.review_ui:
        result = serve_review(
            paths,
            port=args.review_port,
            open_browser=not args.no_open,
            request_id=args.request_id,
            verify_snowflake=args.verify_snowflake,
            config_path=args.config_path,
            configuration_confirmed=args.configuration_confirmed,
            promote_if_clean=not args.no_promote,
        )
        print(f"Review finished: {result['finished']}")
        return 0
    patch_path = args.review_patch
    if args.review_decisions is not None:
        decisions = load_decisions(args.review_decisions, paths.raw)
        compile_decisions(decisions, paths)
        write_static_review(paths)
        patch_path = paths.patch
        print(f"Decisions: {paths.decisions}")
        print(f"Audited patch: {paths.patch}")
    if patch_path is not None:
        reviewed = review_semantic(
            {
                "request_id": args.request_id,
                "raw_model_path": response["raw_model_path"],
                "manifest_path": response["manifest_path"],
                "patch_path": str(patch_path),
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
        if args.review_decisions is not None:
            write_static_review(
                paths,
                promotion_enabled=not args.no_promote,
                verify_snowflake=args.verify_snowflake,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
