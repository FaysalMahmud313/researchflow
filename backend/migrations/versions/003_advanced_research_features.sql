-- Migration 003: Advanced Research Management, LaTeX, Chunked Uploads, Artifacts & Collaboration Signals
ALTER TABLE projects ADD COLUMN publication_status TEXT NOT NULL DEFAULT 'Research in Progress';
ALTER TABLE projects ADD COLUMN last_editor_id TEXT;
ALTER TABLE projects ADD COLUMN last_editor_name TEXT NOT NULL DEFAULT '';
ALTER TABLE projects ADD COLUMN last_edited_at TEXT NOT NULL DEFAULT '';

ALTER TABLE documents ADD COLUMN publication_status TEXT NOT NULL DEFAULT 'Working Draft';
ALTER TABLE documents ADD COLUMN paper_section TEXT NOT NULL DEFAULT 'Full Manuscript';
ALTER TABLE documents ADD COLUMN linked_artifacts_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE documents ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0;
ALTER TABLE documents ADD COLUMN deleted_at TEXT;

ALTER TABLE datasets_files ADD COLUMN artifact_type TEXT NOT NULL DEFAULT 'dataset';
ALTER TABLE datasets_files ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0;
ALTER TABLE datasets_files ADD COLUMN deleted_at TEXT;
ALTER TABLE datasets_files ADD COLUMN linked_entity_type TEXT NOT NULL DEFAULT '';
ALTER TABLE datasets_files ADD COLUMN linked_entity_id TEXT NOT NULL DEFAULT '';
ALTER TABLE datasets_files ADD COLUMN last_editor_name TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS upload_sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    folder TEXT NOT NULL DEFAULT '/',
    artifact_type TEXT NOT NULL DEFAULT 'dataset',
    total_size_bytes INTEGER NOT NULL,
    total_chunks INTEGER NOT NULL DEFAULT 1,
    uploaded_chunks INTEGER NOT NULL DEFAULT 0,
    bytes_received INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('in_progress', 'completed', 'cancelled', 'failed')),
    temp_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    artifact_type TEXT NOT NULL CHECK (artifact_type IN ('code', 'dataset', 'notebook', 'result', 'figure', 'log', 'checkpoint')),
    language TEXT NOT NULL DEFAULT 'python',
    content_text TEXT NOT NULL DEFAULT '',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    parameters_json TEXT NOT NULL DEFAULT '{}',
    unit_system TEXT NOT NULL DEFAULT 'SI',
    linked_experiment_id TEXT NOT NULL DEFAULT '',
    linked_dataset_version TEXT NOT NULL DEFAULT '',
    linked_code_version TEXT NOT NULL DEFAULT '',
    linked_paper_section TEXT NOT NULL DEFAULT '',
    version_number INTEGER NOT NULL DEFAULT 1,
    tags_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT '',
    creator_id TEXT NOT NULL REFERENCES users(id),
    last_editor_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collaboration_signals (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    full_name TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    proposed_contribution TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('Pending', 'Acknowledged', 'Accepted', 'Declined', 'Withdrawn')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_collab_signals_proj_user ON collaboration_signals(project_id, user_id);
