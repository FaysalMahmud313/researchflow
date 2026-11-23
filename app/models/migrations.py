"""Versioned, idempotent schema migrations.

`SCHEMA_SQL` in database.py is the version-3 baseline. Every later schema change is a
numbered migration recorded in `schema_migrations`, so existing databases are upgraded in
place instead of silently missing columns. The SQL equivalents live in
`backend/migrations/versions/` for PostgreSQL deployments.
"""
import re
import sqlite3
from typing import Callable

MigrationFn = Callable[[sqlite3.Connection], None]


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()  # noqa: S608 - table names are constants
    return any(r[1] == column for r in rows)


def _add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if not _has_column(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")  # noqa: S608 - constants only


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def migration_004_latex_collaboration(conn: sqlite3.Connection) -> None:
    # Manuscripts reuse the `documents` table: one row per paper, `doc_kind = 'latex'` for source projects.
    _add_column(conn, "documents", "doc_kind", "TEXT NOT NULL DEFAULT 'rich_text'")
    _add_column(conn, "documents", "main_file_path", "TEXT NOT NULL DEFAULT 'main.tex'")
    _add_column(conn, "documents", "compiler", "TEXT NOT NULL DEFAULT 'pdflatex'")
    _add_column(conn, "documents", "last_editor_name", "TEXT NOT NULL DEFAULT ''")

    _add_column(conn, "user_profiles", "workspace_prefs_json", "TEXT NOT NULL DEFAULT '{}'")

    # BibTeX-faithful bibliography: cite keys, entry types and every field (custom fields preserved).
    _add_column(conn, "literature_references", "cite_key", "TEXT NOT NULL DEFAULT ''")
    _add_column(conn, "literature_references", "entry_type", "TEXT NOT NULL DEFAULT 'article'")
    _add_column(conn, "literature_references", "fields_json", "TEXT NOT NULL DEFAULT '{}'")
    _add_column(conn, "literature_references", "updated_at", "TEXT NOT NULL DEFAULT ''")

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS manuscript_files (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            file_kind TEXT NOT NULL CHECK (file_kind IN ('text', 'binary', 'folder')),
            text_content TEXT NOT NULL DEFAULT '',
            storage_key TEXT NOT NULL DEFAULT '',
            size_bytes INTEGER NOT NULL DEFAULT 0,
            media_type TEXT NOT NULL DEFAULT 'text/plain',
            checksum_sha256 TEXT NOT NULL DEFAULT '',
            is_deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            created_by_id TEXT NOT NULL REFERENCES users(id),
            updated_by_id TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_manuscript_files_active_path
            ON manuscript_files(document_id, path) WHERE is_deleted = 0;
        CREATE INDEX IF NOT EXISTS idx_manuscript_files_doc ON manuscript_files(document_id, is_deleted);

        CREATE TABLE IF NOT EXISTS file_text_versions (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL REFERENCES manuscript_files(id) ON DELETE CASCADE,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            content TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            version_kind TEXT NOT NULL CHECK (version_kind IN ('auto', 'manual', 'restore', 'import', 'initial')),
            author_id TEXT REFERENCES users(id),
            created_at TEXT NOT NULL,
            UNIQUE(file_id, version_number)
        );
        CREATE INDEX IF NOT EXISTS idx_file_text_versions_file ON file_text_versions(file_id, version_number);

        CREATE TABLE IF NOT EXISTS doc_comments (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            file_id TEXT REFERENCES manuscript_files(id) ON DELETE SET NULL,
            parent_id TEXT REFERENCES doc_comments(id) ON DELETE CASCADE,
            body TEXT NOT NULL,
            anchor_json TEXT NOT NULL DEFAULT '{}',
            quoted_text TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
            mentions_json TEXT NOT NULL DEFAULT '[]',
            author_id TEXT NOT NULL REFERENCES users(id),
            resolved_by_id TEXT REFERENCES users(id),
            is_deleted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_doc_comments_doc ON doc_comments(document_id, status);

        CREATE TABLE IF NOT EXISTS doc_suggestions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            file_id TEXT NOT NULL REFERENCES manuscript_files(id) ON DELETE CASCADE,
            author_id TEXT NOT NULL REFERENCES users(id),
            anchor_json TEXT NOT NULL DEFAULT '{}',
            original_text TEXT NOT NULL DEFAULT '',
            proposed_text TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected', 'stale')),
            resolved_by_id TEXT REFERENCES users(id),
            resolved_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_doc_suggestions_file ON doc_suggestions(file_id, status);

        CREATE INDEX IF NOT EXISTS idx_documents_project_kind ON documents(project_id, doc_kind, is_deleted);
        CREATE INDEX IF NOT EXISTS idx_refs_project ON literature_references(project_id);
        CREATE INDEX IF NOT EXISTS idx_activity_project ON activity_events(project_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_datasets_files_project ON datasets_files(project_id, is_deleted);
        """
    )

    # Backfill unique cite keys for references created before this migration.
    rows = conn.execute(
        "SELECT id, project_id, authors, year FROM literature_references WHERE cite_key = '' ORDER BY created_at"
    ).fetchall()
    for r in rows:
        first = (r[2] or "ref").split(",")[0].strip().split()
        base = (_slug(first[-1] if first else "ref") or "ref") + str(r[3])
        key, n = base, 1
        while conn.execute(
            "SELECT 1 FROM literature_references WHERE project_id = ? AND cite_key = ?", (r[1], key)
        ).fetchone():
            n += 1
            key = f"{base}{chr(96 + n) if n <= 26 else n}"
        conn.execute("UPDATE literature_references SET cite_key = ? WHERE id = ?", (key, r[0]))
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_refs_project_citekey ON literature_references(project_id, cite_key) "
        "WHERE cite_key != ''"
    )


def migration_005_simple_editing(conn: sqlite3.Connection) -> None:
    """Replace live (CRDT) editing and PDF compilation with plain saves.

    * `manuscript_files.revision` enables conflict detection on save.
    * Compile job metadata and the CRDT columns/tables are removed. `text_content` was kept
      in sync by the old collaboration server, so it already holds every file's text.
    * Pending CRDT updates (edits that never reached `text_content`) are never discarded:
      if any exist, `collab_updates` is kept and a warning is logged.
    """
    import logging

    _add_column(conn, "manuscript_files", "revision", "INTEGER NOT NULL DEFAULT 1")
    conn.execute("DROP TABLE IF EXISTS compile_jobs")

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "collab_updates" in tables:
        pending = conn.execute("SELECT COUNT(*) FROM collab_updates").fetchone()[0]
        if pending:
            logging.getLogger("researchflow.migrations").warning(
                "Kept table collab_updates: %s live-editing updates were never folded into text_content.", pending
            )
        else:
            conn.execute("DROP TABLE collab_updates")
    if _has_column(conn, "manuscript_files", "yjs_state"):
        conn.execute("ALTER TABLE manuscript_files DROP COLUMN yjs_state")


def migration_006_profile_pictures(conn: sqlite3.Connection) -> None:
    """Profile pictures: storage key of the processed image and a version for cache-busting URLs."""
    _add_column(conn, "user_profiles", "avatar_key", "TEXT NOT NULL DEFAULT ''")
    _add_column(conn, "user_profiles", "avatar_version", "TEXT NOT NULL DEFAULT ''")


MIGRATIONS: list[tuple[int, str, MigrationFn]] = [
    (4, "latex_collaboration", migration_004_latex_collaboration),
    (5, "simple_editing", migration_005_simple_editing),
    (6, "profile_pictures", migration_006_profile_pictures),
]


def apply_pending_migrations(conn: sqlite3.Connection) -> list[int]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
    ran: list[int] = []
    for version, name, fn in MIGRATIONS:
        if version in applied:
            continue
        fn(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, datetime('now'))",
            (version, name),
        )
        ran.append(version)
    return ran
