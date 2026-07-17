from __future__ import annotations

import hashlib
import json
import pprint
from pathlib import Path
from typing import Any

from data_agent.analysis import analyze
from data_agent.io import ContractError, envelope, require_string, write_json_atomic


def render_analysis_workspace(request: dict[str, Any]) -> dict[str, Any]:
    """Create a local Markdown and Jupyter workspace for one analysis."""

    output_dir = Path(require_string(request, "output_dir")).resolve()
    if "reports" not in output_dir.parts:
        raise ContractError("output_dir must be under reports/")

    analysis_request = request.get("analysis_request")
    if not isinstance(analysis_request, dict):
        raise ContractError("analysis_request must be an object")
    supplied_response = request.get("analysis_response")
    if supplied_response is not None and not isinstance(supplied_response, dict):
        raise ContractError("analysis_response must be an object")
    analysis_response = supplied_response or analyze(analysis_request)

    output_dir.mkdir(parents=True, exist_ok=True)
    request_path = output_dir / "analysis.request.json"
    response_path = output_dir / "analysis.response.json"
    markdown_path = output_dir / "analysis.md"
    notebook_path = output_dir / "analysis.ipynb"

    write_json_atomic(request_path, analysis_request)
    write_json_atomic(response_path, analysis_response)
    markdown_path.write_text(
        _analysis_markdown(analysis_request, analysis_response), encoding="utf-8"
    )
    write_json_atomic(
        notebook_path,
        _analysis_notebook(analysis_request, analysis_response),
    )
    return envelope(
        request,
        "success",
        output_dir=str(output_dir),
        request_path=str(request_path),
        response_path=str(response_path),
        markdown_path=str(markdown_path),
        notebook_path=str(notebook_path),
        analysis_status=analysis_response.get("status"),
        warnings=[],
    )


def _analysis_markdown(
    analysis_request: dict[str, Any], analysis_response: dict[str, Any]
) -> str:
    title = str(analysis_request.get("title") or analysis_request.get("question") or "Analysis")
    metric_source = str(analysis_response.get("metric_source", "promoted"))
    validation = analysis_response.get("result_validation", {})
    validation_status = (
        validation.get("status", "not run") if isinstance(validation, dict) else "not run"
    )
    sql = str(analysis_response.get("sql") or analysis_request.get("sql") or "Not available")
    parameters = analysis_response.get("parameters", analysis_request.get("parameters", []))
    result = analysis_response.get("result")

    sections = [
        f"# {title}",
        "",
        f"- Status: `{analysis_response.get('status', 'unknown')}`",
        f"- Metric source: `{metric_source}`",
        f"- Semantic model: `{analysis_response.get('model', 'not resolved')}`",
        f"- Result validation: `{validation_status}`",
        f"- Source objects: `{', '.join(analysis_response.get('referenced_objects', [])) or 'not resolved'}`",
        "",
        "## Question",
        "",
        str(analysis_request.get("question") or "Not supplied."),
        "",
        "## SQL",
        "",
        "```sql",
        sql,
        "```",
        "",
        "## Parameters",
        "",
        "```json",
        json.dumps(parameters, indent=2, default=str),
        "```",
        "",
    ]
    if isinstance(result, dict):
        sections.extend(_result_markdown(result))
    sections.extend(
        [
            "## Semantic plan",
            "",
            "```json",
            json.dumps(
                analysis_response.get("normalized_plan", {}),
                indent=2,
                sort_keys=True,
                default=str,
            ),
            "```",
            "",
            "## Notes",
            "",
            (
                "This workspace is generated from a promoted semantic model. Edit the semantic "
                "plan to refine the analysis; SQL is regenerated from the model. Result checks "
                "remain optional until additional assurance is useful."
            ),
            "",
        ]
    )
    return "\n".join(sections)


def _result_markdown(result: dict[str, Any]) -> list[str]:
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    if not isinstance(columns, list) or not isinstance(rows, list):
        return []
    lines = [
        "## Result preview",
        "",
        (
            f"Returned rows: {result.get('row_count', len(rows))}; "
            f"truncated: {result.get('truncated', False)}; "
            f"query ID: `{result.get('query_id', 'offline or unavailable')}`."
        ),
        "",
    ]
    if columns:
        lines.append("| " + " | ".join(_table_text(value) for value in columns) + " |")
        lines.append("| " + " | ".join("---" for _ in columns) + " |")
        for row in rows[:50]:
            if isinstance(row, list):
                lines.append("| " + " | ".join(_table_text(value) for value in row) + " |")
        if len(rows) > 50:
            lines.extend(["", f"_Preview shows 50 of {len(rows)} returned rows._"])
    lines.append("")
    return lines


def _table_text(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _analysis_notebook(
    analysis_request: dict[str, Any], analysis_response: dict[str, Any]
) -> dict[str, Any]:
    title = str(analysis_request.get("title") or analysis_request.get("question") or "Analysis")
    base_request = dict(analysis_request)
    base_request["execute"] = False
    base_request.pop("configuration_confirmed", None)
    request_literal = pprint.pformat(base_request, sort_dicts=True, width=100)
    response_literal = pprint.pformat(analysis_response, sort_dicts=True, width=100)
    question_literal = repr(str(analysis_request.get("question", "")))
    model_path_literal = repr(str(analysis_request.get("model_path", "")))
    plan_literal = pprint.pformat(analysis_request.get("plan", {}), sort_dicts=True, width=100)

    cells = [
        _markdown_cell(
            f"# {title}\n\n"
            "This notebook is an editable semantic analysis workspace. Change the question or "
            "semantic plan and rerun the analysis cells; SQL is always regenerated from the "
            "promoted model. Set `RUN_LIVE = True` only after reviewing the displayed Snowflake "
            "context."
        ),
        _code_cell(
            "from data_agent.analysis import analyze\n"
            "from IPython.display import display, Markdown\n"
            "import pandas as pd\n"
            "import matplotlib.pyplot as plt\n\n"
            f"SAVED_RESPONSE = {response_literal}\n"
            "response = SAVED_RESPONSE\n"
            "display(Markdown(f\"**Saved analysis status:** `{response.get('status')}`; \"\n"
            "                 f\"**metric source:** `{response.get('metric_source', 'promoted')}`; \"\n"
            "                 f\"**validation:** `{response.get('result_validation', {}).get('status', 'not run')}`\"))"
        ),
        _code_cell(
            "# Edit the question or semantic plan. SQL is generated from this plan.\n"
            f"QUESTION = {question_literal}\n"
            f"MODEL_PATH = {model_path_literal}\n"
            f"PLAN = {plan_literal}"
        ),
        _code_cell(
            f"BASE_REQUEST = {request_literal}\n\n"
            "# Saved evidence remains visible until you explicitly rerun the edited request.\n"
            "USE_SAVED_RESPONSE = True\n"
            "RUN_LIVE = False\n"
            "VALIDATE_RESULT = False\n"
            "CONFIGURATION_CONFIRMED = False\n\n"
            "analysis_request = {\n"
            "    **BASE_REQUEST,\n"
            "    'question': QUESTION,\n"
            "    'model_path': MODEL_PATH,\n"
            "    'plan': PLAN,\n"
            "    'execute': RUN_LIVE,\n"
            "    'validate_result': VALIDATE_RESULT,\n"
            "}\n"
            "if not VALIDATE_RESULT:\n"
            "    analysis_request.pop('result_checks', None)\n"
            "if USE_SAVED_RESPONSE:\n"
            "    response = SAVED_RESPONSE\n"
            "else:\n"
            "    if RUN_LIVE:\n"
            "        analysis_request['configuration_confirmed'] = CONFIGURATION_CONFIRMED\n"
            "    response = analyze(analysis_request)\n"
            "display(Markdown(f\"**Current status:** `{response.get('status')}`\"))\n"
            "print(response.get('sql', 'SQL was not generated'))"
        ),
        _code_cell(
            "result = response.get('result', {})\n"
            "columns = result.get('columns', [])\n"
            "rows = result.get('rows', [])\n"
            "df = pd.DataFrame(rows, columns=columns)\n"
            "display(df)\n"
            "display(Markdown(f\"Rows: **{len(df)}** · Truncated: "
            "**{result.get('truncated', False)}** · Query ID: "
            "`{result.get('query_id', 'offline or unavailable')}`\"))"
        ),
        _code_cell(
            "# Optional quick chart: choose any categorical and numeric columns.\n"
            "if not df.empty:\n"
            "    numeric_columns = list(df.select_dtypes(include='number').columns)\n"
            "    category_columns = [column for column in df.columns if column not in numeric_columns]\n"
            "    if numeric_columns and category_columns:\n"
            "        ax = df.plot.bar(x=category_columns[0], y=numeric_columns[0], legend=False, "
            "figsize=(9, 4))\n"
            "        ax.set_title(QUESTION)\n"
            "        ax.set_ylabel(numeric_columns[0])\n"
            "        plt.tight_layout()\n"
            "        plt.show()"
        ),
        _code_cell(
            "# Optional self-contained HTML report. Edit the summary before generating.\n"
            "from data_agent.reporting.render import render_report\n\n"
            "GENERATE_REPORT = False\n"
            "REPORT_PATH = 'reports/generated/notebook-analysis-report.html'\n"
            "SUMMARY = 'Exploratory analysis; replace this sentence with the main finding.'\n\n"
            "if GENERATE_REPORT:\n"
            "    report_response = render_report({\n"
            "        'request_id': f\"{analysis_request.get('request_id', 'analysis')}-report\",\n"
            "        'output_path': REPORT_PATH,\n"
            "        'validation': response.get('result_validation', {'status': 'not_run'}),\n"
            "        'summary': SUMMARY,\n"
            "        'question': QUESTION,\n"
            "        'columns': columns,\n"
            "        'rows': rows,\n"
            "        'sql': response.get('sql', 'Not available'),\n"
            "        'plan': response.get('normalized_plan'),\n"
            "        'metadata': {\n"
            "            'title': QUESTION or 'Exploratory analysis',\n"
            "            'semantic_model': response.get('model', 'not resolved'),\n"
            "            'metric_source': response.get('metric_source', 'promoted'),\n"
            "            'query_id': result.get('query_id', 'offline or unavailable'),\n"
            "            'truncated': result.get('truncated', False),\n"
            "        },\n"
            "    })\n"
            "    display(Markdown(f\"Report: `{report_response['report_path']}`\"))"
        ),
        _markdown_cell(
            "## From exploration to a validated pattern\n\n"
            "When the question stabilizes, add `result_checks` and set "
            "`validate_result: true`. Request-scoped derived metrics remain unpromoted; promote "
            "a reusable definition through Semantic Setup."
        ),
    ]
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.11"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def _markdown_cell(source: str) -> dict[str, Any]:
    return {
        "cell_type": "markdown",
        "id": _cell_id("markdown", source),
        "metadata": {},
        "source": source.splitlines(keepends=True),
    }


def _code_cell(source: str) -> dict[str, Any]:
    return {
        "cell_type": "code",
        "id": _cell_id("code", source),
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def _cell_id(cell_type: str, source: str) -> str:
    return hashlib.sha256(f"{cell_type}:{source}".encode()).hexdigest()[:12]
