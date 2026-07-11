---
name: snowflake-environment-setup
description: Set up Python, uv, the Snowflake connector, non-secret configuration, and browser SSO. Use before the first Snowflake action or when the environment is not ready.
---

# Procedure

1. Verify Python 3.11+ with `python3 --version`. If missing, guide the user through the official installer for their operating system; do not silently install system software.
2. Verify `uv` with `uv --version`. If missing, guide the user through the official `uv` installation.
3. Run `uv sync --extra dev --extra snowflake` from the repository root.
4. Read `snowflake_config.yaml`. Display only account, user, authenticator, role, warehouse, database, and schema.
5. Ask the user to fill any placeholders and confirm the displayed values. Never request or store a password, token, or private key.
6. Require `authenticator: externalbrowser`. Explain that the connection check opens the enterprise identity-provider login and may require VPN access.
7. Run `config-check`. After the user confirms, run `connection-check` with `configuration_confirmed: true`.
8. Stop if the effective role differs from the approved read-only role.

# Success output

Report Python and `uv` versions, dependency status, sanitized Snowflake context, effective role, and the next safe command.
