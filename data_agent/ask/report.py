from __future__ import annotations

import hashlib
import html
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_agent.io import ContractError, envelope, require_string

_COLORS = ("#2563eb", "#b45309", "#047857", "#7c3aed", "#be123c", "#0369a1")


def _number(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _formatted_number(value: float, spec: Any, *, compact_default: bool = False) -> str:
    if spec is None:
        return _number(value) if compact_default else str(value)
    if not isinstance(spec, dict):
        raise ContractError("number format must be an object")
    style = str(spec.get("style", "number")).casefold()
    if style == "percentage":
        style = "percent"
    if style not in {"number", "currency", "percent"}:
        raise ContractError("number format style must be number, currency, or percentage")
    decimals = spec.get("decimals", 2 if style in {"currency", "percent"} else 0)
    if not isinstance(decimals, int) or isinstance(decimals, bool) or not 0 <= decimals <= 6:
        raise ContractError("number format decimals must be an integer from 0 to 6")
    compact = spec.get("compact", compact_default)
    if not isinstance(compact, bool):
        raise ContractError("number format compact must be true or false")
    scaled = value * 100 if style == "percent" else value
    compact_suffix = ""
    if compact and abs(scaled) >= 1_000_000_000:
        scaled, compact_suffix = scaled / 1_000_000_000, "B"
    elif compact and abs(scaled) >= 1_000_000:
        scaled, compact_suffix = scaled / 1_000_000, "M"
    elif compact and abs(scaled) >= 1_000:
        scaled, compact_suffix = scaled / 1_000, "K"
    number = f"{scaled:,.{decimals}f}"
    currency = ""
    if style == "currency":
        code = str(spec.get("currency", "USD")).upper()
        currency = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}.get(code, f"{code} ")
    suffix = "%" if style == "percent" else ""
    return f"{currency}{number}{compact_suffix}{suffix}"


def _table_value(value: Any, spec: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)) and not isinstance(value, bool) and spec is not None:
        return _formatted_number(float(value), spec)
    return str(value)


def _chart_series(spec: dict[str, Any]) -> list[dict[str, Any]]:
    raw_series = spec.get("series")
    if raw_series is None:
        raw_series = [{"name": str(spec.get("series_name", "Value")), "data": spec.get("data")}]
    if not isinstance(raw_series, list) or not 1 <= len(raw_series) <= 6:
        raise ContractError("spec.series must contain 1 to 6 aggregate series")
    normalized: list[dict[str, Any]] = []
    labels: list[str] | None = None
    total_points = 0
    names: set[str] = set()
    for index, series in enumerate(raw_series):
        if not isinstance(series, dict):
            raise ContractError(f"chart series {index} must be an object")
        name = str(series.get("name", f"Series {index + 1}")).strip()
        if not name or name.casefold() in names:
            raise ContractError("chart series names must be non-empty and unique")
        names.add(name.casefold())
        data = series.get("data")
        if not isinstance(data, list) or not data or len(data) > 100:
            raise ContractError("each chart series must contain 1 to 100 aggregate points")
        try:
            current_labels = [str(point["label"]) for point in data]
            values = [float(point["value"]) for point in data]
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("each chart point requires a string label and numeric value") from exc
        if any(not math.isfinite(value) for value in values):
            raise ContractError("chart values must be finite numbers")
        if labels is not None and current_labels != labels:
            raise ContractError("all chart series must use the same ordered labels")
        labels = current_labels
        total_points += len(values)
        normalized.append({"name": name, "labels": current_labels, "values": values})
    if total_points > 600:
        raise ContractError("chart cannot contain more than 600 aggregate points")
    return normalized


def render_chart(request: dict[str, Any]) -> dict[str, Any]:
    spec = request.get("spec")
    if not isinstance(spec, dict) or spec.get("type") not in {"bar", "line", "waterfall"}:
        raise ContractError("spec.type must be bar, line, or waterfall")
    series = _chart_series(spec)
    if spec["type"] == "waterfall" and len(series) != 1:
        raise ContractError("waterfall charts require exactly one series")
    value_format = spec.get("value_format")
    _formatted_number(series[0]["values"][0], value_format, compact_default=True)
    title = str(spec.get("title", "Chart"))
    unit = str(spec.get("unit", ""))
    all_values = [value for item in series for value in item["values"]]
    unit_suffix = f" {unit}" if unit else ""
    alt_text = str(
        spec.get("alt_text")
        or f"{title}. Values range from {_formatted_number(min(all_values), value_format, compact_default=True)} to {_formatted_number(max(all_values), value_format, compact_default=True)}{unit_suffix}."
    )
    chart_id = "chart-" + hashlib.sha256(
        json.dumps({"title": title, "series": series}, sort_keys=True).encode()
    ).hexdigest()[:10]
    svg = _render_chart_svg(
        chart_id=chart_id,
        chart_type=str(spec["type"]),
        title=title,
        alt_text=alt_text,
        unit=unit,
        value_format=value_format,
        series=series,
    )
    return envelope(
        request,
        "success",
        svg=svg,
        content_sha256=hashlib.sha256(svg.encode()).hexdigest(),
        warnings=[],
    )


def _render_chart_svg(
    *,
    chart_id: str,
    chart_type: str,
    title: str,
    alt_text: str,
    unit: str,
    value_format: Any,
    series: list[dict[str, Any]],
) -> str:
    width, height = 920, 500
    left, right, top, bottom = 86, 28, 82 if len(series) > 1 else 52, 90
    plot_w, plot_h = width - left - right, height - top - bottom
    labels: list[str] = series[0]["labels"]
    if chart_type == "waterfall":
        running = 0.0
        scale_values = [0.0]
        for value in series[0]["values"]:
            running += value
            scale_values.append(running)
    else:
        scale_values = [value for item in series for value in item["values"]]
    raw_low, raw_high = min(scale_values), max(scale_values)
    low = min(0.0, raw_low) if chart_type in {"bar", "waterfall"} else raw_low
    high = max(0.0, raw_high) if chart_type in {"bar", "waterfall"} else raw_high
    if high == low:
        high, low = high + 1.0, low - (0.0 if chart_type != "line" else 1.0)
    span = high - low

    def y_position(value: float) -> float:
        return top + ((high - value) / span) * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" class="report-chart" role="img" aria-labelledby="{chart_id}-title {chart_id}-desc" viewBox="0 0 {width} {height}">',
        f'<title id="{chart_id}-title">{html.escape(title)}</title>',
        f'<desc id="{chart_id}-desc">{html.escape(alt_text)}</desc>',
        '<g font-family="system-ui,-apple-system,sans-serif" fill="currentColor">',
    ]
    for tick in range(5):
        value = low + (span * tick / 4)
        y = top + plot_h - (tick / 4) * plot_h
        parts.append(
            f'<line x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}" stroke="currentColor" stroke-opacity=".16" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{left - 12}" y="{y + 4:.1f}" text-anchor="end" font-size="12">{html.escape(_formatted_number(value, value_format, compact_default=True))}</text>'
        )
    if unit:
        parts.append(f'<text x="{left}" y="24" font-size="12" font-weight="650">{html.escape(unit)}</text>')
    if len(series) > 1:
        for index, item in enumerate(series):
            legend_x = left + (index % 3) * 220
            legend_y = 25 + (index // 3) * 28
            parts.append(
                f'<g role="button" tabindex="0" aria-pressed="true" aria-label="Toggle {html.escape(item["name"], quote=True)}" data-series-toggle="{index}" transform="translate({legend_x},{legend_y})"><rect width="16" height="16" rx="3" fill="{_COLORS[index]}"/><text x="24" y="13" font-size="13">{html.escape(item["name"])}</text></g>'
            )
    zero_y = y_position(0.0)
    if low <= 0 <= high:
        parts.append(
            f'<line x1="{left}" x2="{width - right}" y1="{zero_y:.1f}" y2="{zero_y:.1f}" stroke="currentColor" stroke-opacity=".55" stroke-width="1.5"/>'
        )
    slot = plot_w / len(labels)
    show_values = sum(len(item["values"]) for item in series) <= 24
    if chart_type == "bar":
        group_width = slot * 0.78
        bar_width = group_width / len(series)
        for series_index, item in enumerate(series):
            for index, (label, value) in enumerate(zip(labels, item["values"])):
                value_y = y_position(value)
                bar_top = min(value_y, zero_y)
                bar_h = max(abs(value_y - zero_y), 1.5)
                point_x = left + index * slot + slot * 0.11 + series_index * bar_width
                formatted = _formatted_number(value, value_format)
                aria = f'{item["name"]}, {label}: {formatted}{unit_suffix(unit)}'
                parts.append(
                    f'<rect x="{point_x:.1f}" y="{bar_top:.1f}" width="{max(bar_width - 2, 1):.1f}" height="{bar_h:.1f}" rx="3" fill="{_COLORS[series_index]}" tabindex="0" role="img" aria-label="{html.escape(aria, quote=True)}" data-chart-point data-series-index="{series_index}" data-series="{html.escape(item["name"], quote=True)}" data-label="{html.escape(label, quote=True)}" data-value="{html.escape(formatted, quote=True)}"/>'
                )
                if show_values:
                    label_y = max(bar_top - 7, top + 10) if value >= 0 else min(bar_top + bar_h + 15, height - bottom + 22)
                    parts.append(
                        f'<text x="{point_x + bar_width / 2:.1f}" y="{label_y:.1f}" text-anchor="middle" font-size="11" font-weight="650" data-series-index="{series_index}">{html.escape(_formatted_number(value, value_format, compact_default=True))}</text>'
                    )
    elif chart_type == "line":
        for series_index, item in enumerate(series):
            points = [
                (left + (index / max(len(labels) - 1, 1)) * plot_w, y_position(value))
                for index, value in enumerate(item["values"])
            ]
            dash = "" if series_index % 3 == 0 else ' stroke-dasharray="8 5"' if series_index % 3 == 1 else ' stroke-dasharray="3 5"'
            parts.append(
                '<polyline points="'
                + " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
                + f'" fill="none" stroke="{_COLORS[series_index]}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" data-series-index="{series_index}"{dash}/>'
            )
            for (point_x, point_y), label, value in zip(points, labels, item["values"]):
                formatted = _formatted_number(value, value_format)
                aria = f'{item["name"]}, {label}: {formatted}{unit_suffix(unit)}'
                parts.append(
                    f'<circle cx="{point_x:.1f}" cy="{point_y:.1f}" r="6" fill="{_COLORS[series_index]}" stroke="currentColor" stroke-width="2" tabindex="0" role="img" aria-label="{html.escape(aria, quote=True)}" data-chart-point data-series-index="{series_index}" data-series="{html.escape(item["name"], quote=True)}" data-label="{html.escape(label, quote=True)}" data-value="{html.escape(formatted, quote=True)}"/>'
                )
    else:
        running = 0.0
        for index, (label, delta) in enumerate(zip(labels, series[0]["values"])):
            before, after = running, running + delta
            running = after
            bar_top = min(y_position(before), y_position(after))
            bar_h = max(abs(y_position(before) - y_position(after)), 1.5)
            waterfall_x = left + index * slot + slot * 0.16
            color = "#14733b" if delta >= 0 else "#b42318"
            formatted = _formatted_number(delta, value_format)
            aria = f'{label}: {formatted}{unit_suffix(unit)}; running total {_formatted_number(after, value_format)}'
            parts.append(
                f'<rect x="{waterfall_x:.1f}" y="{bar_top:.1f}" width="{slot * .68:.1f}" height="{bar_h:.1f}" rx="3" fill="{color}" tabindex="0" role="img" aria-label="{html.escape(aria, quote=True)}" data-chart-point data-series-index="0" data-series="Change" data-label="{html.escape(label, quote=True)}" data-value="{html.escape(formatted, quote=True)}"/>'
            )
            parts.append(
                f'<text x="{waterfall_x + slot * .34:.1f}" y="{max(bar_top - 7, top + 10):.1f}" text-anchor="middle" font-size="11" font-weight="650">{html.escape(_formatted_number(delta, value_format, compact_default=True))}</text>'
            )
            if index:
                parts.append(
                    f'<line x1="{waterfall_x - slot * .16:.1f}" x2="{waterfall_x:.1f}" y1="{y_position(before):.1f}" y2="{y_position(before):.1f}" stroke="currentColor" stroke-opacity=".45" stroke-dasharray="3 3"/>'
                )
    label_step = max(1, math.ceil(len(labels) / 12))
    for index, label in enumerate(labels):
        if index % label_step:
            continue
        label_x = left + (index + 0.5) * slot if chart_type != "line" else left + (index / max(len(labels) - 1, 1)) * plot_w
        short_label = label if len(label) <= 18 else label[:17] + "…"
        parts.append(
            f'<text x="{label_x:.1f}" y="{height - 42}" text-anchor="middle" font-size="12">{html.escape(short_label)}</text>'
        )
    parts.extend(["</g>", "</svg>"])
    return "".join(parts)


def unit_suffix(unit: str) -> str:
    return f" {unit}" if unit else ""


def render_report(request: dict[str, Any]) -> dict[str, Any]:
    output = Path(require_string(request, "output_path")).resolve()
    if output.suffix.lower() != ".html" or "workspaces" not in output.parts:
        raise ContractError("output_path must be an HTML file under workspaces/")
    metadata = request.get("metadata")
    if not isinstance(metadata, dict):
        raise ContractError("metadata must be an object")
    metadata = dict(metadata)
    metadata.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
    validation = request.get(
        "validation",
        {
            "status": "not_run",
            "warnings": ["exploratory report; result validation was not supplied"],
        },
    )
    if not isinstance(validation, dict):
        raise ContractError("validation must be an object")
    validation_status = str(validation.get("status", "not_run"))
    if validation_status in {"fail", "validation_failed"}:
        raise ContractError("reports cannot be rendered from failed result checks")
    if not metadata.get("title"):
        raise ContractError("metadata missing: title")
    summary = html.escape(require_string(request, "summary"))
    columns, rows = _validated_table(request)
    column_formats = _validated_column_formats(request, columns)
    table_head, table_rows = _table_html(columns, rows, column_formats)
    insights_html = _insights_html(request.get("insights", []))
    charts_html = _charts_html(request)
    interpretation_html = _mapping_section(
        request.get("interpretation", {}),
        "interpretation",
        "01 / INTERPRET",
        "Resolved question",
        "Definitions unambiguous",
    )
    validation_html = _mapping_section(
        request.get("validation_summary", {}),
        "contract",
        "02 / VALIDATE",
        "Execution contract",
        "All checks passed" if validation_status == "pass" else "Checks not run",
    )
    definitions = request.get("definitions", {})
    if not isinstance(definitions, dict):
        raise ContractError("definitions must be an object")
    definitions_html = "".join(
        f'<div class="definition"><dt>{html.escape(str(key))}</dt><dd>{html.escape(str(value))}</dd></div>'
        for key, value in definitions.items()
    )
    caveats = request.get("caveats", [])
    if not isinstance(caveats, list):
        raise ContractError("caveats must be an array")
    caveats_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in caveats) or "<li>No additional caveats were supplied.</li>"
    methodology = html.escape(str(request.get("methodology", "Not provided")))
    sql = html.escape(str(request.get("sql", "Not available")))
    plan = request.get("plan")
    if plan is not None and not isinstance(plan, dict):
        raise ContractError("plan must be an object")
    plan_html = (
        "<details><summary>Show normalized semantic plan</summary><pre><code>"
        + html.escape(json.dumps(plan, indent=2, sort_keys=True))
        + "</code></pre></details>"
        if isinstance(plan, dict)
        else ""
    )
    query_details = "".join(
        f'<div class="meta-item"><dt>{html.escape(str(key).replace("_", " ").title())}</dt><dd>{html.escape(str(value))}</dd></div>'
        for key, value in metadata.items()
        if key != "title"
    )
    question = str(request.get("question", "")).strip()
    question_html = f'<p class="question">{html.escape(question)}</p>' if question else ""
    badges = (
        ['<span class="badge success">Validation passed</span>']
        if validation_status == "pass"
        else ['<span class="badge warning">Exploratory · not validated</span>']
    )
    if metadata.get("data_freshness"):
        badges.append(f'<span class="badge">Data: {html.escape(str(metadata["data_freshness"]))}</span>')
    if metadata.get("period"):
        badges.append(f'<span class="badge">Period: {html.escape(str(metadata["period"]))}</span>')
    if metadata.get("truncated") is not None:
        badges.append('<span class="badge success">Complete result</span>' if metadata["truncated"] is False else '<span class="badge warning">Result truncated</span>')
    badges.append(f'<span class="badge">Generated: {html.escape(str(metadata["generated_at"]))}</span>')
    replacements = {
        "__EYEBROW__": (
            "Validated analysis · Ask Data"
            if validation_status == "pass"
            else "Exploratory analysis · Ask Data"
        ),
        "__TITLE__": html.escape(str(metadata["title"])),
        "__QUESTION__": question_html,
        "__BADGES__": "".join(badges),
        "__SUMMARY__": summary,
        "__INSIGHTS__": insights_html,
        "__INTERPRETATION__": interpretation_html,
        "__VALIDATION__": validation_html,
        "__CHARTS__": charts_html,
        "__ROW_COUNT__": str(len(rows)),
        "__TABLE_HEAD__": table_head,
        "__TABLE_ROWS__": table_rows,
        "__DEFINITIONS__": definitions_html,
        "__METHODOLOGY__": methodology,
        "__CAVEATS__": caveats_html,
        "__QUERY_DETAILS__": query_details,
        "__SQL__": sql,
        "__PLAN__": plan_html,
    }
    document = _REPORT_TEMPLATE
    for marker, value in replacements.items():
        document = document.replace(marker, value)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    return envelope(
        request,
        "success",
        report_path=str(output),
        content_sha256=hashlib.sha256(document.encode()).hexdigest(),
        warnings=[],
    )


def _validated_table(request: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    columns, rows = request.get("columns", []), request.get("rows", [])
    if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
        raise ContractError("columns must be an array of strings")
    if not isinstance(rows, list) or len(rows) > 500:
        raise ContractError("rows must be an array with at most 500 aggregate rows")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ContractError("each row must be an array matching the columns")
    return columns, rows


def _validated_column_formats(request: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    formats = request.get("column_formats", {})
    if not isinstance(formats, dict):
        raise ContractError("column_formats must be an object keyed by column name")
    unknown = set(formats) - set(columns)
    if unknown:
        raise ContractError(f"column_formats contains unknown columns: {', '.join(sorted(unknown))}")
    for value in formats.values():
        _formatted_number(0.0, value)
    return formats


def _table_html(
    columns: list[str], rows: list[list[Any]], formats: dict[str, Any]
) -> tuple[str, str]:
    head = "".join(
        f'<th scope="col" aria-sort="none"><button type="button" data-sort-index="{index}">{html.escape(column)}<span aria-hidden="true"> ↕</span></button></th>'
        for index, column in enumerate(columns)
    )
    body = "".join(
        f'<tr data-original-index="{row_index}">'
        + "".join(
            _table_cell(value, formats.get(columns[index])) for index, value in enumerate(row)
        )
        + "</tr>"
        for row_index, row in enumerate(rows[:500])
    )
    return head, body


def _table_cell(value: Any, value_format: Any) -> str:
    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    sort_value = str(float(value)) if numeric else str(value or "").casefold()
    return (
        f'<td class="{"number" if numeric else ""}" data-sort-kind="{"number" if numeric else "text"}" '
        f'data-sort-value="{html.escape(sort_value, quote=True)}">'
        f"{html.escape(_table_value(value, value_format))}</td>"
    )


def _insights_html(value: Any) -> str:
    if not isinstance(value, list) or len(value) > 6:
        raise ContractError("insights must be an array with at most 6 items")
    if not value:
        return ""
    cards: list[str] = []
    for index, insight in enumerate(value):
        if not isinstance(insight, dict):
            raise ContractError(f"insight {index} must be an object")
        required = ("title", "finding", "evidence", "why_it_matters")
        missing = [key for key in required if not isinstance(insight.get(key), str) or not insight[key].strip()]
        if missing:
            raise ContractError(f"insight {index} missing: {', '.join(missing)}")
        caveat = str(insight.get("caveat", "")).strip()
        cards.append(
            '<article class="insight-card">'
            f'<h3>{html.escape(insight["title"])}</h3>'
            f'<p class="finding">{html.escape(insight["finding"])}</p>'
            f'<dl><div><dt>Evidence</dt><dd>{html.escape(insight["evidence"])}</dd></div>'
            f'<div><dt>Why it matters</dt><dd>{html.escape(insight["why_it_matters"])}</dd></div></dl>'
            + (f'<p class="caveat"><strong>Keep in mind:</strong> {html.escape(caveat)}</p>' if caveat else "")
            + "</article>"
        )
    return '<section class="card" aria-labelledby="insights-title"><div class="section-heading"><div><span class="step">Key insights</span><h2 id="insights-title">What the evidence says</h2></div></div><div class="insight-grid">' + "".join(cards) + "</div></section>"


def _charts_html(request: dict[str, Any]) -> str:
    charts = request.get("charts", [])
    if not isinstance(charts, list) or len(charts) > 3:
        raise ContractError("charts must be an array with at most 3 items")
    sections: list[str] = []
    for index, chart in enumerate(charts):
        if not isinstance(chart, dict) or not isinstance(chart.get("spec"), dict):
            raise ContractError(f"chart {index} requires a spec object")
        heading = str(chart.get("heading", chart["spec"].get("title", f"Chart {index + 1}"))).strip()
        takeaway = str(chart.get("takeaway", "")).strip()
        if not heading or not takeaway:
            raise ContractError(f"chart {index} requires heading and takeaway")
        rendered = render_chart(
            {"request_id": f"{request.get('request_id', 'report')}-chart-{index}", "spec": chart["spec"]}
        )
        sections.append(
            f'<section class="card chart" data-chart-container aria-labelledby="chart-heading-{index}"><div class="section-heading"><div><span class="step">Explore</span><h2 id="chart-heading-{index}">{html.escape(heading)}</h2><p class="chart-takeaway">{html.escape(takeaway)}</p></div><button type="button" data-reset-chart>Reset chart</button></div>{rendered["svg"]}<div class="chart-tooltip" role="status" hidden></div></section>'
        )
    legacy = _safe_chart_svg(request.get("chart_svg"), heading=str(request.get("chart_heading", "Chart")))
    if legacy:
        sections.append(legacy)
    if len(sections) > 3:
        raise ContractError("a report cannot contain more than 3 charts")
    return "".join(sections)


def _mapping_section(value: Any, css_name: str, step: str, title: str, status: str) -> str:
    if not isinstance(value, dict):
        raise ContractError(f"{css_name if css_name != 'contract' else 'validation_summary'} must be an object")
    if not value:
        return ""
    items = "".join(
        f'<div class="{css_name}-item"><dt>{html.escape(str(key).replace("_", " ").title())}</dt><dd>{html.escape(str(item))}</dd></div>'
        for key, item in value.items()
    )
    return f'<section class="card" aria-labelledby="{css_name}-title"><div class="section-heading"><div><span class="step">{step}</span><h2 id="{css_name}-title">{title}</h2></div><span class="status-text">{status}</span></div><dl class="{css_name}-grid">{items}</dl></section>'


def _safe_chart_svg(value: Any, *, heading: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or not value.lstrip().startswith("<svg"):
        raise ContractError("chart_svg must be SVG returned by render-chart")
    blocked = re.compile(r"(?is)<(?:script|style|foreignObject)|\bon\w+\s*=|\b(?:href|src)\s*=|url\s*\(")
    if blocked.search(value):
        raise ContractError("chart_svg contains blocked active or external content")
    return f'<section class="card chart" aria-labelledby="legacy-chart-heading"><div class="section-heading"><div><span class="step">Compare</span><h2 id="legacy-chart-heading">{html.escape(heading)}</h2></div></div>{value}</section>'


_REPORT_TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark"><title>__TITLE__</title>
<style>
:root{--background:#f8fafc;--surface:#fff;--surface-muted:#edf2f7;--text:#172554;--muted:#475569;--primary:#1e40af;--accent:#b45309;--border:#b8c8e2;--ring:#1e40af;--success:#166534;--warning:#92400e;--shadow:0 8px 20px rgba(30,64,175,.08)}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--background);color:var(--text);font:16px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,input{font:inherit;color:inherit}button{min-height:44px;cursor:pointer}a{color:var(--primary)}:focus-visible{outline:3px solid var(--ring);outline-offset:3px}.skip{position:absolute;left:-9999px;top:1rem;background:var(--surface);padding:.75rem 1rem;z-index:10}.skip:focus{left:1rem}main{width:min(1160px,calc(100% - 2rem));margin:0 auto;padding:3rem 0 5rem}header{display:grid;gap:1rem;margin-bottom:2rem;padding-bottom:2rem;border-bottom:1px solid var(--border)}.eyebrow,.step{color:var(--primary);font-size:.78rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}h1{font-size:clamp(2.15rem,6vw,3.65rem);line-height:1.03;letter-spacing:-.035em;margin:0;max-width:19ch}h2{font-size:1.35rem;line-height:1.25;margin:.25rem 0 1rem}h3{font-size:1.05rem;margin:0 0 .5rem}.question{margin:0;max-width:76ch;color:var(--muted);font-size:1.08rem}.badges{display:flex;flex-wrap:wrap;gap:.5rem}.badge{display:inline-flex;align-items:center;min-height:32px;padding:.25rem .7rem;border:1px solid var(--border);border-radius:999px;background:var(--surface);font-size:.82rem;font-weight:700}.badge.success,.success-text{color:var(--success)}.badge.warning{color:var(--warning)}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:1rem}.card{grid-column:span 12;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:clamp(1.1rem,3vw,1.6rem);box-shadow:var(--shadow)}.summary{border-left:5px solid var(--accent);background:linear-gradient(110deg,var(--surface),var(--surface-muted))}.summary p{font-size:clamp(1.25rem,3vw,1.65rem);line-height:1.4;margin-bottom:.25rem;max-width:58ch}.section-heading{display:flex;flex-wrap:wrap;align-items:flex-start;justify-content:space-between;gap:.75rem;margin-bottom:1rem}.section-heading h2{margin:.15rem 0 0}.section-heading button,.table-controls button{border:1px solid var(--border);border-radius:8px;background:var(--surface);padding:.55rem .8rem;font-weight:700}.status-text{font-size:.84rem;font-weight:750;padding:.25rem .65rem;border:1px solid var(--border);border-radius:999px}.interpretation-grid,.contract-grid{display:grid;gap:.75rem}.interpretation-item,.contract-item{padding:.85rem 1rem;background:var(--surface-muted);border-radius:8px;min-width:0}.interpretation-item dt,.contract-item dt,.insight-card dt{color:var(--muted);font-size:.75rem;letter-spacing:.05em;text-transform:uppercase}.interpretation-item dd,.contract-item dd{color:var(--text);font-weight:750}.insight-grid{display:grid;gap:.75rem}.insight-card{padding:1rem;border:1px solid var(--border);border-radius:10px;background:var(--surface-muted)}.insight-card p{margin:.4rem 0}.insight-card dl{display:grid;gap:.55rem}.insight-card dd{margin:0}.finding{font-size:1.08rem;font-weight:700}.caveat{color:var(--muted);font-size:.9rem}.chart{position:relative}.chart-takeaway{max-width:70ch;margin:.25rem 0;color:var(--muted)}.chart svg{display:block;width:100%;height:auto;color:var(--text);background:transparent}.chart [data-chart-point],.chart [data-series-toggle]{cursor:pointer}.chart [data-series-toggle]:focus{outline:3px solid var(--ring);outline-offset:3px}.chart-tooltip{position:fixed;z-index:20;max-width:280px;padding:.55rem .7rem;border-radius:7px;background:var(--text);color:var(--surface);font-size:.85rem;box-shadow:var(--shadow);pointer-events:none}.table-controls{display:flex;flex-wrap:wrap;gap:.75rem;align-items:end;margin-bottom:1rem}.table-controls label{display:grid;gap:.25rem;font-weight:700;flex:1 1 260px}.table-controls input{min-height:44px;padding:.55rem .7rem;border:1px solid var(--border);border-radius:8px;background:var(--surface)}.table-wrap{overflow:auto;border:1px solid var(--border);border-radius:8px}table{border-collapse:collapse;width:100%;min-width:560px}th,td{padding:.75rem .9rem;text-align:left;border-bottom:1px solid var(--border);vertical-align:top}th{position:sticky;top:0;background:var(--surface-muted)}th button{width:100%;border:0;background:transparent;text-align:left;font-size:.78rem;font-weight:800;letter-spacing:.05em;text-transform:uppercase}tbody tr:nth-child(even){background:color-mix(in srgb,var(--surface-muted) 40%,transparent)}td.number{font-variant-numeric:tabular-nums;text-align:right;font-weight:700}.definition,.meta-item{display:grid;gap:.2rem;padding:.7rem 0;border-bottom:1px solid var(--border)}dt{font-weight:800}dd{margin:0;color:var(--muted);overflow-wrap:anywhere}ul{padding-left:1.25rem}details{border:1px solid var(--border);border-radius:8px;padding:.8rem 1rem}details+details{margin-top:.75rem}summary{cursor:pointer;min-height:44px;display:flex;align-items:center;font-weight:800}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#0f172a;color:#e2e8f0;padding:1rem;border-radius:8px;overflow:auto;font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace}.footer{margin-top:2rem;color:var(--muted);font-size:.85rem}
@media(min-width:680px){.interpretation-grid,.insight-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.contract-grid{grid-template-columns:repeat(4,minmax(0,1fr))}}@media(min-width:800px){.span-7{grid-column:span 7}.span-5{grid-column:span 5}.span-6{grid-column:span 6}}@media(prefers-color-scheme:dark){:root{--background:#071126;--surface:#0f1d38;--surface-muted:#18294a;--text:#eff6ff;--muted:#bfdbfe;--primary:#93c5fd;--accent:#fbbf24;--border:#526b90;--ring:#93c5fd;--success:#86efac;--warning:#fcd34d;--shadow:none}pre{background:#020617}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important;animation:none!important}}@media print{body{background:#fff;color:#111}main{width:100%;padding:0}.card{box-shadow:none;break-inside:avoid}.table-controls,.chart button,.chart-tooltip{display:none!important}details{border:0;padding:0}details>summary{display:none}details>*{display:block!important}}
</style></head><body><a class="skip" href="#content">Skip to report</a><main id="content"><header><div class="eyebrow">__EYEBROW__</div><h1>__TITLE__</h1>__QUESTION__<div class="badges">__BADGES__</div></header><div class="grid"><section class="card summary" aria-labelledby="summary-title"><span class="step">Answer</span><h2 id="summary-title">Direct finding</h2><p>__SUMMARY__</p></section>__INSIGHTS____INTERPRETATION____VALIDATION____CHARTS__<section class="card" aria-labelledby="results-title"><div class="section-heading"><div><span class="step">Evidence</span><h2 id="results-title">Complete result</h2></div><span class="status-text">__ROW_COUNT__ rows returned</span></div><div class="table-controls"><label>Filter result<input id="tableFilter" type="search" placeholder="Filter any visible value"></label><button id="resetTable" type="button">Reset table</button></div><div class="table-wrap" tabindex="0" aria-label="Scrollable result table"><table id="resultTable"><thead><tr>__TABLE_HEAD__</tr></thead><tbody>__TABLE_ROWS__</tbody></table></div></section><section class="card span-7" aria-labelledby="definitions-title"><h2 id="definitions-title">Business definitions</h2><dl>__DEFINITIONS__</dl></section><section class="card span-5" aria-labelledby="method-title"><h2 id="method-title">Method</h2><p>__METHODOLOGY__</p></section><section class="card span-6" aria-labelledby="caveats-title"><h2 id="caveats-title">Notes and caveats</h2><ul>__CAVEATS__</ul></section><section class="card span-6" aria-labelledby="details-title"><h2 id="details-title">Reproducibility</h2><dl>__QUERY_DETAILS__</dl></section><section class="card" aria-labelledby="sql-title"><div class="section-heading"><div><span class="step">Inspect</span><h2 id="sql-title">SQL and semantic plan</h2></div><span class="status-text">Read-only · parameterized</span></div><details><summary>Show compiled SQL</summary><pre><code>__SQL__</code></pre></details>__PLAN__</section></div><p class="footer">Self-contained HTML with no remote scripts, fonts, or assets.</p></main>
<script>
const table=document.getElementById('resultTable'),body=table.tBodies[0],originalRows=[...body.rows];let sortIndex=null,sortDirection=1;function filterRows(){const query=document.getElementById('tableFilter').value.toLowerCase();for(const row of body.rows)row.hidden=!row.textContent.toLowerCase().includes(query)}function resetTable(){document.getElementById('tableFilter').value='';for(const row of originalRows){row.hidden=false;body.append(row)}sortIndex=null;sortDirection=1;for(const header of table.tHead.rows[0].cells)header.setAttribute('aria-sort','none')}document.getElementById('tableFilter').addEventListener('input',filterRows);document.getElementById('resetTable').onclick=resetTable;table.querySelectorAll('[data-sort-index]').forEach(button=>button.onclick=()=>{const index=Number(button.dataset.sortIndex);sortDirection=sortIndex===index?-sortDirection:1;sortIndex=index;const rows=[...body.rows].sort((a,b)=>{const left=a.cells[index],right=b.cells[index],kind=left.dataset.sortKind;let comparison=kind==='number'?Number(left.dataset.sortValue)-Number(right.dataset.sortValue):left.dataset.sortValue.localeCompare(right.dataset.sortValue);return comparison*sortDirection});rows.forEach(row=>body.append(row));[...table.tHead.rows[0].cells].forEach((header,headerIndex)=>header.setAttribute('aria-sort',headerIndex===index?(sortDirection===1?'ascending':'descending'):'none'))});
function showPoint(point){const container=point.closest('[data-chart-container]'),tooltip=container?.querySelector('.chart-tooltip');if(!tooltip)return;tooltip.textContent=`${point.dataset.series} · ${point.dataset.label}: ${point.dataset.value}`;const box=point.getBoundingClientRect();tooltip.style.left=Math.min(box.left,innerWidth-300)+'px';tooltip.style.top=Math.max(box.top-52,8)+'px';tooltip.hidden=false}function hidePoint(point){const tooltip=point.closest('[data-chart-container]')?.querySelector('.chart-tooltip');if(tooltip)tooltip.hidden=true}document.querySelectorAll('[data-chart-point]').forEach(point=>{point.addEventListener('mouseenter',()=>showPoint(point));point.addEventListener('focus',()=>showPoint(point));point.addEventListener('click',()=>showPoint(point));point.addEventListener('mouseleave',()=>hidePoint(point));point.addEventListener('blur',()=>hidePoint(point))});function toggleSeries(toggle){const container=toggle.closest('[data-chart-container]'),index=toggle.dataset.seriesToggle,pressed=toggle.getAttribute('aria-pressed')==='true';toggle.setAttribute('aria-pressed',String(!pressed));container.querySelectorAll(`[data-series-index="${index}"]`).forEach(element=>element.hidden=pressed)}document.querySelectorAll('[data-series-toggle]').forEach(toggle=>{toggle.addEventListener('click',()=>toggleSeries(toggle));toggle.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();toggleSeries(toggle)}})});document.querySelectorAll('[data-reset-chart]').forEach(button=>button.onclick=()=>{const container=button.closest('[data-chart-container]');container.querySelectorAll('[data-series-toggle]').forEach(toggle=>toggle.setAttribute('aria-pressed','true'));container.querySelectorAll('[data-series-index]').forEach(element=>element.hidden=false);const tooltip=container.querySelector('.chart-tooltip');if(tooltip)tooltip.hidden=true});
</script></body></html>'''
