from __future__ import annotations

import http.client
import json
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from data_agent.io import ContractError
from data_agent.semantic.conversion import convert_semantic
from data_agent.semantic.models import load_document
from data_agent.semantic.review_workspace import (
    ReviewApplication,
    MAX_REQUEST_BYTES,
    _editable_objects,
    _handler_for,
    _translation_info,
    compile_decisions,
    default_decisions,
    render_review_html,
    review_paths,
    save_draft,
    validate_decisions,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/generic/sales.yaml"


class ReviewWorkspaceTests(unittest.TestCase):
    def _build(self, directory: str) -> tuple[dict[str, object], object]:
        built = convert_semantic(
            {
                "request_id": "workspace-test",
                "source_path": str(FIXTURE),
                "model_name": "workspace_sales",
                "output_dir": directory,
            }
        )
        return built, review_paths(built["raw_model_path"], built["manifest_path"])

    def test_decisions_require_current_hash_evidence_and_known_keys(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            _, paths = self._build(directory)
            decisions = default_decisions(paths.raw)
            decisions["unknown"] = True
            with self.assertRaisesRegex(ContractError, "unknown review decision keys"):
                validate_decisions(decisions, paths.raw)

            decisions = default_decisions(paths.raw)
            decisions["base_model_sha256"] = "0" * 64
            with self.assertRaisesRegex(ContractError, "stale"):
                validate_decisions(decisions, paths.raw)

            decisions = default_decisions(paths.raw)
            decisions["operations"] = [
                {
                    "op": "replace",
                    "path": "/version",
                    "value": "9.9",
                    "rationale": "Change the protected version.",
                    "evidence": [{"type": "official_spec", "reference": "test"}],
                    "confidence": "high",
                    "assumptions": [],
                }
            ]
            with self.assertRaisesRegex(ContractError, "Ossie version"):
                validate_decisions(decisions, paths.raw)

            decisions = default_decisions(paths.raw)
            decisions["operations"] = [
                {
                    "op": "replace",
                    "path": "/semantic_model/0/description",
                    "value": "Reviewed model.",
                    "rationale": "Clarify the model.",
                    "evidence": [{}],
                    "confidence": "high",
                    "assumptions": [],
                }
            ]
            with self.assertRaisesRegex(ContractError, "evidence 0 requires type"):
                validate_decisions(decisions, paths.raw)

    def test_field_rename_preserves_physical_key_references(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            _, paths = self._build(directory)
            decisions = default_decisions(paths.raw)
            decisions["operations"] = [
                {
                    "op": "replace",
                    "path": "/semantic_model/0/datasets/0/fields/0/name",
                    "value": "order_identifier",
                    "intent": "rename",
                    "rationale": "Use the approved business-facing field name.",
                    "evidence": [{"type": "user", "reference": "Data owner approval"}],
                    "confidence": "high",
                    "assumptions": [],
                }
            ]
            patch = compile_decisions(decisions, paths)
            paths_by_operation = {item["path"]: item for item in patch["operations"]}
            self.assertNotIn("/semantic_model/0/datasets/0/primary_key", paths_by_operation)
            self.assertNotIn("intent", patch["operations"][0])
            self.assertTrue(paths.decisions.is_file())
            self.assertTrue(paths.patch.is_file())

    def test_dataset_rename_requires_explicit_expression_correction(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            _, paths = self._build(directory)
            decisions = default_decisions(paths.raw)
            decisions["operations"] = [
                {
                    "op": "replace",
                    "path": "/semantic_model/0/datasets/0/name",
                    "value": "booked_orders",
                    "intent": "rename",
                    "rationale": "Use the approved dataset name.",
                    "evidence": [{"type": "user", "reference": "Data owner approval"}],
                    "confidence": "high",
                    "assumptions": [],
                }
            ]
            with self.assertRaisesRegex(ContractError, "expression .* references"):
                compile_decisions(decisions, paths)

    def test_apply_generates_audit_and_promotes_only_after_confirmation(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            _, paths = self._build(directory)
            decisions = default_decisions(paths.raw)
            app = ReviewApplication(
                paths,
                request_id="workspace",
                verify_snowflake=False,
                config_path="snowflake_config.yaml",
                configuration_confirmed=False,
                promote_if_clean=True,
            )
            with self.assertRaisesRegex(ContractError, "confirm the promotion destination"):
                app.apply({"decisions": decisions, "confirm_promote": False})
            promotion_root = Path(directory) / "promotion-root"
            with patch("data_agent.semantic.review.ROOT", promotion_root):
                applied = app.apply({"decisions": decisions, "confirm_promote": True})
            self.assertTrue(applied["result"]["clean"])
            self.assertTrue(applied["result"]["promoted"])
            self.assertTrue(paths.decisions.is_file())
            self.assertTrue(paths.patch.is_file())
            self.assertTrue(paths.html.is_file())

    def test_draft_and_static_workspace_are_accessible_and_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            built, paths = self._build(directory)
            raw_before = Path(str(built["raw_model_path"])).read_bytes()
            decisions = default_decisions(paths.raw)
            save_draft(decisions, paths)
            self.assertEqual(Path(str(built["raw_model_path"])).read_bytes(), raw_before)
            state = ReviewApplication(
                paths,
                request_id="workspace",
                verify_snowflake=False,
                config_path="snowflake_config.yaml",
                configuration_confirmed=False,
                promote_if_clean=False,
            ).state()
            document = render_review_html(state)
            for expected in (
                "Skip to review workspace",
                'aria-live="polite"',
                "prefers-reduced-motion",
                "prefers-color-scheme:dark",
                "Apply and validate",
                "Download decisions",
                "Review as",
                "Refresh impact",
                "object-level changes",
                "Accept translation",
                "Retain as reviewed unsupported",
                "Business",
                "Analyst",
            ):
                self.assertIn(expected, document)
            self.assertNotIn("https://", document)

    def test_embedded_workspace_javascript_parses(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is unavailable for static JavaScript validation")
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            _, paths = self._build(directory)
            state = ReviewApplication(
                paths,
                request_id="workspace-js",
                verify_snowflake=False,
                config_path="snowflake_config.yaml",
                configuration_confirmed=False,
                promote_if_clean=False,
            ).state()
            document = render_review_html(state)
            match = re.search(r"<script>(.*?)</script>", document, re.DOTALL)
            self.assertIsNotNone(match)
            assert match is not None
            checked = subprocess.run(
                [node, "--check", "-"],
                input=match.group(1),
                text=True,
                capture_output=True,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_translation_review_builds_audited_status_values(self) -> None:
        value = {
            "custom_extensions": [
                {
                    "vendor_name": "COMMON",
                    "data": json.dumps(
                        {
                            "kind": "source_metadata",
                            "source_expression": "AVG([Sales])",
                            "translation_status": "equivalent-with-assumptions",
                        }
                    ),
                }
            ]
        }
        translation = _translation_info(value, "/semantic_model/0/metrics/0")
        self.assertIsNotNone(translation)
        assert translation is not None
        self.assertEqual(translation["path"], "/semantic_model/0/metrics/0/custom_extensions/0")
        accepted = json.loads(translation["accepted_value"]["data"])
        self.assertEqual(accepted["translation_status"], "exact")
        unsupported = json.loads(translation["unsupported_value"]["data"])
        self.assertEqual(unsupported["translation_status"], "reviewed-unsupported")

    def test_keys_and_relationship_fields_use_guided_selectors(self) -> None:
        document = {
            "name": "sales",
            "datasets": [
                {
                    "name": "orders",
                    "source": "DB.SCHEMA.ORDERS",
                    "fields": [
                        {
                            "name": "customer_identifier",
                            "expression": {
                                "dialects": [
                                    {"dialect": "SNOWFLAKE", "expression": "orders.customer_id"}
                                ]
                            },
                        },
                        {
                            "name": "order_identifier",
                            "expression": {
                                "dialects": [
                                    {"dialect": "SNOWFLAKE", "expression": "orders.order_id"}
                                ]
                            },
                        },
                    ],
                    "primary_key": ["order_id"],
                    "unique_keys": [["customer_id", "order_id"]],
                },
                {
                    "name": "customers",
                    "source": "DB.SCHEMA.CUSTOMERS",
                    "fields": [
                        {
                            "name": "customer_identifier",
                            "expression": {
                                "dialects": [
                                    {
                                        "dialect": "SNOWFLAKE",
                                        "expression": "customers.customer_id",
                                    }
                                ]
                            },
                        }
                    ],
                },
            ],
            "relationships": [
                {
                    "name": "orders_to_customers",
                    "from": "orders",
                    "to": "customers",
                    "from_columns": ["customer_id"],
                    "to_columns": ["customer_id"],
                }
            ],
        }
        objects = _editable_objects(document)
        datasets = next(item for item in objects if item["id"] == "dataset-0")
        relationships = next(item for item in objects if item["id"] == "relationship-0")
        dataset_kinds = {item["label"]: item["kind"] for item in datasets["properties"]}
        relationship_kinds = {item["label"]: item["kind"] for item in relationships["properties"]}
        self.assertEqual(dataset_kinds["Primary key"], "multi_select")
        self.assertEqual(dataset_kinds["Unique keys"], "key_selects")
        self.assertEqual(relationship_kinds["From columns"], "multi_select")
        self.assertEqual(relationship_kinds["To columns"], "multi_select")
        primary_key = next(
            item for item in datasets["properties"] if item["label"] == "Primary key"
        )
        from_columns = next(
            item for item in relationships["properties"] if item["label"] == "From columns"
        )
        self.assertEqual(primary_key["options"], ["customer_id", "order_id"])
        self.assertNotIn("customer_identifier", primary_key["options"])
        self.assertIn("customer_id", from_columns["options"])

    def test_powerbi_selectors_preserve_physical_keys_and_relationship_columns(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            built = convert_semantic(
                {
                    "request_id": "powerbi-workspace",
                    "source_path": str(ROOT / "tests/fixtures/powerbi"),
                    "model_name": "powerbi_workspace",
                    "output_dir": directory,
                }
            )
            model = load_document(str(built["raw_model_path"]))["semantic_model"][0]
            objects = _editable_objects(model)

        orders = next(item for item in objects if item["name"] == "orders")
        primary_key = next(item for item in orders["properties"] if item["label"] == "Primary key")
        relationship = next(item for item in objects if item["section"] == "relationships")
        from_columns = next(
            item for item in relationship["properties"] if item["label"] == "From columns"
        )
        self.assertEqual(primary_key["value"], ["order_id"])
        self.assertIn("order_id", primary_key["options"])
        self.assertNotIn("orderid", primary_key["options"])
        self.assertEqual(from_columns["value"], ["customer_id"])
        self.assertIn("customer_id", from_columns["options"])

    def test_loopback_server_rejects_bad_token_and_origin_and_saves_draft(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "semantic/generated") as directory:
            _, paths = self._build(directory)
            app = ReviewApplication(
                paths,
                request_id="workspace",
                verify_snowflake=False,
                config_path="snowflake_config.yaml",
                configuration_confirmed=False,
                promote_if_clean=False,
            )
            try:
                server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(app))
            except PermissionError:
                self.skipTest("loopback sockets are unavailable in this sandbox")
            port = int(server.server_address[1])
            app.origin = f"http://127.0.0.1:{port}"
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                connection.putrequest("POST", "/api/draft")
                connection.putheader("Content-Type", "application/json")
                connection.putheader("Content-Length", str(MAX_REQUEST_BYTES + 1))
                connection.putheader("Origin", app.origin)
                connection.putheader("X-Review-Token", app.token)
                connection.endheaders()
                oversized = connection.getresponse()
                self.assertEqual(oversized.status, 400)
                oversized.read()

                connection.request(
                    "POST",
                    "/api/draft",
                    body=json.dumps({"decisions": default_decisions(paths.raw)}),
                    headers={"Content-Type": "application/json", "Origin": app.origin},
                )
                self.assertEqual(connection.getresponse().status, 403)

                connection.request(
                    "POST",
                    "/api/draft",
                    body=json.dumps({"decisions": default_decisions(paths.raw)}),
                    headers={
                        "Content-Type": "application/json",
                        "Origin": "http://localhost:9999",
                        "X-Review-Token": app.token,
                    },
                )
                self.assertEqual(connection.getresponse().status, 403)

                connection.request(
                    "POST",
                    "/api/draft",
                    body=json.dumps({"decisions": default_decisions(paths.raw)}),
                    headers={
                        "Content-Type": "application/json",
                        "Origin": app.origin,
                        "X-Review-Token": app.token,
                    },
                )
                self.assertEqual(connection.getresponse().status, 200)
                self.assertTrue(paths.draft.is_file())

                connection.request(
                    "POST",
                    "/api/finish",
                    body="{}",
                    headers={
                        "Content-Type": "application/json",
                        "Origin": app.origin,
                        "X-Review-Token": app.token,
                    },
                )
                self.assertEqual(connection.getresponse().status, 200)
            finally:
                connection.close()
                thread.join(timeout=5)
                server.server_close()
            self.assertTrue(app.finished.is_set())


if __name__ == "__main__":
    unittest.main()
