from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from data_agent.ask.analysis import analyze
from data_agent.ask.report import render_report
from data_agent.ask.workspace import render_analysis_workspace
from data_agent.io import ContractError, envelope, read_json, write_json_atomic

ROOT = Path(__file__).resolve().parents[2]


def ask_data(request: dict[str, Any]) -> dict[str, Any]:
    """Run the single Ask Data workflow and create useful artifacts by default."""

    analysis_request = request.get("analysis_request", request)
    if not isinstance(analysis_request, dict):
        raise ContractError("analysis_request must be an object")
    analysis = analyze(analysis_request)
    if analysis["status"] == "coverage_gap":
        return envelope(
            request,
            "coverage_gap",
            analysis=analysis,
            next_action="semantic_setup",
            artifacts={},
            warnings=analysis.get("warnings", []),
        )

    artifacts: dict[str, Any] = {}
    workspace_requested = request.get("workspace") is not False
    if workspace_requested:
        workspace_dir = request.get("workspace_dir") or _default_workspace_dir(
            str(analysis_request.get("request_id", "analysis"))
        )
        workspace = render_analysis_workspace(
            {
                "request_id": f"{analysis_request.get('request_id', 'analysis')}-workspace",
                "output_dir": str(workspace_dir),
                "analysis_request": analysis_request,
                "analysis_response": analysis,
            }
        )
        artifacts.update(
            {
                "workspace": workspace["output_dir"],
                "manifest": workspace["manifest_path"],
                "markdown": workspace["markdown_path"],
                "notebook": workspace["notebook_path"],
            }
        )

    report_request = request.get("report")
    if report_request:
        if not isinstance(report_request, (bool, dict)):
            raise ContractError("report must be true, false, or an object")
        report_options = report_request if isinstance(report_request, dict) else {}
        result = analysis.get("result")
        if not isinstance(result, dict):
            raise ContractError("a report requires an executed or supplied result")
        output_path = report_options.get("output_path")
        if not output_path:
            workspace_dir = Path(
                artifacts.get(
                    "workspace",
                    _default_workspace_dir(str(analysis_request.get("request_id", "analysis"))),
                )
            )
            workspace_dir.mkdir(parents=True, exist_ok=True)
            output_path = workspace_dir / "report.html"
        report_summary = (
            report_options.get("summary")
            or analysis_request.get("summary")
            or "Exploratory analysis; review the displayed evidence and caveats."
        )
        report_caveats = report_options.get(
            "caveats",
            analysis_request.get("caveats", analysis_request.get("notes", [])),
        )
        report = render_report(
            {
                **report_options,
                "request_id": f"{analysis_request.get('request_id', 'analysis')}-report",
                "output_path": str(output_path),
                "validation": analysis.get("result_validation", {"status": "not_run"}),
                "summary": report_summary,
                "question": analysis_request.get("question"),
                "columns": result.get("columns", []),
                "rows": result.get("rows", []),
                "sql": analysis.get("sql"),
                "plan": analysis.get("normalized_plan"),
                "caveats": report_caveats,
                "metadata": {
                    "title": analysis_request.get("question") or "Analysis",
                    "semantic_model": analysis.get("model"),
                    "model_sha256": analysis.get("semantic_model", {}).get("sha256"),
                    "plan_sha256": analysis.get("plan_sha256"),
                    "metric_source": analysis.get("metric_source"),
                    "query_id": result.get("query_id", "offline or unavailable"),
                    "truncated": result.get("truncated", False),
                    **report_options.get("metadata", {}),
                },
            }
        )
        artifacts["report"] = report["report_path"]
        manifest_path = artifacts.get("manifest")
        if isinstance(manifest_path, str):
            manifest = read_json(manifest_path)
            manifest_artifacts = manifest.setdefault("artifacts", {})
            if not isinstance(manifest_artifacts, dict):
                raise ContractError("analysis manifest artifacts must be an object")
            manifest_artifacts["report"] = report["report_path"]
            narrative = manifest.setdefault("narrative", {})
            if not isinstance(narrative, dict):
                raise ContractError("analysis manifest narrative must be an object")
            narrative["summary"] = report_summary
            narrative["caveats"] = report_caveats
            if isinstance(report_options.get("insights"), list):
                narrative["findings"] = report_options["insights"]
            write_json_atomic(manifest_path, manifest)

    return envelope(
        request,
        str(analysis.get("status", "success")),
        analysis=analysis,
        artifacts=artifacts,
        warnings=analysis.get("warnings", []),
    )


def _default_workspace_dir(request_id: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", request_id.casefold()).strip("-") or "analysis"
    return ROOT / "workspaces" / "analysis" / slug
