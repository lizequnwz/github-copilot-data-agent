from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml

from data_agent.io import ContractError, envelope, require_string


def _hash_files(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(str(path.name).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _slug(value: Any, fallback: str = "item") -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or fallback)).strip("_").lower()
    return normalized or fallback


def _unquote(value: str) -> str:
    value = value.strip().strip("'\"")
    return value.replace("''", "'")


def _source_map(request: dict[str, Any]) -> dict[str, str]:
    value = request.get("source_map", {})
    if not isinstance(value, dict):
        raise ContractError("source_map must be an object mapping source dataset names to tables")
    return {str(key).casefold(): str(source) for key, source in value.items()}


def _translate_aggregate(
    expression: str,
    dataset_name: str,
    *,
    language: str,
    field_lookup: dict[str, str] | None = None,
) -> tuple[str | None, str]:
    """Translate only simple aggregate expressions whose meaning is unambiguous."""

    cleaned = expression.strip()
    if language == "DAX":
        reference = r"(?:'([^']+)'|([A-Za-z_][\w ]*))\s*\[([^\]]+)\]"
        patterns = {
            "SUM": "SUM({field})",
            "AVERAGE": "AVG({field})",
            "MIN": "MIN({field})",
            "MAX": "MAX({field})",
            "COUNT": "COUNT({field})",
            "DISTINCTCOUNT": "COUNT(DISTINCT {field})",
        }
        match = re.fullmatch(rf"(?is)\s*({'|'.join(patterns)})\s*\(\s*{reference}\s*\)\s*", cleaned)
        if match:
            function = match.group(1).upper()
            source_table = match.group(2) or match.group(3) or dataset_name
            source_field = match.group(4)
            key = f"{source_table.casefold()}.{source_field.casefold()}"
            field = (field_lookup or {}).get(
                key, f"{_slug(source_table, dataset_name)}.{_slug(source_field, 'field')}"
            )
            return patterns[function].format(field=field), "exact"
    if language == "TABLEAU":
        match = re.fullmatch(
            r"(?is)\s*(SUM|AVG|AVERAGE|MIN|MAX|COUNT|COUNTD)\s*\(\s*\[([^\]]+)\]\s*\)\s*",
            cleaned,
        )
        if match:
            function = {"AVERAGE": "AVG", "COUNTD": "COUNT(DISTINCT"}.get(
                match.group(1).upper(), match.group(1).upper()
            )
            field = f"{dataset_name}.{_slug(match.group(2), 'field')}"
            if function == "COUNT(DISTINCT":
                return f"COUNT(DISTINCT {field})", "exact"
            return f"{function}({field})", "exact"
    return None, "requires-human-review"


def _tmdl_blocks(text: str, keyword: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        rf"(?ms)^\s*{keyword}\s+(.+?)(?:\s*=\s*[^\r\n]*)?\s*$\n(.*?)(?=^\s*(?:table|column|measure|partition|hierarchy|relationship|role|annotation)\s+|\Z)"
    )
    return [(_unquote(match.group(1).split("=")[0]), match.group(2)) for match in pattern.finditer(text)]


def extract_powerbi_ir(request: dict[str, Any]) -> dict[str, Any]:
    root = Path(require_string(request, "source_path")).resolve()
    if not root.is_dir():
        raise ContractError("source_path must be an unpacked TMDL/PBIP directory")
    files = list(root.rglob("*.tmdl"))
    if not files:
        raise ContractError("no .tmdl files found")
    mapping = _source_map(request)
    datasets_by_name: dict[str, dict[str, Any]] = {}
    metrics: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    unsupported: list[dict[str, str]] = []
    dax_field_lookup: dict[str, str] = {}
    physical_column_lookup: dict[str, str] = {}

    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for relationship_name, block in _tmdl_blocks(text, "relationship"):
            from_match = re.search(r"(?im)^\s*fromColumn:\s*([^\r\n]+)", block)
            to_match = re.search(r"(?im)^\s*toColumn:\s*([^\r\n]+)", block)
            if not from_match or not to_match:
                continue
            from_value, to_value = _unquote(from_match.group(1)), _unquote(to_match.group(1))
            if "." not in from_value or "." not in to_value:
                unsupported.append(
                    {
                        "source_file": str(path.relative_to(root)),
                        "construct": "relationship_without_qualified_columns",
                    }
                )
                continue
            from_table, from_column = from_value.rsplit(".", 1)
            to_table, to_column = to_value.rsplit(".", 1)
            relationships.append(
                {
                    "id": relationship_name,
                    "name": relationship_name,
                    "from_dataset": _unquote(from_table),
                    "to_dataset": _unquote(to_table),
                    "from_columns": [_unquote(from_column)],
                    "to_columns": [_unquote(to_column)],
                    "active": not bool(
                        re.search(r"(?im)^\s*isActive:\s*false\s*$", block)
                    ),
                    "translation_status": "exact",
                }
            )
        table_matches = list(re.finditer(r"(?m)^\s*table\s+([^\r\n]+)", text))
        if not table_matches and not re.search(r"(?m)^\s*(?:column|measure)\s+", text):
            continue
        default_table = _unquote(table_matches[0].group(1)) if table_matches else path.stem
        table_key = default_table.casefold()
        source_hint = re.search(
            r"(?im)^\s*annotation\s+(?:DataAgent\.)?Source\s*=\s*([^\r\n]+)", text
        )
        physical_source = mapping.get(table_key) or (
            _unquote(source_hint.group(1)) if source_hint else None
        )
        dataset = datasets_by_name.setdefault(
            default_table,
            {
                "id": default_table,
                "name": default_table,
                "physical_source": physical_source,
                "fields": [],
                "primary_key": [],
                "source_file": str(path.relative_to(root)),
                "translation_status": "exact" if physical_source else "requires-human-review",
            },
        )
        if physical_source:
            dataset["physical_source"] = physical_source

        for column_name, block in _tmdl_blocks(text, "column"):
            source_column = re.search(r"(?im)^\s*sourceColumn:\s*([^\r\n]+)", block)
            data_type = re.search(r"(?im)^\s*dataType:\s*([^\r\n]+)", block)
            description = re.search(r"(?im)^\s*description:\s*([^\r\n]+)", block)
            is_key = bool(re.search(r"(?im)^\s*isKey:\s*true\s*$", block))
            field_name = _slug(column_name, "field")
            physical_column = _unquote(source_column.group(1)) if source_column else column_name
            normalized_expression = (
                f"{_slug(default_table)}.{_slug(physical_column, field_name)}"
            )
            dax_field_lookup[f"{default_table.casefold()}.{column_name.casefold()}"] = (
                normalized_expression
            )
            physical_column_lookup[
                f"{default_table.casefold()}.{column_name.casefold()}"
            ] = _slug(physical_column, field_name)
            dataset["fields"].append(
                {
                    "id": f"{default_table}.{column_name}",
                    "name": column_name,
                    "source_expression": physical_column,
                    "normalized_expression": normalized_expression,
                    "data_type": _unquote(data_type.group(1)) if data_type else None,
                    "description": _unquote(description.group(1)) if description else None,
                    "is_dimension": True,
                    "is_time": bool(data_type and "date" in data_type.group(1).casefold()),
                    "translation_status": "exact",
                }
            )
            if is_key:
                dataset["primary_key"].append(_slug(physical_column, field_name))

        measure_pattern = re.compile(
            r"(?ms)^\s*measure\s+([^\r\n=]+?)\s*=\s*(.*?)"
            r"(?=^\s*(?:formatString|description|displayFolder|annotation):"
            r"|^\s*(?:column|measure|partition|hierarchy|relationship|role)\s+|\Z)"
        )
        for measure_match in measure_pattern.finditer(text):
            measure_name = _unquote(measure_match.group(1))
            dax = measure_match.group(2).strip()
            normalized, status = _translate_aggregate(
                dax,
                _slug(default_table),
                language="DAX",
                field_lookup=dax_field_lookup,
            )
            metrics.append(
                {
                    "id": f"{default_table}.{measure_name}",
                    "name": measure_name,
                    "dataset": default_table,
                    "source_expression": {"language": "DAX", "value": dax},
                    "normalized_expression": normalized,
                    "translation_status": status,
                }
            )

        for keyword in (
            "calculationGroup",
            "detailRowsDefinition",
            "rowLevelSecurity",
            "perspective",
        ):
            if keyword.casefold() in text.casefold():
                unsupported.append(
                    {"source_file": str(path.relative_to(root)), "construct": keyword}
                )

    for relationship in relationships:
        from_dataset = str(relationship["from_dataset"])
        to_dataset = str(relationship["to_dataset"])
        relationship["from_columns"] = [
            physical_column_lookup.get(
                f"{from_dataset.casefold()}.{str(column).casefold()}", _slug(column, "key")
            )
            for column in relationship["from_columns"]
        ]
        relationship["to_columns"] = [
            physical_column_lookup.get(
                f"{to_dataset.casefold()}.{str(column).casefold()}", _slug(column, "key")
            )
            for column in relationship["to_columns"]
        ]

    return {
        "ir_version": "1.0",
        "source_type": "powerbi",
        "source_artifact": request.get("source_artifact", root.name),
        "snapshot_sha256": _hash_files(files),
        "datasets": list(datasets_by_name.values()),
        "relationships": relationships,
        "metrics": metrics,
        "unsupported": unsupported,
    }


def extract_powerbi(request: dict[str, Any]) -> dict[str, Any]:
    ir = extract_powerbi_ir(request)
    warnings = [
        "Complex DAX, calculation groups, roles, perspectives, and M lineage remain review items."
    ]
    return envelope(
        request,
        "success",
        semantic_ir=ir,
        completeness="partial" if ir["unsupported"] else "best-effort",
        warnings=warnings,
    )


def _tableau_source(relation: ET.Element | None) -> str | None:
    if relation is None:
        return None
    table = relation.get("table")
    if not table:
        return None
    parts = re.findall(r"\[([^\]]+)\]", table)
    return ".".join(parts) if parts else table.strip("[]")


def extract_tableau_ir(request: dict[str, Any]) -> dict[str, Any]:
    source = Path(require_string(request, "source_path")).resolve()
    if source.suffix.lower() != ".twb" or not source.is_file():
        raise ContractError("source_path must be an unpacked .twb workbook")
    text = source.read_text(encoding="utf-8", errors="strict")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ContractError("DTD and entity declarations are blocked")
    root = ET.fromstring(text)
    mapping = _source_map(request)
    datasets: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    unsupported: list[dict[str, str]] = []

    for datasource in root.findall(".//datasource"):
        source_name = datasource.get("caption") or datasource.get("name") or "unnamed_datasource"
        dataset_name = _slug(source_name, "datasource")
        relation = datasource.find(".//relation[@table]")
        physical_source = mapping.get(source_name.casefold()) or mapping.get(dataset_name.casefold()) or _tableau_source(relation)
        fields = []
        for column in datasource.findall(".//column"):
            raw_name = (column.get("caption") or column.get("name") or "unnamed").strip("[]")
            physical_name = (column.get("name") or raw_name).strip("[]").split("].[", 1)[-1]
            calculation = column.find("calculation")
            formula = (calculation.get("formula") or "") if calculation is not None else ""
            role = (column.get("role") or "").casefold()
            data_type = column.get("datatype")
            is_metric = calculation is not None and role == "measure"
            if is_metric:
                normalized, status = _translate_aggregate(
                    formula, dataset_name, language="TABLEAU"
                )
                metrics.append(
                    {
                        "id": f"{source_name}.{raw_name}",
                        "name": raw_name,
                        "dataset": source_name,
                        "source_expression": {"language": "TABLEAU", "value": formula},
                        "normalized_expression": normalized,
                        "translation_status": status,
                    }
                )
            else:
                field_name = _slug(raw_name, "field")
                fields.append(
                    {
                        "id": f"{source_name}.{raw_name}",
                        "name": raw_name,
                        "source_expression": {
                            "language": "TABLEAU",
                            "value": formula or column.get("name"),
                        },
                        "normalized_expression": (
                            f"{dataset_name}.{_slug(physical_name, field_name)}"
                        ),
                        "data_type": data_type,
                        "is_dimension": role == "dimension" or calculation is None,
                        "is_time": str(data_type).casefold() in {"date", "datetime"},
                        "translation_status": "exact" if calculation is None else "requires-human-review",
                    }
                )
            if calculation is not None and (
                "{" in formula
                or "LOOKUP(" in formula.upper()
                or "WINDOW_" in formula.upper()
            ):
                unsupported.append({"field": raw_name, "construct": "LOD_or_table_calculation"})
        datasets.append(
            {
                "id": source_name,
                "name": source_name,
                "physical_source": physical_source,
                "fields": fields,
                "source_file": source.name,
                "translation_status": "exact" if physical_source else "requires-human-review",
            }
        )

    return {
        "ir_version": "1.0",
        "source_type": "tableau",
        "source_artifact": request.get("source_artifact", source.stem),
        "snapshot_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "datasets": datasets,
        "relationships": [],
        "metrics": metrics,
        "unsupported": unsupported,
    }


def extract_tableau(request: dict[str, Any]) -> dict[str, Any]:
    ir = extract_tableau_ir(request)
    return envelope(
        request,
        "success",
        semantic_ir=ir,
        completeness="partial" if ir["unsupported"] else "best-effort",
        warnings=["Workbook XML conversion preserves unsupported calculations for review."],
    )


def extract_generic_ir(request: dict[str, Any]) -> dict[str, Any]:
    source = Path(require_string(request, "source_path")).resolve()
    if not source.is_file() or source.suffix.lower() not in {".json", ".yaml", ".yml"}:
        raise ContractError("generic source must be a JSON or YAML file")
    try:
        raw = json.loads(source.read_text(encoding="utf-8")) if source.suffix.lower() == ".json" else yaml.safe_load(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ContractError(f"invalid generic semantic file: {exc}") from exc
    if not isinstance(raw, dict):
        raise ContractError("generic semantic file must contain an object")
    if raw.get("ir_version") and isinstance(raw.get("datasets"), list):
        return raw
    mapping = _source_map(request)
    source_datasets = raw.get("datasets", raw.get("tables", []))
    if not isinstance(source_datasets, list) or not source_datasets:
        raise ContractError("generic semantic file requires a non-empty datasets or tables array")
    datasets: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    for item in source_datasets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("id") or "dataset")
        dataset_name = _slug(name, "dataset")
        fields = []
        source_fields = item.get("fields", item.get("columns", []))
        if not isinstance(source_fields, list):
            source_fields = []
        for field in source_fields:
            if not isinstance(field, dict):
                continue
            field_name = str(field.get("name") or field.get("id") or "field")
            normalized_name = _slug(field_name, "field")
            fields.append(
                {
                    "id": field.get("id") or f"{name}.{field_name}",
                    "name": field_name,
                    "description": field.get("description"),
                    "data_type": field.get("data_type", field.get("type")),
                    "normalized_expression": str(field.get("expression") or f"{dataset_name}.{normalized_name}"),
                    "source_expression": field.get("source_expression", field.get("expression")),
                    "is_dimension": bool(field.get("dimension", True)),
                    "is_time": bool(field.get("is_time") or str(field.get("type", "")).casefold() in {"date", "datetime", "timestamp"}),
                    "translation_status": str(field.get("translation_status", "exact")),
                }
            )
        source_metrics = item.get("metrics", item.get("measures", []))
        if not isinstance(source_metrics, list):
            source_metrics = []
        for metric in source_metrics:
            if isinstance(metric, dict):
                metrics.append({**metric, "dataset": name})
        datasets.append(
            {
                "id": item.get("id") or name,
                "name": name,
                "description": item.get("description"),
                "physical_source": mapping.get(name.casefold()) or item.get("source") or item.get("physical_source"),
                "primary_key": item.get("primary_key", []),
                "unique_keys": item.get("unique_keys", []),
                "fields": fields,
                "translation_status": str(item.get("translation_status", "exact")),
            }
        )
    top_metrics = raw.get("metrics", raw.get("measures", []))
    if isinstance(top_metrics, list):
        metrics.extend(metric for metric in top_metrics if isinstance(metric, dict))
    normalized_metrics = []
    for metric in metrics:
        expression = metric.get("normalized_expression", metric.get("expression"))
        normalized_metrics.append(
            {
                **metric,
                "name": metric.get("name") or metric.get("id"),
                "normalized_expression": expression,
                "source_expression": metric.get("source_expression", expression),
                "translation_status": metric.get("translation_status", "exact" if expression else "requires-human-review"),
            }
        )
    return {
        "ir_version": "1.0",
        "source_type": "generic",
        "source_artifact": request.get("source_artifact", source.stem),
        "snapshot_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "description": raw.get("description"),
        "datasets": datasets,
        "relationships": raw.get("relationships", []),
        "metrics": normalized_metrics,
        "unsupported": [],
    }
