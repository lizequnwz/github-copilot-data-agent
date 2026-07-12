from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml

from data_agent.io import ContractError, envelope, require_string

_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


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
            source_field = match.group(2)
            field = (field_lookup or {}).get(
                source_field.casefold(), f"{dataset_name}.{_slug(source_field, 'field')}"
            )
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


def _local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _descendants(element: ET.Element, name: str) -> list[ET.Element]:
    return [item for item in element.iter() if _local_tag(item) == name]


def _first_descendant(element: ET.Element, name: str) -> ET.Element | None:
    return next(iter(_descendants(element, name)), None)


def _tableau_identifier(value: str | None) -> str:
    raw = str(value or "").strip()
    parts = re.findall(r"\[([^\]]+)\]", raw)
    if parts:
        return str(parts[-1])
    return raw.strip("[]'\"")


def _tableau_source(relation: ET.Element | None) -> str | None:
    if relation is None:
        return None
    table = relation.get("table")
    if not table:
        return None
    parts = re.findall(r"\[([^\]]+)\]", table)
    return ".".join(parts) if parts else table.strip("[]")


def _field_map(request: dict[str, Any]) -> dict[str, str]:
    value = request.get("field_map", {})
    if not isinstance(value, dict):
        raise ContractError("field_map must be an object mapping Tableau fields to SQL column names")
    result: dict[str, str] = {}
    for key, mapped in value.items():
        if isinstance(mapped, str):
            result[str(key).casefold()] = _tableau_sql_identifier(mapped)
            continue
        if not isinstance(mapped, dict):
            raise ContractError("field_map values must be strings or datasource-to-field objects")
        for field, column in mapped.items():
            if not isinstance(column, str):
                raise ContractError("nested field_map values must be SQL column-name strings")
            result[f"{key}.{field}".casefold()] = _tableau_sql_identifier(column)
    return result


def _tableau_sql_identifier(value: str) -> str:
    normalized = value.strip()
    if not _SQL_IDENTIFIER.fullmatch(normalized):
        raise ContractError(
            "field_map values must be unquoted SQL identifiers; expose quoted or spaced source "
            "columns through a view with normalized aliases"
        )
    return normalized


def _sibling_with_suffix(source: Path, suffix: str) -> Path | None:
    expected = f"{source.stem}{suffix}".casefold()
    for candidate in source.parent.iterdir():
        if candidate.is_file() and candidate.name.casefold() == expected:
            return candidate
    return None


def _resolve_tableau_descriptor(
    source: Path, descriptor_path: str | None = None
) -> tuple[Path, list[Path], str]:
    suffix = source.suffix.casefold()
    if suffix in {".twb", ".tds"} and source.is_file():
        sources = [source]
        if suffix == ".tds":
            sibling_extract = _sibling_with_suffix(source, ".tde")
            if sibling_extract is not None:
                sources.append(sibling_extract)
        return source, sources, suffix.removeprefix(".")
    if suffix == ".tde" and source.is_file():
        descriptor = (
            Path(descriptor_path).resolve() if descriptor_path else _sibling_with_suffix(source, ".tds")
        )
        if descriptor is None or descriptor.suffix.casefold() != ".tds" or not descriptor.is_file():
            raise ContractError(
                "a .tde extract is binary; provide a same-named .tds datasource descriptor, "
                "a valid descriptor_path, or export the datasource as .tds/.twb"
            )
        return descriptor, [descriptor, source], "tde-with-tds"
    raise ContractError("source_path must be a Tableau .twb, .tds, or .tde with a sibling .tds")


def _read_tableau_xml(path: Path) -> str:
    payload = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ContractError("Tableau XML must be UTF-8 or UTF-16")


def _tableau_datasources(root: ET.Element) -> list[ET.Element]:
    if _local_tag(root) == "datasource":
        return [root]
    return _descendants(root, "datasource")


def _tableau_physical_source(
    datasource: ET.Element,
    source_name: str,
    dataset_name: str,
    mapping: dict[str, str],
) -> str | None:
    relation = next(
        (item for item in _descendants(datasource, "relation") if item.get("table")), None
    )
    connection = _first_descendant(datasource, "connection")
    relation_source = _tableau_source(relation)
    lookup_keys = [source_name, dataset_name]
    if relation is not None:
        lookup_keys.append(str(relation.get("name") or ""))
    if relation_source:
        lookup_keys.append(relation_source)
    for key in lookup_keys:
        if key and key.casefold() in mapping:
            candidate = mapping[key.casefold()]
            return None if "REPLACE_WITH" in candidate.upper() else candidate
    connection_class = str(connection.get("class") if connection is not None else "").casefold()
    database_name = str(connection.get("dbname") if connection is not None else "").casefold()
    if connection_class == "dataengine" or database_name.endswith(".tde"):
        return None
    return relation_source


def _tableau_column_records(datasource: ET.Element) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for column in _descendants(datasource, "column"):
        raw_name = _tableau_identifier(column.get("caption") or column.get("name"))
        if not raw_name:
            continue
        calculation = _first_descendant(column, "calculation")
        records[raw_name.casefold()] = {
            "name": raw_name,
            "tableau_name": column.get("name") or raw_name,
            "data_type": column.get("datatype"),
            "role": str(column.get("role") or "").casefold(),
            "aggregation": column.get("aggregation"),
            "formula": calculation.get("formula") if calculation is not None else None,
            "source": "column",
        }
    for metadata in _descendants(datasource, "metadata-record"):
        if metadata.get("class") != "column":
            continue
        values = {
            _local_tag(child): (child.text or "").strip() for child in list(metadata)
        }
        raw_name = _tableau_identifier(values.get("local-name") or values.get("remote-name"))
        if not raw_name:
            continue
        existing = records.setdefault(
            raw_name.casefold(),
            {
                "name": raw_name,
                "tableau_name": values.get("local-name") or raw_name,
                "data_type": values.get("local-type"),
                "role": "",
                "aggregation": values.get("aggregation"),
                "formula": None,
                "source": "metadata-record",
            },
        )
        if not existing.get("data_type"):
            existing["data_type"] = values.get("local-type")
        if not existing.get("aggregation"):
            existing["aggregation"] = values.get("aggregation")
        if not existing.get("tableau_name"):
            existing["tableau_name"] = values.get("local-name") or raw_name
    return list(records.values())


def _tableau_aggregation_metric(
    aggregation: str | None, field_expression: str
) -> tuple[str | None, str | None]:
    normalized = str(aggregation or "").casefold()
    functions = {
        "sum": ("SUM", "sum"),
        "avg": ("AVG", "average"),
        "average": ("AVG", "average"),
        "min": ("MIN", "minimum"),
        "max": ("MAX", "maximum"),
        "count": ("COUNT", "count"),
        "countd": ("COUNT(DISTINCT", "distinct_count"),
    }
    function = functions.get(normalized)
    if function is None:
        return None, None
    if function[0] == "COUNT(DISTINCT":
        return f"COUNT(DISTINCT {field_expression})", function[1]
    return f"{function[0]}({field_expression})", function[1]


def _is_complex_tableau_formula(formula: str) -> bool:
    upper = formula.upper()
    return "{" in formula or any(
        token in upper
        for token in (
            "LOOKUP(",
            "WINDOW_",
            "RUNNING_",
            "PREVIOUS_VALUE(",
            "TOTAL(",
            "RANK(",
            "INDEX(",
            "SIZE(",
        )
    )


def extract_tableau_ir(request: dict[str, Any]) -> dict[str, Any]:
    input_source = Path(require_string(request, "source_path")).resolve()
    descriptor_value = request.get("descriptor_path")
    if descriptor_value is not None and not isinstance(descriptor_value, str):
        raise ContractError("descriptor_path must be a string path to a Tableau .tds file")
    descriptor, source_files, source_format = _resolve_tableau_descriptor(
        input_source, descriptor_value
    )
    text = _read_tableau_xml(descriptor)
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ContractError("DTD and entity declarations are blocked")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ContractError(f"invalid Tableau XML: {exc}") from exc
    mapping = _source_map(request)
    field_mapping = _field_map(request)
    datasets: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    unsupported: list[dict[str, str]] = []

    datasources = _tableau_datasources(root)
    if not datasources:
        raise ContractError("Tableau source contains no datasource element")
    for datasource in datasources:
        source_name = (
            datasource.get("caption")
            or datasource.get("formatted-name")
            or datasource.get("name")
            or descriptor.stem
        )
        dataset_name = _slug(source_name, "datasource")
        physical_source = _tableau_physical_source(
            datasource, source_name, dataset_name, mapping
        )
        fields: list[dict[str, Any]] = []
        field_lookup: dict[str, str] = {}
        source_columns = _tableau_column_records(datasource)
        for record in source_columns:
            raw_name = str(record["name"])
            field_name = _slug(raw_name, "field")
            mapping_keys = [
                f"{source_name}.{raw_name}".casefold(),
                f"{dataset_name}.{raw_name}".casefold(),
                raw_name.casefold(),
            ]
            physical_column = next(
                (field_mapping[key] for key in mapping_keys if key in field_mapping), field_name
            )
            expression = f"{dataset_name}.{physical_column}"
            field_lookup[raw_name.casefold()] = expression
            formula = record.get("formula")
            translation_status = "exact" if formula is None else "requires-human-review"
            if formula and _is_complex_tableau_formula(str(formula)):
                unsupported.append(
                    {"field": raw_name, "construct": "LOD_or_table_calculation"}
                )
            fields.append(
                {
                    "id": f"{source_name}.{raw_name}",
                    "name": raw_name,
                    "source_expression": {
                        "language": "TABLEAU",
                        "value": formula or record.get("tableau_name"),
                    },
                    "normalized_expression": expression,
                    "data_type": record.get("data_type"),
                    "is_dimension": record.get("role") == "dimension",
                    "is_time": str(record.get("data_type")).casefold()
                    in {"date", "datetime", "timestamp"},
                    "translation_status": translation_status,
                }
            )

        for record in source_columns:
            if record.get("role") != "measure":
                continue
            raw_name = str(record["name"])
            field_expression = field_lookup[raw_name.casefold()]
            formula = str(record.get("formula") or "").strip()
            metric_expression: str | None
            metric_suffix: str | None
            metric_status: str
            if formula == "1":
                metric_expression, metric_suffix, metric_status = "COUNT(1)", "count", "exact"
            elif formula:
                metric_expression, metric_status = _translate_aggregate(
                    formula,
                    dataset_name,
                    language="TABLEAU",
                    field_lookup=field_lookup,
                )
                metric_suffix = "calculated"
                if _is_complex_tableau_formula(formula):
                    metric_status = "requires-human-review"
            else:
                metric_expression, metric_suffix = _tableau_aggregation_metric(
                    record.get("aggregation"), field_expression
                )
                metric_status = (
                    "equivalent-with-assumptions"
                    if metric_expression is not None
                    else "requires-human-review"
                )
            if metric_expression is None:
                unsupported.append(
                    {"field": raw_name, "construct": "unmapped_measure_aggregation_or_formula"}
                )
            metrics.append(
                {
                    "id": f"{source_name}.{raw_name}",
                    "name": (
                        "number_of_records"
                        if formula == "1"
                        else f"{metric_suffix or 'measure'}_{_slug(raw_name, 'measure')}"
                    ),
                    "dataset": source_name,
                    "description": (
                        f"Tableau {'calculation' if formula else 'default aggregation'} "
                        f"for {raw_name}."
                    ),
                    "source_expression": {
                        "language": "TABLEAU",
                        "value": formula or record.get("aggregation"),
                    },
                    "source_format": "tableau-tds-metadata",
                    "normalized_expression": metric_expression,
                    "translation_status": metric_status,
                }
            )

        datasets.append(
            {
                "id": source_name,
                "name": source_name,
                "physical_source": physical_source,
                "fields": fields,
                "source_file": descriptor.name,
                "translation_status": "exact" if physical_source else "requires-human-review",
            }
        )

    return {
        "ir_version": "1.0",
        "source_type": "tableau",
        "source_format": source_format,
        "source_artifact": request.get("source_artifact", input_source.stem),
        "source_files": [str(path) for path in source_files],
        "snapshot_sha256": _hash_files(source_files),
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
        warnings=[
            "Tableau .tde extracts require a .tds descriptor for semantic metadata.",
            "Default Tableau aggregations are emitted as usable metrics with assumptions for review.",
        ],
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
