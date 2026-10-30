"""Shared request context for v1 routers: authentication, CSRF, RBAC, audit and activity logging.

Every router module receives one `ApiContext` so authorization rules live in exactly one place.
"""
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request

from app.core.config import AppSettings
from app.models.database import RelationalDatabase
from app.permissions.rbac import Permission, role_has_permission
from app.security.rate_limit import SlidingWindowRateLimiter
from app.security.tokens import hash_token, verify_csrf_token
from app.storage.private_storage import PrivateStorageEngine

# Notification kind -> user preference key (see Account & Settings).
NOTIFICATION_CATEGORIES = {
    "invitation": "invitations",
    "mention": "mentions",
    "comment": "comments",
    "suggestion": "comments",
    "review": "comments",
    "publication_status": "project_updates",
    "collaboration_signal": "project_updates",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ApiContext:
    def __init__(
        self,
        settings: AppSettings,
        db: RelationalDatabase,
        storage: PrivateStorageEngine,
        rate_limiter: SlidingWindowRateLimiter,
    ) -> None:
        self.settings = settings
        self.db = db
        self.storage = storage
        self.rate_limiter = rate_limiter

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------
    def log_audit(
        self,
        conn: Any,
        event_type: str,
        details: str,
        actor_id: Optional[str] = None,
        project_id: Optional[str] = None,
        ip_address: str = "127.0.0.1",
    ) -> None:
        conn.execute(
            "INSERT INTO audit_events (id, actor_id, event_type, project_id, ip_address, details, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, actor_id, event_type, project_id, ip_address, details, utc_now_iso()),
        )

    def log_activity(
        self,
        conn: Any,
        project_id: str,
        actor_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        summary: str,
    ) -> None:
        """Record an activity event and update the project's single definition of 'last editor'."""
        now = utc_now_iso()
        conn.execute(
            "INSERT INTO activity_events (id, project_id, actor_id, action, entity_type, entity_id, summary, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, project_id, actor_id, action, entity_type, entity_id, summary, now),
        )
        u_row = conn.execute("SELECT full_name FROM users WHERE id = ?", (actor_id,)).fetchone()
        editor_name = u_row["full_name"] if u_row else ""
        conn.execute(
            "UPDATE projects SET last_editor_id = ?, last_editor_name = ?, last_edited_at = ?, updated_at = ? WHERE id = ?",
            (actor_id, editor_name, now, now, project_id),
        )

    def notify(self, conn: Any, user_id: str, project_id: Optional[str], kind: str, title: str, message: str) -> None:
        """Create an in-app notification unless the recipient turned that category off."""
        category = NOTIFICATION_CATEGORIES.get(kind)
        if category:
            row = conn.execute("SELECT notification_preferences FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
            prefs = json.loads(row["notification_preferences"]) if row and row["notification_preferences"] else {}
            if prefs.get(category) is False:
                return
        conn.execute(
            "INSERT INTO notifications (id, user_id, project_id, kind, title, message, is_read, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
            (uuid.uuid4().hex, user_id, project_id, kind, title, message, utc_now_iso()),
        )

    # -------------------------------------------------------------------------
    # Rate limiting
    # -------------------------------------------------------------------------
    def enforce_rate_limit(self, request: Request, bucket: str, limit: int, key_suffix: str = "") -> None:
        if not self.settings.rate_limit_enabled:
            return
        client_ip = request.client.host if request.client else "127.0.0.1"
        allowed, retry_after = self.rate_limiter.check_and_record(f"{bucket}:{client_ip}:{key_suffix}", limit)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please wait before retrying.",
                headers={"Retry-After": str(retry_after)},
            )

    # -------------------------------------------------------------------------
    # Sessions
    # -------------------------------------------------------------------------
    def resolve_session_token(self, conn: Any, raw_cookie: str) -> Optional[Dict[str, Any]]:
        """Return the active session row for a raw cookie value, or None. Expired sessions are revoked."""
        token_digest = hash_token(raw_cookie, self.settings.token_hash_pepper)
        row = conn.execute(
            "SELECT s.id AS session_id, s.user_id, s.csrf_secret, s.expires_at, s.revoked, "
            "u.username, u.email, u.full_name, u.email_verified, u.is_active "
            "FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ?",
            (token_digest,),
        ).fetchone()
        if not row or row["revoked"] or not row["is_active"]:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(UTC):
            conn.execute("UPDATE sessions SET revoked = 1 WHERE id = ?", (row["session_id"],))
            return None
        return dict(row)

    def get_current_session_and_user(self, request: Request) -> Dict[str, Any]:
        raw_cookie = request.cookies.get(self.settings.session_cookie_name)
        if not raw_cookie:
            raise HTTPException(status_code=401, detail="Authentication required.")
        with self.db.transaction() as conn:
            row = self.resolve_session_token(conn, raw_cookie)
            if row is None:
                raise HTTPException(status_code=401, detail="Session expired or invalid.")

            # Enforce CSRF protection for state-changing requests
            if self.settings.csrf_protection_enabled and request.method in ("POST", "PATCH", "PUT", "DELETE"):
                csrf_header = request.headers.get(self.settings.csrf_header_name, "")
                if not verify_csrf_token(csrf_header, row["session_id"], row["csrf_secret"]):
                    self.log_audit(
                        conn,
                        "CSRF_VALIDATION_FAILED",
                        f"Missing or invalid CSRF token on {request.method} {request.url.path}",
                        actor_id=row["user_id"],
                    )
                    raise HTTPException(status_code=403, detail="CSRF token validation failed.")
            return row

    # -------------------------------------------------------------------------
    # Authorization
    # -------------------------------------------------------------------------
    def get_project_role(self, conn: Any, project_id: str, user_id: str) -> Optional[str]:
        member = conn.execute(
            "SELECT role FROM project_memberships WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
        return str(member["role"]) if member else None

    def require_project_permission(
        self,
        conn: Any,
        project_id: str,
        user_id: str,
        permission: Permission,
    ) -> str:
        proj = conn.execute("SELECT id, status FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found.")
        role_str = self.get_project_role(conn, project_id, user_id)
        if role_str is None:
            self.log_audit(
                conn,
                "UNAUTHORIZED_PROJECT_ACCESS",
                f"User {user_id} attempted {permission.value} on project {project_id} without membership",
                actor_id=user_id,
                project_id=project_id,
            )
            raise HTTPException(status_code=403, detail="You do not have access to this project.")
        if not role_has_permission(role_str, permission):
            self.log_audit(
                conn,
                "PERMISSION_DENIED",
                f"User {user_id} with role '{role_str}' denied '{permission.value}'",
                actor_id=user_id,
                project_id=project_id,
            )
            raise HTTPException(
                status_code=403,
                detail=f"Role '{role_str}' does not have permission '{permission.value}'.",
            )
        return role_str

    def load_document_for(
        self, conn: Any, document_id: str, user_id: str, permission: Permission, include_deleted: bool = False
    ) -> Dict[str, Any]:
        """Load a document and enforce project-level permission. Unknown and foreign ids are indistinguishable."""
        doc = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not doc or (doc["is_deleted"] and not include_deleted):
            raise HTTPException(status_code=404, detail="Document not found.")
        if self.get_project_role(conn, doc["project_id"], user_id) is None:
            self.log_audit(
                conn,
                "UNAUTHORIZED_DOCUMENT_ACCESS",
                f"User {user_id} attempted {permission.value} on document {document_id}",
                actor_id=user_id,
                project_id=doc["project_id"],
            )
            raise HTTPException(status_code=404, detail="Document not found.")
        self.require_project_permission(conn, doc["project_id"], user_id, permission)
        return dict(doc)
