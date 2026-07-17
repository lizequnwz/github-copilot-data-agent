from __future__ import annotations

import json
from pathlib import Path

from data_agent.reporting.workspace import render_analysis_workspace

ROOT = Path(__file__).resolve().parents[1]
REQUEST = ROOT / "examples/requests/render-workspace.json"


def main() -> int:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    result = render_analysis_workspace(request)
    print(f"Markdown: {result['markdown_path']}")
    print(f"Notebook: {result['notebook_path']}")
    print(f"Analysis status: {result['analysis_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
