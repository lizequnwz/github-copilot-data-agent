# Semantic models

This folder has three responsibilities:

- `schemas/`: the vendored Apache Ossie `0.2.0.dev0` JSON Schema used offline.
- `candidates/`: generated `<name>.osi.yaml` and `<name>.conversion.json` pairs.
- `certified/`: human-reviewed Ossie models searched by default for analysis.

Run `uv run python scripts/convert_semantic.py SOURCE` to create a candidate pair. Candidates can be regenerated and are not trusted analytical definitions. Certification consists of resolving manifest issues, reviewing source expressions and physical mappings, validating keys and relationships, and comparing representative metrics with the source system before copying only the reviewed `.osi.yaml` into `certified/`.

See [the conversion workflow](../docs/SEMANTIC_CONVERSION.md).
