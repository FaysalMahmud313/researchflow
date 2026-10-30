# ResearchFlow System Architecture

## 1. Overview

ResearchFlow is a modular monolith: a FastAPI backend (`backend/`) and a React + TypeScript + Vite frontend (`frontend/`). There are no background workers, WebSocket servers or external services; one backend process and the static frontend are the whole application.

```text
researchflow/
├── backend/app/
│   ├── api/v1/
│   │   ├── context.py        # Shared auth (cookie session + CSRF), RBAC, audit/activity logging, notifications
│   │   ├── router.py         # Auth, profiles, projects, members, tasks, files, experiments, search…
│   │   ├── manuscripts.py    # LaTeX papers: file tree, saving, versions, export/import, comments, suggestions
│   │   ├── bibliography.py   # BibTeX import/export, duplicates, cite-key maintenance, library→.bib sync
│   │   └── workspace.py      # Cross-project lists for the sidebar (/me/…)
│   ├── latex/
│   │   ├── textstore.py      # Text file storage with revisions (conflict detection) and version snapshots
│   │   ├── analysis.py       # Outline, section extraction, labels/citations, dependency report
│   │   ├── bibtex.py         # Tolerant BibTeX parser/serializer (custom fields preserved)
│   │   ├── export.py         # Project ZIP, flattened paper, assets ZIP, README
│   │   ├── importer.py       # Safe ZIP import, Markdown/DOCX conversion
│   │   ├── paths.py          # Manuscript path validation
│   │   └── templates.py      # Starter templates (structure only, no invented content)
│   ├── models/               # SQLite schema (SCHEMA_SQL baseline) + versioned migrations
│   ├── permissions/rbac.py   # Owner / Editor / Reviewer / Viewer matrix
│   ├── security/             # Passwords, tokens, rate limiting, sanitizers
│   └── storage/              # Private blob storage (streaming downloads, chunked uploads)
└── frontend/src/
    ├── workspace/            # Writing workspace (files · editor · tools/review/history)
    ├── editor/               # CodeMirror 6 LaTeX editor, completion, snippets, folding, structure check
    ├── components/           # Sidebar, top bar, diff view (@codemirror/merge), UI primitives
    └── pages/                # Overview, project lists, cross-project pages, project tabs, settings
```

The earlier mock-data prototype UI is kept, unused, at `frontend/legacy/PrototypeApp.tsx`.

## 2. One representation per paper

A paper (manuscript) is a row in `documents` with `doc_kind = 'latex'`. Its source tree is `manuscript_files` (text, binary assets and explicit folders, addressed by validated relative paths).

* **Manuscript status** (`documents.publication_status`: Working Draft … Archived) is per paper. Outcomes (*Submitted*, *Under Review*, *Revision Requested*, *Accepted*, *Published*, *Rejected*) are owner-only, matching the owner-controlled project publication status.
* **Review workflow** (`documents.review_status`) is separate from publication status.
* **TeX engine** (`documents.compiler`) records which engine the source is written for. It is only used in the export README; ResearchFlow does not compile.
* **Last editor**: saves and other mutations update `documents.updated_by_id/last_editor_name` and the project's `last_editor_*` fields.

## 3. Editing and saving

ResearchFlow does not support two people typing in the same file at the same moment. Members still share every paper and contribute at different times, and nobody's work is silently overwritten:

* Each text file stores `text_content` and a `revision` number.
* The editor loads `{content, revision}`. Saving (`PUT /manuscript-files/{id}/content`) sends the new text and the `base_revision` it started from.
* If another member saved in between, the server answers **409** with the newer text, its author and time. The editor stops autosaving, shows a conflict banner, and lets the user compare the two versions, load the newer one, or explicitly keep theirs. Keeping theirs saves against the newer revision, and the other version remains in History.
* Autosave runs 2 s after typing stops (it can be turned off per user). Ctrl/⌘+S saves immediately. The toolbar shows *Unsaved changes*, *Saving…*, *Saved* or *Save failed*. Leaving the page or switching files with unsaved changes saves first or asks.
* Every 20 s the editor checks for a newer saved revision. With no local edits it switches to the newer text quietly; otherwise it warns.
* **Versions** are recorded automatically on a save at least 10 minutes after the previous snapshot, on "Save version", around every restore and server-side rewrite, and on import. Restoring writes the old text as a new revision, so a restore can itself be undone.
* Server-side rewrites (accepted suggestions, cite-key renames, library→.bib sync) go through the same revision counter, so an open editor with unsaved edits gets a conflict instead of losing them.

## 4. Comments and suggestions

* A comment stores code-point offsets, the quoted text and 40 characters of context on each side. The client re-finds the passage after later edits: offsets first, then the quote with context, then the quote alone, accepting only a unique match. If the passage is gone, the comment still appears in the Review panel with its line number. Comments without a selection apply to the whole paper.
* Suggestions never change the document until an editor accepts one. On acceptance the server locates the original text the same way. If it is gone the suggestion is marked `stale` instead of being applied to the wrong place.

## 5. LaTeX export (no compilation)

The Tools panel and the server export the complete project ZIP (folder structure, `.bib`, figures and a README that says the archive has not been compiled), a flattened single `.tex`, individual sections (verbatim slices from the outline), the current file, the selection, the bibliography and the assets. `/manuscripts/{id}/dependencies` reports missing `\input` files, figures, bibliographies, cite keys and labels. In the editor, a lightweight structure check flags unbalanced braces and mismatched environments as you type.

## 6. Database and migrations

The relational layer is SQLite (WAL mode, busy timeout) accessed with parameterized SQL. `SCHEMA_SQL` is the baseline; later changes are numbered migrations in `app/models/migrations.py`, tracked in `schema_migrations` and applied at startup.

* `004` added papers, files, versions, comments, suggestions and BibTeX fields.
* `005` replaced live editing and compilation. It adds `manuscript_files.revision`, drops the compile-job and CRDT tables and the `yjs_state` column, and keeps the CRDT update log if it ever contains edits that never reached `text_content`.

> The runtime database layer is SQLite only. Porting means replacing `RelationalDatabase` with a PostgreSQL driver and converting the `?` placeholders and SQLite-specific DDL.

## 7. Uploads and storage

Blobs live outside any web root under random keys. Chunked uploads are idempotent per chunk index (safe retries), strictly ordered, resumable (`GET /uploads/{id}` reports progress), and validated against the declared size and project quota before finalization. Finalization streams the file to compute its checksum and moves it into place without loading it into memory. Downloads stream from disk. Uploading a file with the same name into the same folder creates a new version. Abandoned staging files are cleaned at startup. PDFs and Word files are stored and downloaded like any other research file and previewed in the browser where it can display them.
