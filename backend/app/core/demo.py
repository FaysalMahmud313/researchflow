"""The local demo account (development and testing only).

These credentials are public on purpose so anyone can try ResearchFlow locally. They are
never created outside development/testing: ensure_demo_account() refuses, and the login
page hint (GET /auth/dev-demo) only exists when APP_ENV=development.
"""
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.config import AppSettings
from app.security.passwords import hash_password

DEMO_USERNAME = "researchflow_demo"
DEMO_EMAIL = "demo@researchflow.local"
DEMO_PASSWORD = "ResearchFlowDemo!2026"  # noqa: S105 - documented local demo account
DEMO_FULL_NAME = "Demo Researcher"
DEMO_PROJECT_TITLE = "Demo: Climate Downscaling Study"

ALLOWED_ENVS = ("development", "testing")


class DemoSeedRefused(RuntimeError):
    pass


def ensure_demo_account(conn: Any, settings: AppSettings) -> str:
    """Create the demo user, or restore its known password if it exists. Returns the user id."""
    if settings.app_env not in ALLOWED_ENVS:
        raise DemoSeedRefused(
            f"The demo account is only for local development. APP_ENV is '{settings.app_env}', so nothing was created."
        )
    now = datetime.now(UTC).isoformat()
    row = conn.execute(
        "SELECT id FROM users WHERE username = ? OR email = ?", (DEMO_USERNAME, DEMO_EMAIL)
    ).fetchone()
    pw_hash = hash_password(DEMO_PASSWORD)
    if row:
        conn.execute(
            "UPDATE users SET password_hash = ?, email_verified = 1, is_active = 1, updated_at = ? WHERE id = ?",
            (pw_hash, now, row["id"]),
        )
        return str(row["id"])
    user_id = f"usr_{uuid.uuid4().hex[:16]}"
    conn.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, email_verified, is_active, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)",
        (user_id, DEMO_USERNAME, DEMO_EMAIL, DEMO_FULL_NAME, pw_hash, now, now),
    )
    conn.execute(
        "INSERT INTO user_profiles (user_id, professional_title, updated_at) VALUES (?, ?, ?)",
        (user_id, "Demo account", now),
    )
    return user_id


def demo_account_exists(conn: Any) -> bool:
    return conn.execute("SELECT 1 FROM users WHERE username = ?", (DEMO_USERNAME,)).fetchone() is not None
