from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import json
import yaml
from jsonschema import Draft202012Validator

from data_agent.semantic.ossie import SCHEMA, official_validation_errors


class SemanticError(ValueError):
    pass


def load_document(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if source.stat().st_size > 5_000_000:
        raise SemanticError("semantic document exceeds 5000000 bytes")
    text = source.read_text(encoding="utf-8")
    try:
        value = json.loads(text) if source.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SemanticError(f"invalid semantic document: {exc}") from exc
    if not isinstance(value, dict):
        raise SemanticError("semantic document must be an object")
    return value


def validate_document(document: dict[str, Any], schema_path: str | Path = SCHEMA) -> list[str]:
    path = Path(schema_path).resolve()
    if path == SCHEMA.resolve():
        return official_validation_errors(document)
    schema = json.loads(path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda e: list(e.path))
    return [
        f"{'/'.join(str(p) for p in error.path) or '<root>'}: {error.message}" for error in errors
    ]


def iter_models(document: dict[str, Any]) -> Iterable[dict[str, Any]]:
    models = document.get("semantic_model", [])
    if isinstance(models, list):
        yield from (model for model in models if isinstance(model, dict))


def search_documents(paths: Iterable[Path], query: str) -> list[dict[str, Any]]:
    terms = [term.casefold() for term in query.split() if term.strip()]
    results: list[dict[str, Any]] = []
    for path in paths:
        try:
            document = load_document(path)
        except (OSError, SemanticError):
            continue
        for model in iter_models(document):
            for kind, values in (
                ("metric", model.get("metrics", [])),
                ("dataset", model.get("datasets", [])),
            ):
                for item in values if isinstance(values, list) else []:
                    if not isinstance(item, dict):
                        continue
                    haystack = json.dumps(item, sort_keys=True).casefold()
                    score = sum(term in haystack for term in terms)
                    if score:
                        results.append(
                            {
                                "path": str(path),
                                "model": model.get("name"),
                                "kind": kind,
                                "name": item.get("name"),
                                "description": item.get("description"),
                                "score": score / max(len(terms), 1),
                            }
                        )
    return sorted(results, key=lambda value: (-value["score"], value["name"] or ""))
