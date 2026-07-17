from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_snowflake import run_check


class ConnectionDiagnosticsTests(unittest.TestCase):
    def _config(self, directory: str, *, oauth: bool = False) -> Path:
        path = Path(directory) / "snowflake.yaml"
        auth = "oauth" if oauth else "externalbrowser"
        path.write_text(
            "snowflake:\n"
            "  account: test_account\n"
            "  user: analyst@example.com\n"
            f"  authenticator: {auth}\n"
            "  oauth_token_env: TEST_SNOWFLAKE_TOKEN\n"
            "  warehouse: preferred_wh\n",
            encoding="utf-8",
        )
        return path

    def test_one_command_reports_preferred_and_effective_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._config(directory)
            captured: dict[str, object] = {}

            def connect(request: dict[str, object]) -> dict[str, object]:
                captured.update(request)
                return {
                    "actual_context": {
                        "user": "ANALYST@EXAMPLE.COM",
                        "role": "ANALYST",
                        "warehouse": "EFFECTIVE_WH",
                        "database": None,
                        "schema": None,
                    },
                    "warnings": ["effective warehouse differs from configured preference"],
                }

            code, lines = run_check(str(path), connect=connect)

        output = "\n".join(lines)
        self.assertEqual(code, 0)
        self.assertTrue(captured["configuration_confirmed"])
        self.assertIn("Status: connected", output)
        self.assertIn("warehouse=preferred_wh", output)
        self.assertIn("warehouse=EFFECTIVE_WH", output)
        self.assertIn("Warning: effective warehouse differs", output)

    def test_oauth_reports_only_environment_name_and_availability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._config(directory, oauth=True)
            with patch.dict(os.environ, {"TEST_SNOWFLAKE_TOKEN": "super-secret-token"}):
                code, lines = run_check(
                    str(path),
                    connect=lambda _request: {
                        "actual_context": {},
                        "warnings": [],
                    },
                )

        output = "\n".join(lines)
        self.assertEqual(code, 0)
        self.assertIn("TEST_SNOWFLAKE_TOKEN (available)", output)
        self.assertNotIn("super-secret-token", output)

    def test_missing_oauth_token_is_actionable_without_connecting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._config(directory, oauth=True)
            with patch.dict(os.environ, {}, clear=True):
                code, lines = run_check(
                    str(path),
                    connect=lambda _request: self.fail("connection should not be attempted"),
                )

        output = "\n".join(lines)
        self.assertEqual(code, 2)
        self.assertIn("Status: configuration required", output)
        self.assertIn("Fix: environment variable TEST_SNOWFLAKE_TOKEN is not set", output)


if __name__ == "__main__":
    unittest.main()
