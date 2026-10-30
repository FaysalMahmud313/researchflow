"""Server-side account administration (run on the server, from the backend folder).

    python scripts/admin.py list-users
    python scripts/admin.py reset-password <username-or-email>
    python scripts/admin.py verify-email <username-or-email>

Reads the same .env as the app (default: backend/.env, override with --env-file).
Use reset-password when email delivery (SMTP) is not configured.
"""
import argparse
import getpass
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", default=str(BACKEND / ".env"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-users")
    for name in ("reset-password", "verify-email"):
        sub.add_parser(name).add_argument("identifier", help="username or email")
    args = parser.parse_args()

    load_env(Path(args.env_file))
    from app.core.config import load_settings_from_env
    from app.models.database import RelationalDatabase
    from app.security.passwords import hash_password, validate_password_strength

    cfg = load_settings_from_env()
    db_path = cfg.database_path or (cfg.database_url[len("sqlite:///"):] if cfg.database_url.startswith("sqlite:///") else "")
    if not db_path:
        print("Set DATABASE_PATH in the .env file.", file=sys.stderr)
        return 2
    db = RelationalDatabase(db_path)
    now = datetime.now(UTC).isoformat()

    with db.transaction() as conn:
        if args.command == "list-users":
            for r in conn.execute("SELECT username, email, full_name, email_verified, is_active, created_at FROM users ORDER BY created_at"):
                print(f"{r['username']:<20} {r['email']:<32} {'verified' if r['email_verified'] else 'unverified':<10} "
                      f"{'active' if r['is_active'] else 'disabled':<8} {r['full_name']}")
            return 0
        user = conn.execute("SELECT id, username FROM users WHERE username = ? OR email = ?", (args.identifier, args.identifier)).fetchone()
        if not user:
            print(f"No user '{args.identifier}'.", file=sys.stderr)
            return 1
        if args.command == "verify-email":
            conn.execute("UPDATE users SET email_verified = 1, updated_at = ? WHERE id = ?", (now, user["id"]))
            print(f"Marked @{user['username']} as verified.")
            return 0

    password = getpass.getpass(f"New password for @{user['username']}: ")
    if password != getpass.getpass("Repeat it: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1
    ok, message = validate_password_strength(password)
    if not ok:
        print(message, file=sys.stderr)
        return 1
    with db.transaction() as conn:
        conn.execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?", (hash_password(password), now, user["id"]))
        conn.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (user["id"],))
        conn.execute(
            "INSERT INTO audit_events (id, actor_id, event_type, project_id, ip_address, details, created_at) "
            "VALUES (lower(hex(randomblob(16))), ?, 'PASSWORD_RESET_BY_ADMIN', NULL, 'cli', 'Password reset from scripts/admin.py', ?)",
            (user["id"], now),
        )
    print(f"Password updated for @{user['username']}; their existing sessions were signed out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
