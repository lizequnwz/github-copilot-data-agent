from __future__ import annotations

import copy
import html
import json
import re
import secrets
import threading
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from data_agent.io import ContractError, write_json_atomic
from data_agent.semantic.models import load_document
from data_agent.semantic.review import review_semantic, sha256_text, validate_patch_document

ROOT = Path(__file__).resolve().parents[2]
GENERATED_ROOT = (ROOT / "semantic/generated").resolve()
DECISION_VERSION = "1.0"
MAX_REQUEST_BYTES = 1_000_000
_DECISION_KEYS = {"decision_version", "base_model_sha256", "operations"}
_OPERATION_KEYS = {
    "op",
    "path",
    "value",
    "rationale",
    "evidence",
    "confidence",
    "assumptions",
    "intent",
}


@dataclass(frozen=True)
class ReviewPaths:
    raw: Path
    manifest: Path
    draft: Path
    decisions: Path
    patch: Path
    html: Path


def review_paths(raw_path: str | Path, manifest_path: str | Path) -> ReviewPaths:
    raw = _restricted_generated_path(raw_path)
    manifest = _restricted_generated_path(manifest_path)
    stem = raw.name.removesuffix(".raw.osi.yaml")
    return ReviewPaths(
        raw=raw,
        manifest=manifest,
        draft=raw.with_name(f"{stem}.review.draft.json"),
        decisions=raw.with_name(f"{stem}.review.decisions.json"),
        patch=raw.with_name(f"{stem}.review.patch.json"),
        html=raw.with_name(f"{stem}.review.html"),
    )


def default_decisions(raw_path: str | Path) -> dict[str, Any]:
    raw = _restricted_generated_path(raw_path)
    raw_sha = sha256_text(raw.read_text(encoding="utf-8"))
    return {
        "decision_version": DECISION_VERSION,
        "base_model_sha256": raw_sha,
        "operations": [],
    }


def load_decisions(path: str | Path, raw_path: str | Path) -> dict[str, Any]:
    decision_path = Path(path).resolve()
    if decision_path.stat().st_size > MAX_REQUEST_BYTES:
        raise ContractError(f"review decisions exceed {MAX_REQUEST_BYTES} bytes")
    try:
        value = json.loads(decision_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"review decisions must be valid JSON: {exc}") from exc
    validate_decisions(value, raw_path)
    return cast(dict[str, Any], value)


def validate_decisions(value: Any, raw_path: str | Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("review decisions must contain a JSON object")
    unknown = set(value) - _DECISION_KEYS
    if unknown:
        raise ContractError(f"unknown review decision keys: {', '.join(sorted(unknown))}")
    if value.get("decision_version") != DECISION_VERSION:
        raise ContractError(f"decision_version must be {DECISION_VERSION}")
    raw = _restricted_generated_path(raw_path)
    raw_sha = sha256_text(raw.read_text(encoding="utf-8"))
    if value.get("base_model_sha256") != raw_sha:
        raise ContractError("review decisions are stale for the deterministic raw model")
    operations = value.get("operations")
    if not isinstance(operations, list):
        raise ContractError("review decision operations must be an array")
    patch_operations: list[dict[str, Any]] = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise ContractError(f"review decision {index} must be an object")
        extra = set(operation) - _OPERATION_KEYS
        if extra:
            raise ContractError(
                f"unknown keys in review decision {index}: {', '.join(sorted(extra))}"
            )
        normalized = copy.deepcopy(operation)
        normalized["base_model_sha256"] = raw_sha
        normalized.pop("intent", None)
        patch_operations.append(normalized)
    validate_patch_document(
        {
            "patch_version": "1.0",
            "base_model_sha256": raw_sha,
            "operations": patch_operations,
        },
        raw_sha,
    )
    return value


def compile_decisions(value: Any, paths: ReviewPaths) -> dict[str, Any]:
    decisions = validate_decisions(value, paths.raw)
    raw_document = load_document(paths.raw)
    raw_sha = str(decisions["base_model_sha256"])
    operations = _coordinate_renames(raw_document, decisions["operations"], raw_sha)
    patch = {
        "patch_version": "1.0",
        "base_model_sha256": raw_sha,
        "operations": operations,
    }
    validate_patch_document(patch, raw_sha)
    write_json_atomic(paths.decisions, decisions)
    write_json_atomic(paths.patch, patch)
    return patch


def save_draft(value: Any, paths: ReviewPaths) -> Path:
    decisions = validate_decisions(value, paths.raw)
    write_json_atomic(paths.draft, decisions)
    return paths.draft


def build_review_state(
    paths: ReviewPaths,
    *,
    decisions: dict[str, Any] | None = None,
    promotion_enabled: bool = True,
    verify_snowflake: bool = False,
) -> dict[str, Any]:
    raw_document = load_document(paths.raw)
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ContractError("conversion manifest must contain a JSON object")
    active = decisions or _latest_decisions(paths)
    validate_decisions(active, paths.raw)
    models = raw_document.get("semantic_model", [])
    model = models[0] if isinstance(models, list) and models else {}
    if not isinstance(model, dict):
        raise ContractError("raw model does not contain a semantic model object")
    current_issues = manifest.get("issues", [])
    original_issues = manifest.get("conversion_issues", current_issues)
    current_count = len(current_issues) if isinstance(current_issues, list) else 0
    total_count = len(original_issues) if isinstance(original_issues, list) else current_count
    resolved_count = max(total_count - current_count, 0)
    source = manifest.get("source", {})
    review = manifest.get("review", {})
    promotion = manifest.get("promotion", {})
    return {
        "model_name": str(model.get("name", "Semantic model")),
        "source": source if isinstance(source, dict) else {},
        "status": str(manifest.get("status", "review_required")),
        "progress": {
            "resolved": resolved_count,
            "total": total_count,
            "remaining": current_count,
            "pending_edits": len(active["operations"]),
        },
        "issues": current_issues if isinstance(current_issues, list) else [],
        "objects": _editable_objects(model),
        "decisions": active,
        "artifacts": {
            "raw": _relative(paths.raw),
            "manifest": _relative(paths.manifest),
            "draft": _relative(paths.draft),
            "decisions": _relative(paths.decisions),
            "patch": _relative(paths.patch),
            "html": _relative(paths.html),
        },
        "review_result": review if isinstance(review, dict) else {},
        "promotion": promotion if isinstance(promotion, dict) else {},
        "refresh": manifest.get("refresh", {}),
        "promotion_enabled": promotion_enabled,
        "verify_snowflake": verify_snowflake,
    }


def write_static_review(
    paths: ReviewPaths, *, promotion_enabled: bool = True, verify_snowflake: bool = False
) -> Path:
    state = build_review_state(
        paths,
        promotion_enabled=promotion_enabled,
        verify_snowflake=verify_snowflake,
    )
    paths.html.write_text(render_review_html(state), encoding="utf-8")
    return paths.html


class ReviewApplication:
    def __init__(
        self,
        paths: ReviewPaths,
        *,
        request_id: str,
        verify_snowflake: bool,
        config_path: str,
        configuration_confirmed: bool,
        promote_if_clean: bool,
    ) -> None:
        self.paths = paths
        self.request_id = request_id
        self.verify_snowflake = verify_snowflake
        self.config_path = config_path
        self.configuration_confirmed = configuration_confirmed
        self.promote_if_clean = promote_if_clean
        self.token = secrets.token_urlsafe(32)
        self.origin = ""
        self.finished = threading.Event()

    def state(self) -> dict[str, Any]:
        return build_review_state(
            self.paths,
            promotion_enabled=self.promote_if_clean,
            verify_snowflake=self.verify_snowflake,
        )

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        decisions = payload.get("decisions")
        if payload.get("confirm_promote") is not True and self.promote_if_clean:
            raise ContractError("confirm the promotion destination before applying decisions")
        compile_decisions(decisions, self.paths)
        result = review_semantic(
            {
                "request_id": self.request_id,
                "raw_model_path": str(self.paths.raw),
                "manifest_path": str(self.paths.manifest),
                "patch_path": str(self.paths.patch),
                "verify_snowflake": self.verify_snowflake,
                "config_path": self.config_path,
                "configuration_confirmed": self.configuration_confirmed,
                "promote_if_clean": self.promote_if_clean,
            }
        )
        write_static_review(
            self.paths,
            promotion_enabled=self.promote_if_clean,
            verify_snowflake=self.verify_snowflake,
        )
        return {"result": result, "state": self.state()}


def serve_review(
    paths: ReviewPaths,
    *,
    port: int,
    open_browser: bool,
    request_id: str,
    verify_snowflake: bool,
    config_path: str,
    configuration_confirmed: bool,
    promote_if_clean: bool,
) -> dict[str, Any]:
    if port < 0 or port > 65535:
        raise ContractError("review port must be between 0 and 65535")
    app = ReviewApplication(
        paths,
        request_id=request_id,
        verify_snowflake=verify_snowflake,
        config_path=config_path,
        configuration_confirmed=configuration_confirmed,
        promote_if_clean=promote_if_clean,
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler_for(app))
    actual_port = int(server.server_address[1])
    app.origin = f"http://127.0.0.1:{actual_port}"
    url = f"{app.origin}/?token={app.token}"
    write_static_review(
        paths,
        promotion_enabled=promote_if_clean,
        verify_snowflake=verify_snowflake,
    )
    print(f"Review workspace: {url}")
    print(f"Static fallback: {paths.html}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return {"url": url, "finished": app.finished.is_set(), "state": app.state()}


def render_review_html(state: dict[str, Any], *, token: str = "") -> str:
    serialized = json.dumps(state, ensure_ascii=False).replace("</", "<\\/")
    token_json = json.dumps(token)
    title = html.escape(str(state["model_name"]))
    refresh_html = _refresh_summary_html(state.get("refresh"))
    return rf"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark"><title>Review {title}</title>
<style>
:root{{--bg:#f5f7fa;--surface:#fff;--surface-2:#eef2f6;--text:#172033;--muted:#526173;--border:#808da1;--primary:#174ea6;--primary-text:#fff;--success:#14733b;--warning:#8a4b00;--error:#b42318;--ring:#2563eb;--shadow:0 8px 24px rgba(22,34,54,.08)}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}button,input,select,textarea{{font:inherit;color:inherit}}button,input,select,textarea,summary{{min-height:44px}}button{{border:1px solid var(--border);border-radius:8px;background:var(--surface);padding:.6rem 1rem;font-weight:700;cursor:pointer}}button:hover{{border-color:var(--primary)}}button:disabled{{cursor:not-allowed;opacity:.55}}.primary{{background:var(--primary);border-color:var(--primary);color:var(--primary-text)}}.danger{{color:var(--error);border-color:var(--error)}}:focus-visible{{outline:3px solid var(--ring);outline-offset:3px}}.skip{{position:fixed;left:-9999px;top:8px;z-index:99;background:var(--surface);padding:.75rem 1rem}}.skip:focus{{left:8px}}header{{position:sticky;top:0;z-index:20;display:flex;gap:1rem;align-items:center;justify-content:space-between;padding:.75rem clamp(1rem,3vw,2rem);background:var(--surface);border-bottom:1px solid var(--border)}}.identity{{min-width:0}}.eyebrow{{color:var(--muted);font-size:.78rem;font-weight:800;text-transform:uppercase}}h1{{font-size:clamp(1.2rem,2.5vw,1.65rem);line-height:1.25;margin:0;overflow-wrap:anywhere}}h2{{font-size:1.4rem;line-height:1.3;margin:.25rem 0 1rem}}h3{{font-size:1.05rem;line-height:1.35;margin:0}}.header-meta{{display:none;gap:.75rem;color:var(--muted);font-variant-numeric:tabular-nums}}.actions{{display:flex;gap:.5rem;align-items:center}}.shell{{width:min(1440px,100%);margin:auto;padding:1rem}}nav{{display:none}}.mobile-nav{{width:100%;margin-bottom:1rem}}main{{min-width:0}}section[hidden]{{display:none}}.panel,.issue,.object-list{{background:var(--surface);border:1px solid var(--border);border-radius:12px;box-shadow:var(--shadow)}}.panel{{padding:clamp(1rem,3vw,1.5rem);margin-bottom:1rem}}.status-line{{display:flex;flex-wrap:wrap;gap:.5rem 1rem;align-items:center}}.badge{{display:inline-flex;align-items:center;gap:.4rem;padding:.2rem .65rem;border:1px solid var(--border);border-radius:999px;font-size:.84rem;font-weight:750}}.badge svg{{width:16px;height:16px;flex:none}}.success{{color:var(--success)}}.warning{{color:var(--warning)}}.error{{color:var(--error)}}.muted{{color:var(--muted)}}.issue-list{{display:grid;gap:.75rem}}.issue{{padding:1rem;border-left:5px solid var(--warning)}}.issue.blocking{{border-left-color:var(--error)}}.issue p{{margin:.35rem 0 0;color:var(--muted)}}details{{border:1px solid var(--border);border-radius:8px;padding:.35rem .75rem}}summary{{display:flex;align-items:center;cursor:pointer;font-weight:750}}.toolbar{{display:grid;gap:.75rem;margin-bottom:1rem}}label{{display:grid;gap:.3rem;font-weight:700}}.helper{{color:var(--muted);font-size:.86rem;font-weight:400}}input,select,textarea{{width:100%;border:1px solid var(--border);border-radius:8px;background:var(--surface);padding:.6rem .75rem}}textarea{{min-height:112px;resize:vertical}}.object-list{{overflow:hidden}}.object-row{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:.75rem;align-items:center;padding:.75rem 1rem;border-bottom:1px solid var(--border)}}.object-row:last-child{{border:0}}.object-row p{{margin:.2rem 0 0;color:var(--muted);overflow-wrap:anywhere}}.empty{{padding:1rem;color:var(--muted)}}.side-button{{width:100%;text-align:left;border:0;border-radius:8px;background:transparent;margin-bottom:.25rem}}.side-button[aria-current="page"]{{background:var(--surface-2);color:var(--primary)}}dialog{{width:min(720px,calc(100% - 1rem));max-height:calc(100% - 1rem);border:1px solid var(--border);border-radius:12px;background:var(--surface);color:var(--text);padding:0;box-shadow:0 24px 70px rgba(0,0,0,.3)}}dialog::backdrop{{background:rgba(15,23,42,.62)}}.dialog-head,.dialog-foot{{position:sticky;z-index:2;display:flex;gap:.75rem;align-items:center;justify-content:space-between;padding:1rem;background:var(--surface)}}.dialog-head{{top:0;border-bottom:1px solid var(--border)}}.dialog-foot{{bottom:0;border-top:1px solid var(--border)}}.dialog-body{{padding:1rem;display:grid;gap:1rem}}fieldset{{border:1px solid var(--border);border-radius:8px;padding:1rem;display:grid;gap:.85rem}}legend{{font-weight:800;padding:0 .3rem}}.field-error{{color:var(--error);font-size:.86rem}}.error-summary{{border:2px solid var(--error);border-radius:8px;padding:1rem;background:var(--surface-2)}}.error-summary:empty{{display:none}}.unsaved{{font-weight:750;color:var(--warning)}}.live{{position:fixed;left:-9999px}}.path{{font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted);overflow-wrap:anywhere}}.result-grid{{display:grid;gap:.75rem}}.result-grid div{{padding:.75rem;background:var(--surface-2);border-radius:8px}}.result-grid dt{{font-weight:800}}.result-grid dd{{margin:0;overflow-wrap:anywhere}}.advanced-row{{display:grid;gap:.75rem}}.toast{{position:fixed;right:1rem;bottom:1rem;z-index:40;max-width:min(420px,calc(100% - 2rem));padding:1rem;border-radius:8px;background:var(--text);color:var(--surface);box-shadow:var(--shadow)}}
@media(max-width:767px){{header{{display:grid;grid-template-columns:minmax(0,1fr)}}.actions{{display:grid;grid-template-columns:1fr 2fr}}.actions button{{min-width:0}}}}
@media(min-width:768px){{.header-meta{{display:flex}}.shell{{display:grid;grid-template-columns:220px minmax(0,1fr);gap:1rem;padding:1.5rem}}nav{{display:block;position:sticky;top:92px;align-self:start;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:.75rem}}.mobile-nav{{display:none}}.toolbar{{grid-template-columns:minmax(220px,1fr) 220px}}.result-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(min-width:1024px){{.shell{{grid-template-columns:240px minmax(0,1fr);gap:1.5rem;padding:2rem}}}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0b1220;--surface:#121d2f;--surface-2:#1b2940;--text:#edf2f8;--muted:#b3c0d2;--border:#6d7f9b;--primary:#8bb8ff;--primary-text:#07111f;--success:#72d69a;--warning:#ffc266;--error:#ff938a;--ring:#9dc4ff;--shadow:none}}}}
@media(prefers-reduced-motion:reduce){{*{{scroll-behavior:auto!important;transition:none!important;animation:none!important}}}}
</style></head><body><a class="skip" href="#workspace">Skip to review workspace</a>
<header><div class="identity"><div class="eyebrow">Semantic review</div><h1>{title}</h1></div><div class="header-meta"><span id="progressText"></span><span id="dirtyState">Draft saved</span></div><div class="actions"><label class="role-filter">Review as<select id="roleFilter"><option value="all">All reviewers</option><option value="business">Business</option><option value="analyst">Analyst</option></select></label><button id="finishButton" type="button">Finish</button><button id="applyButton" class="primary" type="button">Apply and validate</button></div></header>
<div class="shell"><nav aria-label="Review sections" id="sideNav"></nav><main id="workspace" tabindex="-1"><label class="mobile-nav">Review section<select id="sectionSelect"></select></label>{refresh_html}<div id="content"></div></main></div>
<dialog id="editor"><form method="dialog" id="editorForm"><div class="dialog-head"><div><div class="eyebrow" id="editorType"></div><h2 id="editorTitle">Edit semantic object</h2></div><button value="cancel" aria-label="Close editor">Close</button></div><div class="dialog-body"><div id="errorSummary" class="error-summary" tabindex="-1"></div><div id="propertyFields"></div><fieldset><legend>Review evidence</legend><label>Rationale<span class="helper">Why this semantic change is correct and useful.</span><textarea id="rationale" required></textarea><span class="field-error" id="rationaleError"></span></label><label>Evidence type<select id="evidenceType"><option value="user">Business owner or user</option><option value="source_metadata">Source metadata</option><option value="snowflake_metadata">Snowflake metadata</option><option value="official_spec">Official specification</option><option value="inference">Documented inference</option></select></label><label>Evidence reference<span class="helper">Point to the export, conversation, query, or specification.</span><input id="evidenceReference" required><span class="field-error" id="evidenceError"></span></label><label>Confidence<select id="confidence"><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label><label>Assumptions<span class="helper">One per line. Leave blank only when none remain.</span><textarea id="assumptions"></textarea></label></fieldset></div><div class="dialog-foot"><button id="removeButton" class="danger" type="button">Remove object</button><div><button value="cancel">Cancel</button> <button id="saveButton" class="primary" type="button">Save to draft</button></div></div></form></dialog>
<div class="live" role="status" aria-live="polite" id="live"></div><script>const INITIAL={serialized};const TOKEN={token_json};
let state=INITIAL,active=sessionStorage.getItem('semantic-review-section')||(INITIAL.progress.remaining?'issues':'overview'),reviewRole=sessionStorage.getItem('semantic-review-role')||'all',dirty=false,editorObject=null,translationChoice=null,saveTimer=null;const sections=['overview','issues','datasets','fields','metrics','relationships','ai_context'],roleSections={{all:sections,business:['overview','issues','metrics','ai_context'],analyst:['overview','issues','datasets','fields','metrics','relationships']}};const labels={{overview:'Overview',issues:'Blocking issues',datasets:'Datasets',fields:'Fields',metrics:'Metrics',relationships:'Relationships',ai_context:'AI context'}};
const icon=(kind)=>kind==='error'?'<svg viewBox="0 0 20 20" aria-hidden="true"><path fill="currentColor" d="M10 1 19 18H1L10 1Zm-1 6v5h2V7H9Zm0 7v2h2v-2H9Z"/></svg>':kind==='success'?'<svg viewBox="0 0 20 20" aria-hidden="true"><path fill="currentColor" d="m8.2 14.6-4.4-4.4 1.4-1.4 3 3 6.6-6.6 1.4 1.4-8 8Z"/></svg>':'<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="2"/><path d="M9 9h2v6H9zm0-4h2v2H9z" fill="currentColor"/></svg>';
function esc(v){{return String(v??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]))}}function announce(v){{document.getElementById('live').textContent=v}}function setDirty(v){{dirty=v;document.getElementById('dirtyState').textContent=v?'Unsaved changes':'Draft saved';document.getElementById('dirtyState').className=v?'unsaved':''}}
function operationFor(path){{return state.decisions.operations.find(o=>o.path===path)}}function shownValue(prop){{const op=operationFor(prop.path);return op&&op.op!=='remove'?op.value:prop.value}}function valueText(prop){{const value=shownValue(prop);return prop.kind==='text'?String(value??''):JSON.stringify(value??null,null,2)}}
function renderNav(){{const visible=roleSections[reviewRole]||sections;if(!visible.includes(active))active=visible[0];const nav=document.getElementById('sideNav'),sel=document.getElementById('sectionSelect');nav.innerHTML=visible.map(s=>`<button class="side-button" data-section="${{s}}" aria-current="${{active===s?'page':'false'}}">${{labels[s]}}</button>`).join('');sel.innerHTML=visible.map(s=>`<option value="${{s}}" ${{active===s?'selected':''}}>${{labels[s]}}</option>`).join('');nav.querySelectorAll('button').forEach(b=>b.onclick=()=>showSection(b.dataset.section));sel.onchange=()=>showSection(sel.value);const role=document.getElementById('roleFilter');role.value=reviewRole;role.onchange=()=>{{reviewRole=role.value;sessionStorage.setItem('semantic-review-role',reviewRole);render()}}}}
function showSection(section){{active=sections.includes(section)?section:'overview';sessionStorage.setItem('semantic-review-section',active);render()}}
function progress(){{const p=state.progress;document.getElementById('progressText').textContent=`${{p.resolved}} of ${{p.total}} issues resolved`;document.getElementById('applyButton').disabled=false}}
function issueHtml(i){{const blocking=i.severity==='blocking',element=String(i.element||''),target=state.objects.find(o=>element===state.model_name&&o.id==='model'||element.endsWith('.'+o.name));return `<article class="issue ${{blocking?'blocking':''}}"><span class="badge ${{blocking?'error':'warning'}}">${{icon(blocking?'error':'info')}}${{esc(i.severity||'review')}}</span><h3>${{esc(i.code||'Review issue')}}</h3><p>${{esc(i.message||'')}}</p><p class="path">${{esc(i.element||'model')}}</p>${{target?`<button type="button" data-object="${{esc(target.id)}}">Review ${{esc(labels[target.section].toLowerCase())}}</button>`:''}}</article>`}}
function issueGroups(){{const blocking=state.issues.filter(i=>i.severity==='blocking'),review=state.issues.filter(i=>i.severity!=='blocking'),groups=Object.values(review.reduce((all,item)=>{{(all[item.code]??=[]).push(item);return all}},{{}})),notice=`<p class="${{blocking.length?'error':'success'}}">${{blocking.length?blocking.length+' blocking issues require correction.':'No blocking issues. '+review.length+' review decisions remain.'}}</p>`,reviewHtml=groups.map(items=>items.length===1?issueHtml(items[0]):`<details><summary>${{items.length}} ${{esc(items[0].code)}} decisions</summary><div class="issue-list">${{items.map(issueHtml).join('')}}</div></details>`).join('');return notice+blocking.map(issueHtml).join('')+reviewHtml}}
function objectRows(kind){{const objects=state.objects.filter(o=>o.section===kind);if(!objects.length)return '<div class="empty">No objects in this section.</div>';const hasTranslations=objects.some(o=>o.translation);return `<div class="toolbar"><label>Search ${{esc(labels[kind].toLowerCase())}}<input id="objectSearch" type="search" placeholder="Search by name or path"></label><label>Filter<select id="objectFilter"><option value="all">All objects</option><option value="changed">Changed only</option></select></label></div>${{hasTranslations?'<p><button id="bulkTranslation" type="button">Review selected translations</button></p>':''}}<div class="object-list" id="objectList">${{objects.map(o=>`<div class="object-row" data-search="${{esc((o.name+' '+o.context+' '+o.path).toLowerCase())}}" data-changed="${{o.properties.some(p=>operationFor(p.path))}}"><div>${{o.translation?`<label><input type="checkbox" data-bulk-object="${{esc(o.id)}}"> Select for shared translation decision</label>`:''}}<h3>${{esc(o.name)}}</h3><p>${{esc(o.context)}}</p></div><button type="button" data-object="${{esc(o.id)}}">Review</button></div>`).join('')}}</div>`}}
function overview(){{const p=state.progress,src=state.source||{{}},promotion=state.promotion||{{}},applied=!!state.review_result?.validation,decisionCount=state.decisions.operations.length,pending=state.decisions.operations.map((o,i)=>`<div class="object-row"><div><strong>${{esc(o.op)}} ${{esc(o.path)}}</strong><p>${{esc(o.rationale)}}</p></div><button type="button" data-undo="${{i}}">Undo</button></div>`).join('');return `<section class="panel"><div class="eyebrow">Readiness</div><h2>Resolve meaning before promotion</h2><div class="status-line"><span class="badge ${{p.remaining?'warning':'success'}}">${{icon(p.remaining?'info':'success')}}${{p.remaining}} issues remaining</span><span>${{decisionCount}} ${{applied?'reviewed decisions':'pending edits'}}</span><span class="muted">Status: ${{esc(state.status)}}</span></div><p>Business users confirm meaning and exclusions. Analysts confirm mappings, keys, relationships, and expressions. The agent compiles every approved decision into an audited patch, validates Ossie, and promotes only a clean result.</p></section>${{pending?`<section class="panel"><h2>${{applied?'Reviewed decisions':'Pending changes'}}</h2><div class="object-list">${{pending}}</div></section>`:''}}<section class="panel"><h2>Source and artifacts</h2><dl class="result-grid"><div><dt>Source</dt><dd>${{esc(src.path||'Unknown')}}</dd></div><div><dt>Source type</dt><dd>${{esc(src.type||'Unknown')}}</dd></div><div><dt>Raw model</dt><dd>${{esc(state.artifacts.raw)}}</dd></div><div><dt>Promotion</dt><dd>${{promotion.promoted?'Promoted to '+esc(promotion.model_path):promotion.eligible&&state.promotion_enabled?'Eligible after confirmation':state.promotion_enabled?'Not yet eligible':'Promotion disabled for this run'}}</dd></div></dl></section><section class="panel"><h2>Advanced operation</h2><details><summary>Add or remove an object with JSON Pointer</summary><div class="advanced-row"><label>Operation<select id="advancedOp"><option>add</option><option>replace</option><option>remove</option></select></label><label>Path<input id="advancedPath" placeholder="/semantic_model/0/metrics/-"></label><label>JSON value<textarea id="advancedValue" placeholder='{{"name":"metric_name"}}'></textarea></label><button id="advancedAdd" type="button">Open evidence editor</button></div></details></section>`}}
function results(){{const r=state.review_result||{{}},p=state.promotion||{{}};if(!r.validation)return '';const audit=(r.operations||[]).map(o=>`<details><summary>${{esc(o.op)}} ${{esc(o.path)}}</summary><dl class="result-grid"><div><dt>Before</dt><dd class="path">${{esc(JSON.stringify(o.before,null,2))}}</dd></div><div><dt>After</dt><dd class="path">${{esc(JSON.stringify(o.after,null,2))}}</dd></div></dl></details>`).join('');return `<section class="panel"><h2>Latest validation result</h2><dl class="result-grid"><div><dt>Official Ossie</dt><dd>${{r.validation?.official_valid?'Valid':'Needs correction'}}</dd></div><div><dt>Analysis ready</dt><dd>${{r.validation?.analysis_ready?'Yes':'No'}}</dd></div><div><dt>Final model</dt><dd>${{esc(r.final_model_path||'Not written')}}</dd></div><div><dt>Promotion</dt><dd>${{p.promoted?'Promoted to '+esc(p.model_path):'Not promoted'}}</dd></div></dl>${{audit?`<h3>Before and after</h3>${{audit}}`:''}}${{(r.unresolved_assumptions||[]).length?`<details><summary>${{r.unresolved_assumptions.length}} unresolved assumptions</summary><ul>${{r.unresolved_assumptions.map(a=>`<li>${{esc(a)}}</li>`).join('')}}</ul></details>`:''}}</section>`}}
function render(){{const scroll=Number(sessionStorage.getItem('semantic-review-scroll-'+active)||0);renderNav();progress();let body='';if(active==='overview')body=overview()+results();else if(active==='issues')body=`<section class="panel"><h2>Blocking issues and decisions</h2><p class="muted">Address required decisions first. Repeated and informational details stay compact.</p><div class="issue-list">${{state.issues.length?issueGroups():'<p class="success">No remaining review issues.</p>'}}</div></section>`;else body=`<section class="panel"><h2>${{labels[active]}}</h2><p class="muted">Search the object list, then review one focused editor at a time.</p>${{objectRows(active)}}</section>`;document.getElementById('content').innerHTML=body;document.querySelectorAll('[data-object]').forEach(b=>b.onclick=()=>openObject(b.dataset.object));document.querySelectorAll('[data-undo]').forEach(b=>b.onclick=()=>{{state.decisions.operations.splice(Number(b.dataset.undo),1);setDirty(true);scheduleDraft();render();announce('Pending change undone.')}});const search=document.getElementById('objectSearch'),filter=document.getElementById('objectFilter');if(search){{const saved=sessionStorage.getItem('semantic-review-search-'+active)||'';search.value=saved;search.oninput=()=>{{sessionStorage.setItem('semantic-review-search-'+active,search.value);filterRows()}};filter.onchange=filterRows;filterRows()}}const add=document.getElementById('advancedAdd');if(add)add.onclick=openAdvanced;const bulk=document.getElementById('bulkTranslation');if(bulk)bulk.onclick=openBulk;requestAnimationFrame(()=>scrollTo(0,scroll))}}
function filterRows(){{const q=document.getElementById('objectSearch').value.toLowerCase(),f=document.getElementById('objectFilter').value;document.querySelectorAll('.object-row').forEach(row=>row.hidden=!row.dataset.search.includes(q)||(f==='changed'&&row.dataset.changed!=='true'))}}
function keySelect(prop,selected){{return `<select data-key-select multiple size="${{Math.min(Math.max((prop.options||[]).length,2),8)}}">${{(prop.options||[]).map(v=>`<option ${{selected.includes(v)?'selected':''}}>${{esc(v)}}</option>`).join('')}}</select>`}}
function propertyInput(prop){{const value=shownValue(prop);let control='';if(prop.kind==='text')control=`<input data-value value="${{esc(String(value??''))}}">`;else if(prop.kind==='select')control=`<select data-value>${{(prop.options||[]).map(v=>`<option ${{v===value?'selected':''}}>${{esc(v)}}</option>`).join('')}}</select>`;else if(prop.kind==='multi_select')control=`<select data-value multiple size="${{Math.min(Math.max((prop.options||[]).length,2),8)}}">${{(prop.options||[]).map(v=>`<option ${{(value||[]).includes(v)?'selected':''}}>${{esc(v)}}</option>`).join('')}}</select>`;else if(prop.kind==='string_list')control=`<textarea data-value placeholder="One field per line">${{esc((value||[]).join('\n'))}}</textarea>`;else if(prop.kind==='key_lists')control=`<textarea data-value placeholder="One key per line; separate composite fields with commas">${{esc((value||[]).map(v=>Array.isArray(v)?v.join(', '):v).join('\n'))}}</textarea>`;else if(prop.kind==='key_selects'){{const keys=value?.length?value:[[]];control=`<div data-key-list>${{keys.map(key=>keySelect(prop,key)).join('')}}</div><button type="button" data-add-key="${{esc(prop.path)}}">Add another unique key</button>`}}else if(prop.kind==='dimension')control=`<label><input data-value type="checkbox" ${{value?.is_time?'checked':''}}> Time dimension</label>`;else if(prop.kind==='ai_context'){{const v=value||{{}};control=`<label>Instructions<textarea data-part="instructions">${{esc(v.instructions||'')}}</textarea></label><label>Synonyms<span class="helper">One per line</span><textarea data-part="synonyms">${{esc((v.synonyms||[]).join('\n'))}}</textarea></label><label>Example questions<span class="helper">One per line</span><textarea data-part="examples">${{esc((v.examples||[]).join('\n'))}}</textarea></label>`}}else if(prop.kind==='expression'){{const dialects=value?.dialects?.length?value.dialects:[{{dialect:'ANSI_SQL',expression:''}}];control=dialects.map((d,i)=>`<div class="result-grid"><label>Dialect<input data-dialect="${{i}}" value="${{esc(d.dialect||'')}}"></label><label>Expression<textarea data-expression="${{i}}">${{esc(d.expression||'')}}</textarea></label></div>`).join('')}}return `<div class="property-field" data-property data-path="${{esc(prop.path)}}"><label>${{esc(prop.label)}}<span class="helper">${{esc(prop.help)}}</span></label>${{control}}<span class="field-error" data-error="${{esc(prop.path)}}"></span></div>`}}
function translationPanel(t){{if(!t)return '';const accept=t.can_accept?'<button type="button" data-translation="accepted">Accept translation</button>':'';return `<fieldset><legend>Translation decision</legend><p><strong>Status:</strong> ${{esc(t.status)}}</p><p><strong>Source expression:</strong> <span class="path">${{esc(typeof t.source_expression==='string'?t.source_expression:JSON.stringify(t.source_expression))}}</span></p><div class="status-line">${{accept}}<button type="button" data-translation="unsupported">Retain as reviewed unsupported</button><button type="button" data-translation="requested">Request evidence</button></div><p class="helper" id="translationState">Choose how this source translation should be treated. A reviewed-unsupported decision preserves the source evidence, excludes the construct from executable OSI, and clears its promotion blocker.</p></fieldset>`}}
function openObject(id){{editorObject=state.objects.find(o=>o.id===id);translationChoice=null;document.getElementById('editorType').textContent=labels[editorObject.section];document.getElementById('editorTitle').textContent=editorObject.name;document.getElementById('propertyFields').innerHTML=`<fieldset><legend>Semantic values</legend>${{editorObject.properties.map(propertyInput).join('')}}</fieldset>${{translationPanel(editorObject.translation)}}`;document.querySelectorAll('#propertyFields [data-property]').forEach(input=>input.addEventListener('focusout',()=>validateProperty(input)));document.querySelectorAll('[data-add-key]').forEach(button=>button.onclick=()=>{{const prop=editorObject.properties.find(item=>item.path===button.dataset.addKey);button.previousElementSibling.insertAdjacentHTML('beforeend',keySelect(prop,[]))}});document.querySelectorAll('[data-translation]').forEach(button=>button.onclick=()=>{{translationChoice=button.dataset.translation;document.getElementById('translationState').textContent='Selected: '+button.textContent;announce(button.textContent+' selected.')}});document.getElementById('removeButton').hidden=editorObject.protected===true;clearAudit();document.getElementById('editor').showModal();document.querySelector('#propertyFields input,#propertyFields textarea,#propertyFields select')?.focus()}}
function openAdvanced(){{const op=document.getElementById('advancedOp').value,path=document.getElementById('advancedPath').value.trim();let value;try{{if(op!=='remove')value=JSON.parse(document.getElementById('advancedValue').value)}}catch(e){{announce('Advanced value must be valid JSON.');return}}editorObject={{id:'advanced',name:'Advanced operation',section:'overview',path,advancedOp:op,advancedValue:value,properties:[]}};document.getElementById('editorType').textContent='Advanced';document.getElementById('editorTitle').textContent='Review advanced operation';document.getElementById('propertyFields').innerHTML=`<p class="path">${{esc(op)}} ${{esc(path)}}</p>`;document.getElementById('removeButton').hidden=true;clearAudit();document.getElementById('editor').showModal();document.getElementById('rationale').focus()}}
function openBulk(){{const selected=[...document.querySelectorAll('[data-bulk-object]:checked')].map(input=>state.objects.find(o=>o.id===input.dataset.bulkObject)).filter(Boolean);if(!selected.length){{announce('Select at least one translation.');return}}const statuses=new Set(selected.map(o=>o.translation.status));if(statuses.size!==1){{announce('Bulk review requires translations with the same status.');return}}editorObject={{id:'bulk',name:'Shared translation decision',section:active,bulkTranslation:selected,properties:[]}};translationChoice=null;document.getElementById('editorType').textContent='Bulk translation review';document.getElementById('editorTitle').textContent=`Review ${{selected.length}} selected translations`;document.getElementById('propertyFields').innerHTML=`<p>One decision and evidence record will be applied individually to each selected item.</p>${{translationPanel(selected[0].translation)}}`;document.querySelectorAll('[data-translation]').forEach(button=>button.onclick=()=>{{translationChoice=button.dataset.translation;document.getElementById('translationState').textContent='Selected: '+button.textContent}});document.getElementById('removeButton').hidden=true;clearAudit();document.getElementById('editor').showModal();document.getElementById('rationale').focus()}}
function clearAudit(){{document.getElementById('rationale').value='';document.getElementById('evidenceReference').value='';document.getElementById('assumptions').value='';document.getElementById('confidence').value='high';document.getElementById('errorSummary').textContent='';document.querySelectorAll('.field-error').forEach(e=>e.textContent='')}}
function readProperty(node,prop){{if(prop.kind==='text'||prop.kind==='select')return node.querySelector('[data-value]').value;if(prop.kind==='multi_select')return[...node.querySelector('[data-value]').selectedOptions].map(option=>option.value);if(prop.kind==='string_list')return node.querySelector('[data-value]').value.split('\n').map(v=>v.trim()).filter(Boolean);if(prop.kind==='key_lists')return node.querySelector('[data-value]').value.split('\n').map(v=>v.split(',').map(x=>x.trim()).filter(Boolean)).filter(v=>v.length);if(prop.kind==='key_selects')return[...node.querySelectorAll('[data-key-select]')].map(select=>[...select.selectedOptions].map(option=>option.value)).filter(key=>key.length);if(prop.kind==='dimension')return{{is_time:node.querySelector('[data-value]').checked}};if(prop.kind==='ai_context'){{const result={{}},instructions=node.querySelector('[data-part="instructions"]').value.trim(),synonyms=node.querySelector('[data-part="synonyms"]').value.split('\n').map(v=>v.trim()).filter(Boolean),examples=node.querySelector('[data-part="examples"]').value.split('\n').map(v=>v.trim()).filter(Boolean);if(instructions)result.instructions=instructions;if(synonyms.length)result.synonyms=synonyms;if(examples.length)result.examples=examples;return result}}if(prop.kind==='expression')return{{dialects:[...node.querySelectorAll('[data-dialect]')].map(input=>({{dialect:input.value.trim(),expression:node.querySelector(`[data-expression="${{input.dataset.dialect}}"]`).value.trim()}}))}};return null}}
function emptyValue(value){{return value===null||value===undefined||value===''||(Array.isArray(value)&&value.length===0)||(typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===0)}}
function validateProperty(node){{const prop=editorObject?.properties?.find(p=>p.path===node.dataset.path),error=node.querySelector('.field-error');if(!prop)return true;const value=readProperty(node,prop);let message='';if(prop.label==='Name'&&!String(value).trim())message='Name is required.';if(prop.kind==='expression'&&value.dialects.some(d=>!d.dialect||!d.expression))message='Every expression needs a dialect and value.';error.textContent=message;return !message}}
function audit(){{return{{rationale:document.getElementById('rationale').value.trim(),evidence:[{{type:document.getElementById('evidenceType').value,reference:document.getElementById('evidenceReference').value.trim()}}],confidence:document.getElementById('confidence').value,assumptions:document.getElementById('assumptions').value.split('\n').map(v=>v.trim()).filter(Boolean)}}}}
function validateAudit(){{const a=audit(),errors=[];if(!a.rationale)errors.push(['rationale','Explain why this change is correct.']);if(!a.evidence[0].reference)errors.push(['evidence','Provide a verifiable evidence reference.']);document.getElementById('rationaleError').textContent=errors.find(e=>e[0]==='rationale')?.[1]||'';document.getElementById('evidenceError').textContent=errors.find(e=>e[0]==='evidence')?.[1]||'';const summary=document.getElementById('errorSummary');summary.innerHTML=errors.map(e=>`<div>${{esc(e[1])}}</div>`).join('');if(errors.length){{summary.focus();document.getElementById(errors[0][0]==='rationale'?'rationale':'evidenceReference').focus();return null}}return a}}
function upsert(op){{const i=state.decisions.operations.findIndex(v=>v.path===op.path);if(i>=0)state.decisions.operations[i]=op;else state.decisions.operations.push(op)}}function removePending(path){{state.decisions.operations=state.decisions.operations.filter(o=>o.path!==path)}}
function saveEditor(){{const inputs=[...document.querySelectorAll('#propertyFields [data-property]')],invalid=inputs.find(input=>!validateProperty(input));if(invalid){{document.getElementById('errorSummary').textContent='Correct the highlighted semantic value.';document.getElementById('errorSummary').focus();invalid.querySelector('input,textarea,select')?.focus();return}}const a=validateAudit();if(!a)return;if(editorObject.bulkTranslation){{if(!translationChoice){{document.getElementById('errorSummary').textContent='Choose a translation decision for the selected items.';return}}for(const item of editorObject.bulkTranslation)upsert({{op:'replace',path:item.translation.path,value:item.translation[translationChoice+'_value'],...a}})}}else if(editorObject.advancedOp){{if(!editorObject.path?.startsWith('/')){{document.getElementById('errorSummary').textContent='Path must be a JSON Pointer beginning with /.';return}}upsert({{op:editorObject.advancedOp,path:editorObject.path,...(editorObject.advancedOp==='remove'?{{}}:{{value:editorObject.advancedValue}}),...a}})}}else{{let expressionChanged=false;for(const prop of editorObject.properties){{const input=inputs.find(el=>el.dataset.path===prop.path),value=readProperty(input,prop);if((!prop.exists&&emptyValue(value))||JSON.stringify(value)===JSON.stringify(prop.value))removePending(prop.path);else{{upsert({{op:prop.exists?'replace':'add',path:prop.path,value,...a,...(prop.label==='Name'?{{intent:'rename'}}:{{}})}});if(prop.kind==='expression')expressionChanged=true}}}}if(editorObject.translation){{const choice=translationChoice||(expressionChanged?'accepted':null);if(choice)upsert({{op:'replace',path:editorObject.translation.path,value:editorObject.translation[choice+'_value'],...a}})}}}}setDirty(true);scheduleDraft();document.getElementById('editor').close();announce('Changes saved to the review draft.');render()}}
function removeObject(){{if(!confirm(`Remove ${{editorObject.name}}? You can undo before Apply.`))return;const a=validateAudit();if(!a)return;upsert({{op:'remove',path:editorObject.path,...a}});setDirty(true);scheduleDraft();document.getElementById('editor').close();announce('Object marked for removal.');render()}}
function scheduleDraft(){{clearTimeout(saveTimer);saveTimer=setTimeout(saveDraft,800)}}async function api(path,payload){{const response=await fetch(path,{{method:'POST',headers:{{'Content-Type':'application/json','X-Review-Token':TOKEN}},body:JSON.stringify(payload)}});const body=await response.json();if(!response.ok)throw new Error(body.error||'Request failed');return body}}
async function saveDraft(){{if(!TOKEN){{setDirty(true);return}}try{{await api('/api/draft',{{decisions:state.decisions}});setDirty(false);announce('Draft saved.')}}catch(e){{setDirty(true);announce('Draft could not be saved: '+e.message)}}}}
async function applyAll(){{if(!TOKEN){{downloadDecisions();return}}const destination=state.promotion?.model_path||`semantic/models/${{String(state.model_name).toLowerCase().replace(/[^a-z0-9]+/g,'_')}}.yaml`,confirmation=state.promotion_enabled?`Apply the complete audited decisions, validate Ossie, and promote to ${{destination}} if clean?`:'Apply the complete audited decisions and validate Ossie without promotion?';if(!confirm(confirmation))return;const button=document.getElementById('applyButton'),steps=['Compiling decisions','Applying patch','Validating Ossie',...(state.verify_snowflake?['Verifying Snowflake']:[]),...(state.promotion_enabled?['Promoting when eligible']:[])];let step=0;button.disabled=true;button.textContent=steps[0]+'…';announce(steps[0]+'.');const progressTimer=setInterval(()=>{{step=Math.min(step+1,steps.length-1);button.textContent=steps[step]+'…';announce(steps[step]+'.')}},700);try{{const body=await api('/api/apply',{{decisions:state.decisions,confirm_promote:true}});state=body.state;setDirty(false);render();announce(body.result.promoted?'Validation passed and model promoted.':'Apply complete. Review the validation result.');showToast(body.result.promoted?'Model validated and promoted.':'Apply and validation complete.')}}catch(e){{announce('Apply failed: '+e.message);showToast('Apply failed: '+e.message,true)}}finally{{clearInterval(progressTimer);button.disabled=false;button.textContent='Apply and validate'}}}}
function downloadDecisions(){{const blob=new Blob([JSON.stringify(state.decisions,null,2)+'\n'],{{type:'application/json'}}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=state.artifacts.decisions.split('/').pop();a.click();URL.revokeObjectURL(a.href);announce('Decisions JSON downloaded for later application.')}}async function finish(){{if(dirty&&!confirm('Finish with an unsaved browser draft?'))return;if(TOKEN){{try{{await api('/api/finish',{{}})}}catch(e){{showToast(e.message,true);return}}}}showToast('Review session finished. You may close this tab.')}}function showToast(message,isError=false){{const old=document.querySelector('.toast');if(old)old.remove();const el=document.createElement('div');el.className='toast';el.setAttribute('role',isError?'alert':'status');el.textContent=message;document.body.append(el);setTimeout(()=>el.remove(),6000)}}
document.getElementById('saveButton').onclick=saveEditor;document.getElementById('removeButton').onclick=removeObject;document.getElementById('applyButton').onclick=applyAll;document.getElementById('finishButton').onclick=finish;if(!TOKEN)document.getElementById('applyButton').textContent='Download decisions';let scrollTimer;window.addEventListener('scroll',()=>{{clearTimeout(scrollTimer);scrollTimer=setTimeout(()=>sessionStorage.setItem('semantic-review-scroll-'+active,String(scrollY)),120)}});window.addEventListener('beforeunload',e=>{{if(dirty){{e.preventDefault();e.returnValue='' }}}});render();</script></body></html>"""


def _refresh_summary_html(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    summary = value.get("summary", {})
    changes = value.get("changes", [])
    if not isinstance(summary, dict) or not isinstance(changes, list):
        return ""
    status = "Existing promoted model" if value.get("status") == "refresh" else "New model"
    items = []
    for change in changes:
        if not isinstance(change, dict):
            continue
        label = " ".join(
            [
                str(change.get("impact", "metadata")),
                str(change.get("kind", "object")),
                str(change.get("object", "unknown")),
                str(change.get("change_type", "changed")),
            ]
        )
        items.append(f"<li>{html.escape(label)}</li>")
    details = ""
    if items:
        details = (
            f"<details><summary>Review {len(items)} object-level changes</summary>"
            f"<ul>{''.join(items)}</ul></details>"
        )
    return (
        '<section class="panel" aria-labelledby="refresh-heading">'
        '<div class="eyebrow">Refresh impact</div>'
        '<h2 id="refresh-heading">Changes from the promoted model</h2>'
        f"<p>{html.escape(status)}: {int(summary.get('added', 0))} added, "
        f"{int(summary.get('removed', 0))} removed, "
        f"{int(summary.get('changed', 0))} changed.</p>"
        f"{details}</section>"
    )


def _handler_for(app: ReviewApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "SemanticReview/1.0"

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            supplied = parse_qs(parsed.query).get("token", [""])[0]
            if parsed.path == "/" and secrets.compare_digest(supplied, app.token):
                self._html(render_review_html(app.state(), token=app.token))
                return
            if parsed.path == "/api/state":
                if not self._authorized(require_origin=False):
                    return
                self._json(HTTPStatus.OK, app.state())
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized(require_origin=True):
                return
            try:
                payload = self._body()
                if self.path == "/api/draft":
                    save_draft(payload.get("decisions"), app.paths)
                    self._json(HTTPStatus.OK, {"status": "saved"})
                elif self.path == "/api/apply":
                    self._json(HTTPStatus.OK, app.apply(payload))
                elif self.path == "/api/finish":
                    app.finished.set()
                    self._json(HTTPStatus.OK, {"status": "finished"})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except (ContractError, OSError, ValueError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def _authorized(self, *, require_origin: bool) -> bool:
            token = self.headers.get("X-Review-Token", "")
            if not secrets.compare_digest(token, app.token):
                self._json(HTTPStatus.FORBIDDEN, {"error": "invalid review session token"})
                return False
            if require_origin and self.headers.get("Origin") != app.origin:
                self._json(HTTPStatus.FORBIDDEN, {"error": "invalid request origin"})
                return False
            return True

        def _body(self) -> dict[str, Any]:
            if self.headers.get_content_type() != "application/json":
                raise ContractError("requests must use application/json")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ContractError("invalid Content-Length") from exc
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ContractError(f"request body must be 1 to {MAX_REQUEST_BYTES} bytes")
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, dict):
                raise ContractError("request body must be a JSON object")
            return value

        def _headers(self, content_type: str, length: int) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
            )

        def _json(self, status: HTTPStatus, value: Any) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._headers("application/json; charset=utf-8", len(body))
            self.end_headers()
            self.wfile.write(body)

        def _html(self, value: str) -> None:
            body = value.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self._headers("text/html; charset=utf-8", len(body))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _editable_objects(model: dict[str, Any]) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    model_path = "/semantic_model/0"
    datasets: Any = [item for item in model.get("datasets", []) if isinstance(item, dict)]
    dataset_names = [str(item.get("name")) for item in datasets]
    relationships = [item for item in model.get("relationships", []) if isinstance(item, dict)]
    fields_by_dataset = {
        str(item.get("name")): _physical_reference_options(item, relationships) for item in datasets
    }
    objects.append(
        _object(
            "ai_context",
            "model",
            str(model.get("name", "Model context")),
            "Model-level descriptions, synonyms, examples, and AI guidance",
            model_path,
            model,
            ["name", "description", "ai_context"],
            protected=True,
        )
    )
    if isinstance(datasets, list):
        for dataset_index, dataset in enumerate(datasets):
            if not isinstance(dataset, dict):
                continue
            dataset_path = f"{model_path}/datasets/{dataset_index}"
            dataset_name = str(dataset.get("name", f"Dataset {dataset_index + 1}"))
            objects.append(
                _object(
                    "datasets",
                    f"dataset-{dataset_index}",
                    dataset_name,
                    str(dataset.get("source", "No physical source")),
                    dataset_path,
                    dataset,
                    [
                        "name",
                        "description",
                        "source",
                        "primary_key",
                        "unique_keys",
                        "ai_context",
                    ],
                    options={
                        "primary_key": fields_by_dataset.get(dataset_name, []),
                        "unique_keys": fields_by_dataset.get(dataset_name, []),
                    },
                )
            )
            fields = dataset.get("fields", [])
            if isinstance(fields, list):
                for field_index, field in enumerate(fields):
                    if not isinstance(field, dict):
                        continue
                    field_path = f"{dataset_path}/fields/{field_index}"
                    objects.append(
                        _object(
                            "fields",
                            f"field-{dataset_index}-{field_index}",
                            str(field.get("name", f"Field {field_index + 1}")),
                            dataset_name,
                            field_path,
                            field,
                            [
                                "name",
                                "description",
                                "expression",
                                "dimension",
                                "ai_context",
                            ],
                        )
                    )
    metrics = model.get("metrics", [])
    if isinstance(metrics, list):
        for index, metric in enumerate(metrics):
            if isinstance(metric, dict):
                objects.append(
                    _object(
                        "metrics",
                        f"metric-{index}",
                        str(metric.get("name", f"Metric {index + 1}")),
                        "Model metric",
                        f"{model_path}/metrics/{index}",
                        metric,
                        ["name", "description", "expression", "ai_context"],
                    )
                )
    for index, relationship in enumerate(relationships):
        context = f"{relationship.get('from', '?')} to {relationship.get('to', '?')}"
        objects.append(
            _object(
                "relationships",
                f"relationship-{index}",
                str(relationship.get("name", f"Relationship {index + 1}")),
                context,
                f"{model_path}/relationships/{index}",
                relationship,
                [
                    "name",
                    "from",
                    "to",
                    "from_columns",
                    "to_columns",
                ],
                options={
                    "from": dataset_names,
                    "to": dataset_names,
                    "from_columns": fields_by_dataset.get(str(relationship.get("from", "")), []),
                    "to_columns": fields_by_dataset.get(str(relationship.get("to", "")), []),
                },
            )
        )
    return objects


def _physical_reference_options(
    dataset: dict[str, Any], relationships: list[dict[str, Any]]
) -> list[str]:
    """Return physical columns suitable for OSI key and relationship references."""

    dataset_name = str(dataset.get("name", ""))
    values: list[str] = []
    for field in dataset.get("fields", []):
        if not isinstance(field, dict):
            continue
        expression = field.get("expression")
        if not isinstance(expression, dict):
            continue
        for dialect in expression.get("dialects", []):
            if not isinstance(dialect, dict):
                continue
            value = dialect.get("expression")
            if not isinstance(value, str):
                continue
            match = re.fullmatch(r"[A-Za-z_]\w*\.([A-Za-z_]\w*)", value.strip())
            if match:
                values.append(match.group(1))
                break

    for key in dataset.get("primary_key", []):
        if isinstance(key, str):
            values.append(key)
    for unique_key in dataset.get("unique_keys", []):
        if isinstance(unique_key, list):
            values.extend(key for key in unique_key if isinstance(key, str))
    for relationship in relationships:
        if relationship.get("from") == dataset_name:
            values.extend(
                key for key in relationship.get("from_columns", []) if isinstance(key, str)
            )
        if relationship.get("to") == dataset_name:
            values.extend(key for key in relationship.get("to_columns", []) if isinstance(key, str))

    return list(dict.fromkeys(values))


def _object(
    section: str,
    identifier: str,
    name: str,
    context: str,
    path: str,
    value: dict[str, Any],
    properties: list[str],
    *,
    protected: bool = False,
    options: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    labels = {
        "ai_context": "AI context",
        "primary_key": "Primary key",
        "unique_keys": "Unique keys",
        "from_columns": "From columns",
        "to_columns": "To columns",
        "custom_extensions": "Source and review metadata",
    }
    result = []
    for key in properties:
        exists = key in value
        current = value.get(key, "" if key in {"name", "description", "source"} else None)
        kind = "text"
        if key == "ai_context":
            kind = "ai_context"
        elif key == "expression":
            kind = "expression"
        elif key == "dimension":
            kind = "dimension"
        elif key in {"primary_key", "from_columns", "to_columns"}:
            kind = "multi_select" if options and key in options else "string_list"
        elif key == "unique_keys":
            kind = "key_selects" if options and key in options else "key_lists"
        elif options and key in options:
            kind = "select"
        result.append(
            {
                "label": labels.get(key, key.replace("_", " ").title()),
                "path": f"{path}/{_escape_pointer(key)}",
                "value": current,
                "exists": exists,
                "kind": kind,
                "options": (options or {}).get(key, []),
                "help": _property_help(key),
            }
        )
    return {
        "section": section,
        "id": identifier,
        "name": name,
        "context": context,
        "path": path,
        "properties": result,
        "protected": protected,
        "translation": _translation_info(value, path),
    }


def _translation_info(value: dict[str, Any], path: str) -> dict[str, Any] | None:
    extensions = value.get("custom_extensions", [])
    if not isinstance(extensions, list):
        return None
    for index, extension in enumerate(extensions):
        if not isinstance(extension, dict) or not isinstance(extension.get("data"), str):
            continue
        try:
            data = json.loads(extension["data"])
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or data.get("kind") not in {
            "source_metadata",
            "unsupported_review",
        }:
            continue
        status = str(data.get("translation_status", "exact"))
        if status in {"exact", "reviewed-unsupported"}:
            return None
        accepted_data = {**data, "translation_status": "exact"}
        unsupported_data = {**data, "translation_status": "reviewed-unsupported"}
        requested_data = {
            **data,
            "review_request": "Additional business or technical evidence is required.",
        }
        return {
            "status": status,
            "source_expression": data.get("source_expression"),
            "can_accept": data.get("kind") == "source_metadata",
            "path": f"{path}/custom_extensions/{index}",
            "accepted_value": {
                **extension,
                "data": json.dumps(accepted_data, sort_keys=True),
            },
            "unsupported_value": {
                **extension,
                "data": json.dumps(unsupported_data, sort_keys=True),
            },
            "requested_value": {
                **extension,
                "data": json.dumps(requested_data, sort_keys=True),
            },
        }
    return None


def _property_help(key: str) -> str:
    return {
        "name": "Stable semantic name used by analysts and downstream references.",
        "description": "Plain-language business meaning, scope, and exclusions.",
        "source": "Qualified physical source or source expression.",
        "primary_key": "Select the physical source columns that form the primary key.",
        "unique_keys": "Select physical source columns for each alternate unique key.",
        "expression": "OSI expression object, including dialect-specific SQL when applicable.",
        "dimension": "OSI dimension metadata such as time or categorical behavior.",
        "ai_context": "Structured synonyms, examples, instructions, and other AI context.",
        "from": "Source dataset semantic name.",
        "to": "Target dataset semantic name.",
        "from_columns": "Select physical foreign-key columns from the many-side dataset.",
        "to_columns": "Select physical primary/unique-key columns from the one-side dataset.",
        "custom_extensions": (
            "Source and review metadata. Preserve unrelated entries; change translation status "
            "only when the supplied evidence fully resolves the source issue."
        ),
    }.get(key, "Review this semantic value against source evidence.")


def _coordinate_renames(
    document: dict[str, Any], operations: list[Any], raw_sha: str
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    explicit_paths = {
        str(item.get("path")) for item in operations if isinstance(item, dict) and item.get("path")
    }
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        normalized = copy.deepcopy(operation)
        intent = normalized.pop("intent", None)
        normalized["base_model_sha256"] = raw_sha
        result.append(normalized)
        if intent != "rename" or normalized.get("op") != "replace":
            continue
        path = str(normalized["path"])
        match = re.fullmatch(r"/semantic_model/0/datasets/(\d+)/name", path)
        if match:
            dataset_index = int(match.group(1))
            model = document["semantic_model"][0]
            old_name = str(model["datasets"][dataset_index]["name"])
            new_name = str(normalized["value"])
            _reject_ambiguous_expression_rewrite(document, old_name, path, explicit_paths)
            for index, relationship in enumerate(model.get("relationships", [])):
                for side in ("from", "to"):
                    if relationship.get(side) == old_name:
                        ref_path = f"/semantic_model/0/relationships/{index}/{side}"
                        if ref_path not in explicit_paths:
                            result.append(_derived_operation(normalized, ref_path, new_name))
            continue
        match = re.fullmatch(r"/semantic_model/0/datasets/(\d+)/fields/(\d+)/name", path)
        if match:
            # Field names are semantic identifiers. OSI keys and relationship columns are
            # physical source-column identifiers, so a semantic rename must not rewrite them.
            continue
    return result


def _derived_operation(source: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    return {
        "base_model_sha256": source["base_model_sha256"],
        "op": "replace",
        "path": path,
        "value": value,
        "rationale": f"Coordinated reference update: {source['rationale']}",
        "evidence": copy.deepcopy(source["evidence"]),
        "confidence": source["confidence"],
        "assumptions": copy.deepcopy(source["assumptions"]),
    }


def _reject_ambiguous_expression_rewrite(
    document: dict[str, Any],
    old_name: str,
    rename_path: str,
    explicit_paths: set[str],
) -> None:
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(old_name)}(?![A-Za-z0-9_])", re.IGNORECASE)

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}/{_escape_pointer(str(key))}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}/{index}")
        elif isinstance(value, str) and "/expression" in path and pattern.search(value):
            if not path.startswith(rename_path.rsplit("/name", 1)[0] + "/expression"):
                expression_path = path.split("/dialects/", 1)[0]
                if expression_path in explicit_paths or path in explicit_paths:
                    return
                raise ContractError(
                    f"rename is ambiguous because expression {path} references {old_name!r}; "
                    "add an explicit reviewed expression correction"
                )

    walk(document, "")


def _latest_decisions(paths: ReviewPaths) -> dict[str, Any]:
    for path in (paths.draft, paths.decisions):
        if path.is_file():
            try:
                return load_decisions(path, paths.raw)
            except ContractError:
                continue
    return default_decisions(paths.raw)


def _restricted_generated_path(value: str | Path) -> Path:
    path = Path(value).resolve()
    if path != GENERATED_ROOT and GENERATED_ROOT not in path.parents:
        raise ContractError("review artifacts must remain under semantic/generated")
    return path


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")
