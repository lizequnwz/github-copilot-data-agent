# Audited review patch (advanced)

The interactive workspace normally creates this file from reviewed decisions. Edit it manually
only for audit, debugging, or automation that cannot use `--review-ui` or `--review-decisions`.

The agent must express every semantic change as a JSON operation against the deterministic raw
model. The raw SHA-256 comes from `osi.raw_model_sha256` in the conversion manifest.

```json
{
  "patch_version": "1.0",
  "base_model_sha256": "RAW_MODEL_SHA256",
  "operations": [
    {
      "base_model_sha256": "RAW_MODEL_SHA256",
      "op": "add",
      "path": "/semantic_model/0/ai_context",
      "value": {
        "instructions": "Use this model for country-level development indicators.",
        "synonyms": ["world indicators"],
        "examples": ["Compare GDP and population by country and year."]
      },
      "rationale": "Describe the source-backed model scope for analytical use.",
      "evidence": [
        {
          "type": "source_metadata",
          "reference": "Tableau datasource name, folders, fields, and Year/Country dimensions"
        }
      ],
      "confidence": "high",
      "assumptions": []
    }
  ]
}
```

## Rules

- `op` is `add`, `replace`, or `remove`; `path` is an RFC 6901 JSON Pointer.
- Every operation repeats the top-level `base_model_sha256`, and requires non-empty `rationale`
  and `evidence`, `confidence` of `high`, `medium`, or `low`, and an `assumptions` array.
- Use evidence types `source_metadata`, `snowflake_metadata`, `user`, `official_spec`, or
  `inference`. Logic changes need high-confidence direct evidence for automatic promotion.
- Assumptions and low-confidence changes are allowed in a reviewed artifact but prevent clean
  automatic promotion.
- `/version` and the model-level `conversion_provenance` extension are protected. A separate
  `unsupported_review` extension may receive an audited `reviewed-unsupported` disposition.
- Update a source metadata extension's serialized `translation_status` when review evidence fully
  resolves an earlier `equivalent-with-assumptions` or `requires-human-review` state.
