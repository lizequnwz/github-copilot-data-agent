from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from data_agent.ossie import (
    EXPECTED_OSSIE_COMMIT,
    EXPECTED_SCHEMA_SHA256,
    SCHEMA,
    schema_sha256,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []
    required = [
        "AGENTS.md",
        ".gitmodules",
        ".github/copilot-instructions.md",
        ".github/agents/data-analytics.agent.md",
        ".github/skills/ask-data/SKILL.md",
        ".github/skills/ask-data/references/notebook.md",
        ".github/skills/ask-data/references/validation.md",
        ".github/skills/ask-data/references/reporting.md",
        ".github/skills/semantic-setup/SKILL.md",
        ".github/skills/semantic-setup/agents/openai.yaml",
        ".github/workflows/ci.yml",
        "snowflake_config.example.yaml",
        "semantic/models/demo_sales.yaml",
        "semantic/tests/demo_sales.yaml",
        "ossie-main/core-spec/osi-schema.json",
        "ossie-main/validation/validate.py",
        "ossie-main/LICENSE",
        "docs/ARCHITECTURE.md",
        "docs/ASK_DATA.md",
        "docs/SEMANTIC_SETUP.md",
        "examples/ask-data/exploration.json",
        "examples/ask-data/advanced-plan.json",
        "examples/ask-data/coverage-gap.json",
        "examples/ask-data/report.json",
        "examples/semantic-setup/test-model.json",
        "examples/semantic-setup/validate-model.json",
        "data_agent/ask/service.py",
        "data_agent/ask/compiler.py",
        "data_agent/ask/coverage.py",
        "data_agent/ask/workspace.py",
        "data_agent/ask/report.py",
        "data_agent/setup/conversion.py",
        "data_agent/setup/review.py",
        "data_agent/setup/review_workspace.py",
        "data_agent/diagnostics.py",
    ]
    for item in required:
        if not (ROOT / item).is_file():
            errors.append(f"missing required file: {item}")

    agent_paths = list((ROOT / ".github/agents").glob("*.agent.md"))
    for path in agent_paths:
        frontmatter = _frontmatter(path, errors)
        if not frontmatter.get("name") or not frontmatter.get("description"):
            errors.append(f"{path.relative_to(ROOT)}: name and description are required")

    skill_names: set[str] = set()
    for path in (ROOT / ".github/skills").glob("*/SKILL.md"):
        frontmatter = _frontmatter(path, errors)
        name = frontmatter.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", name):
            errors.append(f"{path.relative_to(ROOT)}: invalid skill name")
            continue
        if name in skill_names:
            errors.append(f"duplicate skill name: {name}")
        skill_names.add(name)
        if not frontmatter.get("description"):
            errors.append(f"{path.relative_to(ROOT)}: description is required")

    expected_skills = {"ask-data", "semantic-setup"}
    errors.extend(f"missing skill: {name}" for name in sorted(expected_skills - skill_names))

    try:
        json.loads(SCHEMA.read_text())
        for path in (ROOT / "examples").rglob("*.json"):
            json.loads(path.read_text())
        yaml.safe_load((ROOT / "snowflake_config.example.yaml").read_text())
        yaml.safe_load((ROOT / "semantic/tests/demo_sales.yaml").read_text())
    except Exception as exc:
        errors.append(f"invalid JSON/YAML project artifact: {exc}")

    if SCHEMA.is_file() and schema_sha256() != EXPECTED_SCHEMA_SHA256:
        errors.append("Apache Ossie schema does not match the pinned reviewed hash")
    try:
        commit = subprocess.run(
            ["git", "-C", str(ROOT / "ossie-main"), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if commit != EXPECTED_OSSIE_COMMIT:
            errors.append(
                f"Apache Ossie submodule commit is {commit}; expected {EXPECTED_OSSIE_COMMIT}"
            )
    except (OSError, subprocess.CalledProcessError):
        errors.append("Apache Ossie submodule is not initialized")

    try:
        official = subprocess.run(
            [
                sys.executable,
                str(ROOT / "ossie-main/validation/validate.py"),
                str(ROOT / "semantic/models/demo_sales.yaml"),
            ],
            capture_output=True,
            text=True,
        )
        if official.returncode != 0:
            detail = (official.stdout or official.stderr).strip().splitlines()
            errors.append(
                "official Ossie validation failed for demo_sales.yaml"
                + (f": {detail[-1]}" if detail else "")
            )
    except OSError as exc:
        errors.append(f"could not run official Ossie validation: {exc}")

    legacy_term = "enter" + "prise"
    for path in ROOT.rglob("*"):
        if (
            not path.is_file()
            or ".git" in path.parts
            or ".venv" in path.parts
            or "ossie-main" in path.parts
            or path.name == "uv.lock"
            or path.suffix.lower() not in {".md", ".py", ".yaml", ".yml", ".toml", ".json"}
        ):
            continue
        if re.search(rf"\b{legacy_term}\w*\b", path.read_text(encoding="utf-8"), re.IGNORECASE):
            errors.append(f"legacy positioning remains: {path.relative_to(ROOT)}")

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
