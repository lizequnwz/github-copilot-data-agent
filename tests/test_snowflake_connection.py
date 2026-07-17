from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from data_agent.config import Settings
from data_agent.io import ContractError
from data_agent.snowflake import _connect, config_check, connection_check, search_objects


class SnowflakeConnectionTests(unittest.TestCase):
    def _config(self, text: str) -> str:
        directory = tempfile.TemporaryDirectory(prefix="snowflake-config-")
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "snowflake.yaml"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_externalbrowser_allows_optional_context(self) -> None:
        path = self._config(
            "snowflake:\n"
            "  account: org-account\n"
            "  user: analyst\n"
            "  authenticator: EXTERNALBROWSER\n"
        )
        result = config_check({"request_id": "config", "config_path": path})
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["authentication"]["mode"], "externalbrowser")
        self.assertIsNone(result["configuration"]["role"])

    def test_oauth_uses_environment_token_without_exposing_it(self) -> None:
        path = self._config(
            "snowflake:\n"
            "  account: org-account\n"
            "  user: analyst\n"
            "  authenticator: oauth\n"
            "  oauth_token_env: TEST_SNOWFLAKE_TOKEN\n"
            "  role: REPORTING\n"
        )
        with patch.dict(os.environ, {"TEST_SNOWFLAKE_TOKEN": "super-secret"}, clear=False):
            result = config_check({"request_id": "config", "config_path": path})
            captured: dict[str, object] = {}
            connector = types.ModuleType("snowflake.connector")
            connector.connect = lambda **kwargs: captured.update(kwargs) or object()  # type: ignore[attr-defined]
            snowflake = types.ModuleType("snowflake")
            snowflake.connector = connector  # type: ignore[attr-defined]
            with patch.dict(
                sys.modules,
                {"snowflake": snowflake, "snowflake.connector": connector},
            ):
                _connect(
                    {"request_id": "connect", "configuration_confirmed": True},
                    Settings.from_file(path),
                )

        self.assertTrue(result["authentication"]["token_available"])
        self.assertNotIn("super-secret", repr(result))
        self.assertEqual(captured["authenticator"], "oauth")
        self.assertEqual(captured["token"], "super-secret")
        self.assertNotIn("warehouse", captured)
        self.assertNotIn("database", captured)
        self.assertNotIn("schema", captured)

    def test_oauth_missing_token_is_configuration_required(self) -> None:
        path = self._config(
            "snowflake:\n"
            "  account: org-account\n"
            "  user: analyst\n"
            "  authenticator: oauth\n"
            "  oauth_token_env: ABSENT_SNOWFLAKE_TOKEN\n"
        )
        with patch.dict(os.environ, {}, clear=True):
            result = config_check({"request_id": "config", "config_path": path})
        self.assertEqual(result["status"], "configuration_required")
        self.assertFalse(result["authentication"]["token_available"])

    def test_connection_context_differences_are_warnings(self) -> None:
        settings = Settings(
            account="account",
            user="preferred-user",
            authenticator="externalbrowser",
            role="PREFERRED_ROLE",
            warehouse=None,
            database=None,
            schema=None,
            query_tag="test",
            max_rows=10,
            max_bytes=1_000,
            timeout_seconds=10,
            blocked_schemas=(),
            allowed_objects=(),
            allow_sensitive_sampling=False,
        )

        class Cursor:
            sfqid = "query-id"

            def execute(self, _sql: str) -> None:
                return None

            def fetchone(self) -> tuple[str, str, str, str, str]:
                return ("actual-user", "ACTUAL_ROLE", "WH", "DB", "SCHEMA")

            def close(self) -> None:
                return None

        class Connection:
            def __enter__(self) -> Connection:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def cursor(self) -> Cursor:
                return Cursor()

        with (
            patch("data_agent.snowflake.load_settings", return_value=settings),
            patch("data_agent.snowflake._connect", return_value=Connection()),
        ):
            result = connection_check(
                {"request_id": "connection", "configuration_confirmed": True}
            )
        self.assertEqual(result["status"], "success")
        self.assertIn("effective role differs", " ".join(result["warnings"]))

    def test_object_search_requires_database_at_operation_boundary(self) -> None:
        settings = Settings(
            account="account",
            user="user",
            authenticator="externalbrowser",
            role=None,
            warehouse=None,
            database=None,
            schema=None,
            query_tag="test",
            max_rows=10,
            max_bytes=1_000,
            timeout_seconds=10,
            blocked_schemas=(),
            allowed_objects=(),
            allow_sensitive_sampling=False,
        )
        with patch("data_agent.snowflake.load_settings", return_value=settings):
            with self.assertRaisesRegex(ContractError, "request.database"):
                search_objects({"request_id": "search", "query": "orders"})


if __name__ == "__main__":
    unittest.main()
