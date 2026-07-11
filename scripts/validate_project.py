from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []
    required = [
        "AGENTS.md",
        ".github/copilot-instructions.md",
        ".github/agents/data-analytics.agent.md",
        "snowflake_config.yaml",
        "semantic/schemas/osi-0.2.0.dev0.schema.json",
        "semantic/schemas/README.md",
        "docs/OPERATING_GUIDE.md",
        "docs/SEMANTIC_CONVERSION.md",
        "docs/DATA_AGENT.md",
        "docs/TOOLS.md",
        "scripts/convert_semantic.py",
        "scripts/render_report_demo.py",
        "tests/test_semantic_conversion.py",
        "tests/test_reporting.py",
    ]
    for item in required:
        if not (ROOT / item).is_file():
            errors.append(f"missing required file: {item}")
    agent_paths = list((ROOT / ".github/agents").glob("*.agent.md"))
    if [path.name for path in agent_paths] != ["data-analytics.agent.md"]:
        errors.append("POC must contain only .github/agents/data-analytics.agent.md")
    for path in agent_paths:
        frontmatter = _frontmatter(path, errors)
        if not frontmatter.get("description"):
            errors.append(f"{path.relative_to(ROOT)}: description is required")
        if "tools" in frontmatter:
            errors.append(f"{path.relative_to(ROOT)}: omit tools to use Copilot defaults")
    skill_names: set[str] = set()
    for path in (ROOT / ".github/skills").glob("*/SKILL.md"):
        frontmatter = _frontmatter(path, errors)
        name = frontmatter.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", name):
            errors.append(f"{path.relative_to(ROOT)}: invalid skill name")
        elif name in skill_names:
            errors.append(f"duplicate skill name: {name}")
        skill_names.add(str(name))
        if not frontmatter.get("description"):
            errors.append(f"{path.relative_to(ROOT)}: description is required")
    expected_skills = {
        "analytics-report-generation",
        "osi-semantic-builder",
        "snowflake-environment-setup",
        "snowflake-readonly-query",
        "result-validation",
    }
    errors.extend(f"missing skill: {name}" for name in sorted(expected_skills - skill_names))
    errors.extend(f"unexpected skill: {name}" for name in sorted(skill_names - expected_skills))
    for removed in [".env.example", "knowledge", "evals"]:
        if (ROOT / removed).exists():
            errors.append(f"deferred or conflicting artifact still exists: {removed}")
    config_source = (ROOT / "data_agent/config.py").read_text(encoding="utf-8")
    if "from_env" in config_source or "SNOWFLAKE_ACCOUNT" in config_source:
        errors.append("environment-variable Snowflake configuration is still enabled")
    cli_source = (ROOT / "data_agent/cli.py").read_text(encoding="utf-8")
    tool_docs = (ROOT / "docs/TOOLS.md").read_text(encoding="utf-8")
    expected_commands = {
        "cancel-query",
        "config-check",
        "connection-check",
        "describe-object",
        "execute-readonly",
        "ir-to-osi",
        "memory-propose",
        "osi-compile",
        "osi-search",
        "osi-validate",
        "powerbi-extract",
        "profile-table",
        "render-chart",
        "render-report",
        "sample-values",
        "search-objects",
        "semantic-diff",
        "semantic-convert",
        "tableau-extract",
        "validate-result",
        "validate-sql",
    }
    for command in sorted(expected_commands):
        if f'"{command}"' not in cli_source:
            errors.append(f"CLI command missing: {command}")
        if f"`{command}`" not in tool_docs:
            errors.append(f"tool command undocumented: {command}")
    try:
        json.loads((ROOT / "semantic/schemas/osi-0.2.0.dev0.schema.json").read_text())
    except Exception as exc:
        errors.append(f"invalid vendored schema: {exc}")
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors))
        return 1
    print(f"Project structure valid: {len(skill_names)} skills and {len(agent_paths)} agent")
    return 0


def _frontmatter(path: Path, errors: list[str]) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        errors.append(f"{path.relative_to(ROOT)}: missing YAML frontmatter")
        return {}
    raw = text.split("---\n", 2)[1]
    try:
        value = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        errors.append(f"{path.relative_to(ROOT)}: invalid YAML frontmatter: {exc}")
        return {}
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
