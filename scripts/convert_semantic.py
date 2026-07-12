from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.semantic.conversion import SUPPORTED_SOURCE_TYPES, convert_semantic


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Convert Power BI, Tableau .twb/.tds/.tde, generic, neutral IR, or Ossie metadata to a candidate Ossie model."
    )
    result.add_argument(
        "source", help="PBIP/TMDL directory, Tableau .twb/.tds/.tde, or JSON/YAML semantic file"
    )
    result.add_argument(
        "--source-type", choices=sorted(SUPPORTED_SOURCE_TYPES), default="auto"
    )
    result.add_argument("--model-name")
    result.add_argument(
        "--descriptor",
        type=Path,
        help="Optional .tds descriptor for a .tde extract when it is not a same-named sibling",
    )
    result.add_argument(
        "--source-map",
        type=Path,
        help="Optional JSON object mapping source dataset names to DATABASE.SCHEMA.OBJECT",
    )
    result.add_argument(
        "--field-map",
        type=Path,
        help="Optional JSON object mapping Tableau display fields to unquoted SQL column aliases",
    )
    result.add_argument("--request-id", default="semantic-conversion")
    return result


def main() -> int:
    args = parser().parse_args()
    source_map = {}
    field_map = {}
    if args.source_map:
        value = json.loads(args.source_map.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise SystemExit("--source-map must contain a JSON object")
        source_map = value
    if args.field_map:
        value = json.loads(args.field_map.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise SystemExit("--field-map must contain a JSON object")
        field_map = value
    response = convert_semantic(
        {
            "request_id": args.request_id,
            "source_path": args.source,
            "source_type": args.source_type,
            "model_name": args.model_name,
            "descriptor_path": str(args.descriptor) if args.descriptor else None,
            "source_map": source_map,
            "field_map": field_map,
        }
    )
    print(json.dumps(response, indent=2, sort_keys=True))
    return 0 if response["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
