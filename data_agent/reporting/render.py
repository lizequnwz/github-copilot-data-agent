from __future__ import annotations

import hashlib
import html
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_agent.io import ContractError, envelope, require_string


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
        currency = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}.get(
            code, f"{code} "
        )
    suffix = "%" if style == "percent" else ""
    return f"{currency}{number}{compact_suffix}{suffix}"


def _table_value(value: Any, spec: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)) and not isinstance(value, bool) and spec is not None:
        return _formatted_number(float(value), spec)
    return str(value)


def render_chart(request: dict[str, Any]) -> dict[str, Any]:
    spec = request.get("spec")
    if not isinstance(spec, dict) or spec.get("type") not in {"bar", "line"}:
        raise ContractError("spec.type must be bar or line")
    data = spec.get("data")
    if not isinstance(data, list) or not data or len(data) > 100:
        raise ContractError("spec.data must contain 1 to 100 aggregate points")
    try:
        values = [float(point["value"]) for point in data]
        labels = [str(point["label"]) for point in data]
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("each chart point requires a string label and numeric value") from exc
    if any(not math.isfinite(value) for value in values):
        raise ContractError("chart values must be finite numbers")
    title = str(spec.get("title", "Chart"))
    unit = str(spec.get("unit", ""))
    value_format = spec.get("value_format")
    if value_format is not None:
        _formatted_number(values[0], value_format, compact_default=True)
    unit_suffix = f" {unit}" if unit else ""
    alt_text = str(
        spec.get("alt_text")
        or f"{title}. Values range from {_formatted_number(min(values), value_format, compact_default=True)} to {_formatted_number(max(values), value_format, compact_default=True)}{unit_suffix}."
    )
    width, height = 920, 480
    left, right, top, bottom = 82, 28, 54, 92
    plot_w, plot_h = width - left - right, height - top - bottom
    raw_low, raw_high = min(values), max(values)
    low = min(0.0, raw_low) if spec["type"] == "bar" else raw_low
    high = max(0.0, raw_high) if spec["type"] == "bar" else raw_high
    if high == low:
        high, low = high + 1.0, low - (0.0 if spec["type"] == "bar" else 1.0)
    span = high - low
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="chart-title chart-desc" viewBox="0 0 {width} {height}">',
        f'<title id="chart-title">{html.escape(title)}</title>',
        f'<desc id="chart-desc">{html.escape(alt_text)}</desc>',
        '<g font-family="system-ui,-apple-system,sans-serif" fill="currentColor">',
    ]
    for tick in range(5):
        value = low + (span * tick / 4)
        y = top + plot_h - (tick / 4) * plot_h
        parts.append(
            f'<line x1="{left}" x2="{width-right}" y1="{y:.1f}" y2="{y:.1f}" stroke="currentColor" stroke-opacity=".18" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{left-12}" y="{y+4:.1f}" text-anchor="end" font-size="12">{html.escape(_formatted_number(value, value_format, compact_default=True))}</text>'
        )
    zero_y = top + ((high - 0.0) / span) * plot_h
    parts.append(
        f'<line x1="{left}" x2="{width-right}" y1="{zero_y:.1f}" y2="{zero_y:.1f}" stroke="currentColor" stroke-opacity=".55" stroke-width="1.5"/>'
    )
    if unit:
        parts.append(
            f'<text x="{left}" y="24" font-size="12" font-weight="600">{html.escape(unit)}</text>'
        )

    slot = plot_w / len(values)
    if spec["type"] == "bar":
        for index, (label, value) in enumerate(zip(labels, values)):
            value_y = top + ((high - value) / span) * plot_h
            bar_top = min(value_y, zero_y)
            bar_h = max(abs(value_y - zero_y), 1.5)
            x = left + index * slot + slot * 0.16
            parts.append(
                f'<rect x="{x:.1f}" y="{bar_top:.1f}" width="{slot*0.68:.1f}" height="{bar_h:.1f}" rx="4" fill="#3b82f6"/>'
            )
            label_y = max(bar_top - 8, 16) if value >= 0 else min(bar_top + bar_h + 16, height - bottom + 24)
            parts.append(
                f'<text x="{x+slot*0.34:.1f}" y="{label_y:.1f}" text-anchor="middle" font-size="12" font-weight="600">{html.escape(_formatted_number(value, value_format, compact_default=True))}</text>'
            )
    else:
        points: list[tuple[float, float]] = []
        for index, value in enumerate(values):
            x = left + (index / max(len(values) - 1, 1)) * plot_w
            y = top + ((high - value) / span) * plot_h
            points.append((x, y))
        parts.append(
            '<polyline points="'
            + " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
            + '" fill="none" stroke="#3b82f6" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'
        )
        for (x, y), value in zip(points, values):
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#3b82f6" stroke="currentColor" stroke-width="2"/>')
            parts.append(
                f'<text x="{x:.1f}" y="{max(y-12, 18):.1f}" text-anchor="middle" font-size="12" font-weight="600">{html.escape(_formatted_number(value, value_format, compact_default=True))}</text>'
            )

    label_step = max(1, math.ceil(len(labels) / 12))
    for index, label in enumerate(labels):
        if index % label_step:
            continue
        x = left + (index + 0.5) * slot if spec["type"] == "bar" else left + (index / max(len(labels) - 1, 1)) * plot_w
        short_label = label if len(label) <= 18 else label[:17] + "…"
        parts.append(
            f'<text x="{x:.1f}" y="{height-44}" text-anchor="middle" font-size="12">{html.escape(short_label)}</text>'
        )
    parts.extend(["</g>", "</svg>"])
    svg = "".join(parts)
    return envelope(
        request,
        "success",
        svg=svg,
        content_sha256=hashlib.sha256(svg.encode()).hexdigest(),
        warnings=[],
    )


def render_report(request: dict[str, Any]) -> dict[str, Any]:
    output = Path(require_string(request, "output_path")).resolve()
    if output.suffix.lower() != ".html" or "reports" not in output.parts:
        raise ContractError("output_path must be an HTML file under reports/")
    metadata = request.get("metadata")
    if not isinstance(metadata, dict):
        raise ContractError("metadata must be an object")
    metadata = dict(metadata)
    metadata.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
    validation = request.get("validation")
    if not isinstance(validation, dict) or validation.get("status") != "pass":
        raise ContractError("passing result checks are required")
    required = ["title"]
    missing = [name for name in required if not metadata.get(name)]
    if missing:
        raise ContractError(f"metadata missing: {', '.join(missing)}")
    summary = html.escape(require_string(request, "summary"))
    columns, rows = request.get("columns", []), request.get("rows", [])
    if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
        raise ContractError("columns must be an array of strings")
    if not isinstance(rows, list) or len(rows) > 500:
        raise ContractError("rows must be an array with at most 500 aggregate rows")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ContractError("each row must be an array matching the columns")
    column_formats = request.get("column_formats", {})
    if not isinstance(column_formats, dict):
        raise ContractError("column_formats must be an object keyed by column name")
    unknown_formats = set(column_formats) - set(columns)
    if unknown_formats:
        raise ContractError(
            f"column_formats contains unknown columns: {', '.join(sorted(unknown_formats))}"
        )
    for value in column_formats.values():
        _formatted_number(0.0, value)
    table_head = "".join(f'<th scope="col">{html.escape(str(column))}</th>' for column in columns)
    table_rows = "".join(
        "<tr>"
        + "".join(
            f'<td class="{"number" if isinstance(value, (int, float)) and not isinstance(value, bool) else ""}">{html.escape(_table_value(value, column_formats.get(columns[index])))}</td>'
            for index, value in enumerate(row)
        )
        + "</tr>"
        for row in rows[:500]
    )
    query_details = "".join(
        f'<div class="meta-item"><dt>{html.escape(str(key).replace("_", " ").title())}</dt><dd>{html.escape(str(value))}</dd></div>'
        for key, value in metadata.items()
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
    caveats_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in caveats)
    if not caveats_html:
        caveats_html = "<li>No additional caveats were supplied.</li>"
    methodology = html.escape(str(request.get("methodology", "Not provided")))
    sql = html.escape(str(request.get("sql", "Not available")))
    chart = _safe_chart_svg(request.get("chart_svg"))
    title = html.escape(str(metadata["title"]))
    badges = ['<span class="badge success">Validation passed</span>']
    if metadata.get("data_freshness"):
        badges.append(
            f'<span class="badge">Data: {html.escape(str(metadata["data_freshness"]))}</span>'
        )
    if metadata.get("period"):
        badges.append(f'<span class="badge">Period: {html.escape(str(metadata["period"]))}</span>')
    badges.append(
        f'<span class="badge">Generated: {html.escape(str(metadata["generated_at"]))}</span>'
    )
    badges_html = "".join(badges)
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light dark"><title>{title}</title>
<style>
:root{{--background:#f8fafc;--surface:#fff;--surface-muted:#e9eef6;--text:#172554;--muted:#475569;--primary:#1e40af;--accent:#b45309;--border:#bfdbfe;--ring:#1e40af;--success:#166534;--shadow:0 8px 20px rgba(30,64,175,.08)}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--background);color:var(--text);font:16px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}a{{color:var(--primary)}}a:focus-visible,summary:focus-visible{{outline:3px solid var(--ring);outline-offset:3px}}.skip{{position:absolute;left:-9999px;top:1rem;background:var(--surface);padding:.75rem 1rem;z-index:10}}.skip:focus{{left:1rem}}main{{width:min(1160px,calc(100% - 2rem));margin:0 auto;padding:3rem 0 5rem}}header{{display:grid;gap:1rem;margin-bottom:2rem}}.eyebrow{{color:var(--primary);font-size:.8rem;font-weight:800;letter-spacing:0;text-transform:uppercase}}h1{{font-size:2.5rem;line-height:1.1;letter-spacing:0;margin:0;max-width:24ch}}h2{{font-size:1.35rem;line-height:1.25;margin:0 0 1rem}}p{{max-width:72ch}}.badges{{display:flex;flex-wrap:wrap;gap:.5rem}}.badge{{display:inline-flex;align-items:center;min-height:32px;padding:.25rem .7rem;border:1px solid var(--border);border-radius:8px;background:var(--surface);font-size:.82rem;font-weight:700}}.badge.success{{color:var(--success)}}.grid{{display:grid;grid-template-columns:repeat(12,1fr);gap:1rem}}.card{{grid-column:span 12;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:1.5rem;box-shadow:var(--shadow)}}.summary{{font-size:1.15rem;border-left:5px solid var(--accent)}}.chart svg{{display:block;width:100%;height:auto;color:var(--text);background:transparent}}.table-wrap{{overflow:auto;border:1px solid var(--border);border-radius:8px}}table{{border-collapse:collapse;width:100%;min-width:560px}}th,td{{padding:.7rem .8rem;text-align:left;border-bottom:1px solid var(--border);vertical-align:top}}th{{position:sticky;top:0;background:var(--surface-muted);font-size:.78rem;letter-spacing:0;text-transform:uppercase}}tbody tr:nth-child(even){{background:color-mix(in srgb,var(--surface-muted) 40%,transparent)}}td.number{{font-variant-numeric:tabular-nums;text-align:right}}dl{{margin:0}}.definition,.meta-item{{display:grid;gap:.2rem;padding:.7rem 0;border-bottom:1px solid var(--border)}}dt{{font-weight:800}}dd{{margin:0;color:var(--muted);overflow-wrap:anywhere}}ul{{padding-left:1.25rem}}details{{border:1px solid var(--border);border-radius:8px;padding:.8rem 1rem}}summary{{cursor:pointer;min-height:44px;display:flex;align-items:center;font-weight:800}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#0f172a;color:#e2e8f0;padding:1rem;border-radius:8px;overflow:auto;font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace}}.footer{{margin-top:2rem;color:var(--muted);font-size:.85rem}}
@media(min-width:800px){{.span-7{{grid-column:span 7}}.span-5{{grid-column:span 5}}.span-6{{grid-column:span 6}}}}
@media(prefers-color-scheme:dark){{:root{{--background:#071126;--surface:#0f1d38;--surface-muted:#18294a;--text:#eff6ff;--muted:#bfdbfe;--primary:#93c5fd;--accent:#fbbf24;--border:#29436c;--ring:#93c5fd;--success:#86efac;--shadow:none}}pre{{background:#020617}}}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}
@media print{{body{{background:#fff;color:#111}}main{{width:100%;padding:0}}.card{{box-shadow:none;break-inside:avoid}}details{{border:0;padding:0}}details>summary{{display:none}}details>*{{display:block!important}}}}
</style></head><body><a class="skip" href="#content">Skip to report</a><main id="content"><header><div class="eyebrow">Analysis report</div><h1>{title}</h1><div class="badges">{badges_html}</div></header><div class="grid"><section class="card summary" aria-labelledby="summary-title"><h2 id="summary-title">Answer</h2><p>{summary}</p></section>{chart}<section class="card" aria-labelledby="results-title"><h2 id="results-title">Results</h2><div class="table-wrap" tabindex="0" aria-label="Scrollable result table"><table><thead><tr>{table_head}</tr></thead><tbody>{table_rows}</tbody></table></div></section><section class="card span-7" aria-labelledby="definitions-title"><h2 id="definitions-title">Definitions</h2><dl>{definitions_html}</dl></section><section class="card span-5" aria-labelledby="method-title"><h2 id="method-title">Method</h2><p>{methodology}</p></section><section class="card span-6" aria-labelledby="caveats-title"><h2 id="caveats-title">Notes</h2><ul>{caveats_html}</ul></section><section class="card span-6" aria-labelledby="details-title"><h2 id="details-title">Query details</h2><dl>{query_details}</dl></section><section class="card" aria-labelledby="sql-title"><h2 id="sql-title">SQL</h2><details><summary>Show SQL</summary><pre><code>{sql}</code></pre></details></section></div><p class="footer">Self-contained HTML with no remote scripts, fonts, or assets.</p></main></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    return envelope(
        request,
        "success",
        report_path=str(output),
        content_sha256=hashlib.sha256(document.encode()).hexdigest(),
        warnings=[],
    )


def _safe_chart_svg(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or not value.lstrip().startswith("<svg"):
        raise ContractError("chart_svg must be SVG returned by render-chart")
    blocked = re.compile(
        r"(?is)<(?:script|style|foreignObject)|\bon\w+\s*=|\b(?:href|src)\s*=|url\s*\("
    )
    if blocked.search(value):
        raise ContractError("chart_svg contains blocked active or external content")
    return f'<section class="card chart" aria-labelledby="chart-heading"><h2 id="chart-heading">Chart</h2>{value}</section>'
