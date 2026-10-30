-- Migration 004: LaTeX papers, real-time collaboration, versions, review, compilation, BibTeX fields.
-- Applied automatically for SQLite by app/models/migrations.py (tracked in schema_migrations).
-- This file documents the same change for PostgreSQL deployments.

ALTER TABLE documents ADD COLUMN IF NOT EXISTS doc_kind TEXT NOT NULL DEFAULT 'rich_text';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS main_file_path TEXT NOT NULL DEFAULT 'main.tex';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS compiler TEXT NOT NULL DEFAULT 'pdflatex';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS last_editor_name TEXT NOT NULL DEFAULT '';
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS workspace_prefs_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE literature_references ADD COLUMN IF NOT EXISTS cite_key TEXT NOT NULL DEFAULT '';
ALTER TABLE literature_references ADD COLUMN IF NOT EXISTS entry_type TEXT NOT NULL DEFAULT 'article';
ALTER TABLE literature_references ADD COLUMN IF NOT EXISTS fields_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE literature_references ADD COLUMN IF NOT EXISTS updated_at TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS manuscript_files (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    file_kind TEXT NOT NULL CHECK (file_kind IN ('text', 'binary', 'folder')),
    text_content TEXT NOT NULL DEFAULT '',
    yjs_state BYTEA,
    storage_key TEXT NOT NULL DEFAULT '',
    size_bytes BIGINT NOT NULL DEFAULT 0,
    media_type TEXT NOT NULL DEFAULT 'text/plain',
    checksum_sha256 TEXT NOT NULL DEFAULT '',
    is_deleted INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT,
    created_by_id TEXT NOT NULL REFERENCES users(id),
    updated_by_id TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_manuscript_files_active_path ON manuscript_files(document_id, path) WHERE is_deleted = 0;
CREATE INDEX IF NOT EXISTS idx_manuscript_files_doc ON manuscript_files(document_id, is_deleted);

CREATE TABLE IF NOT EXISTS collab_updates (
    seq BIGSERIAL PRIMARY KEY,
    file_id TEXT NOT NULL REFERENCES manuscript_files(id) ON DELETE CASCADE,
    update_blob BYTEA NOT NULL,
    user_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_collab_updates_file ON collab_updates(file_id, seq);

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

CREATE TABLE IF NOT EXISTS compile_jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    requested_by_id TEXT NOT NULL REFERENCES users(id),
    engine TEXT NOT NULL,
    main_file TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'unavailable')),
    input_hash TEXT NOT NULL DEFAULT '',
    log_text TEXT NOT NULL DEFAULT '',
    diagnostics_json TEXT NOT NULL DEFAULT '[]',
    pdf_storage_key TEXT NOT NULL DEFAULT '',
    pdf_size_bytes BIGINT NOT NULL DEFAULT 0,
    cached_from_job_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_compile_jobs_doc ON compile_jobs(document_id, created_at);
CREATE INDEX IF NOT EXISTS idx_compile_jobs_hash ON compile_jobs(document_id, input_hash, status);

CREATE INDEX IF NOT EXISTS idx_documents_project_kind ON documents(project_id, doc_kind, is_deleted);
CREATE UNIQUE INDEX IF NOT EXISTS ux_refs_project_citekey ON literature_references(project_id, cite_key) WHERE cite_key != '';
