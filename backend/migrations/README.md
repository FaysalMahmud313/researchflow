# ResearchFlow Database Migrations

- `SCHEMA_SQL` in `app/models/database.py` is the baseline schema (equivalent to `001`–`003`).
- Later changes are numbered Python migrations in `app/models/migrations.py`. They are recorded in the `schema_migrations` table and applied automatically at startup, so existing SQLite databases are upgraded in place. Each migration is idempotent.
- `versions/*.sql` documents each change as SQL for PostgreSQL deployments. The runtime database layer is currently SQLite only (see `docs/ARCHITECTURE.md`).

| Version | Name | Summary |
| --- | --- | --- |
| 004 | latex_collaboration | LaTeX papers and file trees, file versions, anchored comments, suggestions, BibTeX cite keys and fields, workspace preferences |
| 005 | simple_editing | Adds `manuscript_files.revision` for conflict-safe saves. Drops the compile-job table and the live-editing (CRDT) storage, keeping the CRDT update log only if it holds edits that never reached `text_content`. No papers, files, versions, comments or references are removed. |
