-- Migration 005: replace live (CRDT) editing and PDF compilation with plain saves.
-- Applied automatically for SQLite by app/models/migrations.py (tracked in schema_migrations).
-- This file documents the same change for PostgreSQL deployments.

-- Conflict detection: every save names the revision it was based on.
ALTER TABLE manuscript_files ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 1;

-- PDF compilation was removed; its job metadata is no longer used.
DROP TABLE IF EXISTS compile_jobs;

-- Live-editing storage. text_content already holds every file's text.
-- Only drop collab_updates when it is empty: rows there are edits that never reached text_content.
--   SELECT COUNT(*) FROM collab_updates;   -- must be 0
DROP TABLE IF EXISTS collab_updates;
ALTER TABLE manuscript_files DROP COLUMN IF EXISTS yjs_state;
