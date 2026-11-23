"""Plain storage for manuscript text files with optimistic concurrency.

`manuscript_files.text_content` holds the current text and `revision` increases on every
write. A save must name the revision it was based on; if someone else saved in between,
the save is rejected so nobody's work is silently overwritten.
"""
import hashlib
import uuid
from datetime import UTC
from typing import Any, Optional

AUTO_VERSION_INTERVAL_SECONDS = 600


def utc_now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()


class RevisionConflict(Exception):
    def __init__(self, current: dict[str, Any]) -> None:
        super().__init__("Revision conflict")
        self.current = current


def get_text(conn: Any, file_id: str) -> str:
    row = conn.execute("SELECT text_content FROM manuscript_files WHERE id = ?", (file_id,)).fetchone()
    return row["text_content"] if row else ""


def current_state(conn: Any, file_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT f.revision, f.text_content, f.updated_at, u.full_name AS updated_by_name "
        "FROM manuscript_files f LEFT JOIN users u ON u.id = f.updated_by_id WHERE f.id = ?",
        (file_id,),
    ).fetchone()
    return dict(row) if row else {}


def create_version(
    conn: Any, file_id: str, kind: str, summary: str, user_id: Optional[str], text: str, force: bool = False
) -> dict[str, Any]:
    """Record a version unless the text equals the latest version (or `force`)."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    f = conn.execute("SELECT document_id FROM manuscript_files WHERE id = ?", (file_id,)).fetchone()
    latest = conn.execute(
        "SELECT version_number, content_sha256 FROM file_text_versions WHERE file_id = ? ORDER BY version_number DESC LIMIT 1",
        (file_id,),
    ).fetchone()
    if latest and latest["content_sha256"] == digest and not force:
        return {"version_number": latest["version_number"], "created": False}
    number = (int(latest["version_number"]) if latest else 0) + 1
    vid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO file_text_versions (id, file_id, document_id, version_number, content, content_sha256, summary, "
        "version_kind, author_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (vid, file_id, f["document_id"], number, text, digest, summary[:300], kind, user_id, utc_now_iso()),
    )
    return {"id": vid, "version_number": number, "created": True}


def _maybe_auto_version(conn: Any, file_id: str, user_id: str, text: str) -> bool:
    """Snapshot after meaningful idle time so history stays useful without a version per keystroke."""
    from datetime import datetime

    latest = conn.execute(
        "SELECT created_at FROM file_text_versions WHERE file_id = ? ORDER BY version_number DESC LIMIT 1", (file_id,)
    ).fetchone()
    if latest:
        age = (datetime.now(UTC) - datetime.fromisoformat(latest["created_at"])).total_seconds()
        if age < AUTO_VERSION_INTERVAL_SECONDS:
            return False
    return bool(create_version(conn, file_id, "auto", "Automatic snapshot", user_id, text).get("created"))


def write_text(
    conn: Any,
    file_id: str,
    text: str,
    user_id: str,
    expected_revision: Optional[int] = None,
    auto_version: bool = True,
) -> dict[str, Any]:
    """Store new text. With `expected_revision`, refuse to overwrite a newer saved revision."""
    row = conn.execute("SELECT revision, text_content FROM manuscript_files WHERE id = ?", (file_id,)).fetchone()
    if expected_revision is not None and int(row["revision"]) != expected_revision:
        raise RevisionConflict(current_state(conn, file_id))
    if row["text_content"] == text:
        return {"revision": int(row["revision"]), "changed": False, "version_created": False}
    revision = int(row["revision"]) + 1
    now = utc_now_iso()
    conn.execute(
        "UPDATE manuscript_files SET text_content = ?, size_bytes = ?, revision = ?, updated_by_id = ?, updated_at = ? WHERE id = ?",
        (text, len(text.encode("utf-8")), revision, user_id, now, file_id),
    )
    version_created = _maybe_auto_version(conn, file_id, user_id, text) if auto_version else False
    return {"revision": revision, "changed": True, "version_created": version_created, "updated_at": now}


def replace_with_history(conn: Any, file_id: str, text: str, user_id: str, summary: str) -> dict[str, Any]:
    """Server-side rewrite (e.g. cite-key rename, library sync) that stays recoverable from history."""
    before = get_text(conn, file_id)
    if before == text:
        return {"changed": False}
    create_version(conn, file_id, "auto", f"Before: {summary}"[:300], user_id, before)
    result = write_text(conn, file_id, text, user_id, auto_version=False)
    create_version(conn, file_id, "auto", summary, user_id, text)
    return result
