# ResearchFlow — Research Management Workspace

ResearchFlow keeps a research team's work in one place: LaTeX papers with an editor, version history, comments and suggestions; a BibTeX reference manager; datasets, code, results and experiments with comparisons; tasks; and portable LaTeX export. Access is enforced on the server with the `Owner`, `Editor`, `Reviewer` and `Viewer` roles.

ResearchFlow **writes and exports LaTeX source**. It does not compile PDFs. Download the project ZIP and build it with your own TeX installation or an online LaTeX editor.

Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Security: [docs/SECURITY.md](docs/SECURITY.md) · API: [docs/API_CONTRACT.md](docs/API_CONTRACT.md)

## 1. Quick start on Windows (one click)

1. Install **Python 3.11+** (python.org, tick "Add to PATH") and **Node.js LTS** (nodejs.org). Nothing else is needed: no Docker, TeX or database server.
2. Double-click **`start_local_pc.bat`**.

The first run installs everything and creates `backend/.env` with fresh secrets (a few minutes); later runs start in seconds. Your browser opens at http://localhost:5173. To stop, close the two server windows.

| Address | What it is |
| --- | --- |
| **http://localhost:5173** | The app: open this one |
| http://127.0.0.1:8000 | The API behind it (opening it just forwards you to the app) |

If a window says the port is already in use, ResearchFlow is probably still running from last time. Close the old "ResearchFlow backend/frontend" windows, or restart the PC, and start again.

### Local demo account (development only)

```bash
cd backend
.venv\Scripts\python.exe scripts\seed_dev.py
```

Then open http://localhost:5173 and sign in as **researchflow_demo** (or `demo@researchflow.local`) with password **ResearchFlowDemo!2026**. The login page also offers a "Use it" shortcut while you run in development.

The script creates the account (email already verified) and a sample project, *Demo: Climate Downscaling Study*, with a paper and a reference. Running it again is safe: nothing is duplicated, and the demo password is restored if it was changed. It refuses to run unless `APP_ENV` is `development` or `testing`, and the login hint only exists in development, so these public credentials can never reach a deployed server. They are defined in `backend/app/core/demo.py`.

## 2. Manual start (any OS)

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cd ../frontend
npm install
```

Copy `.env.example` to `backend/.env` (never commit it) and replace the three secrets with values from `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Then:

```bash
# Terminal 1: backend API on http://127.0.0.1:8000
cd backend
uvicorn app.main:app --env-file .env --host 127.0.0.1 --port 8000

# Terminal 2: frontend on http://localhost:5173 (Vite proxies /api to the backend)
cd frontend
npm run dev
```

## 3. Configuration

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | `development`, `testing`, `staging`, `production` (staging/production refuse insecure settings at startup) |
| `FRONTEND_ORIGIN` | Exact browser origin (CORS) |
| `DATABASE_PATH` | SQLite file; migrations run automatically at startup |
| `PRIVATE_STORAGE_DIR` | Private file storage outside any web root |
| `MAX_UPLOAD_SIZE_BYTES`, `PROJECT_STORAGE_QUOTA_BYTES` | Size of a single-request upload and per-project quota. Large files use resumable chunked uploads |
| `EMAIL_BACKEND`, `SMTP_*`, `EMAIL_FROM_ADDRESS` | `console` sends nothing; `smtp` emails verification and password-reset links |
| `ALLOWED_EMAIL_DOMAINS` | Optional comma-separated list (e.g. `uni.edu,lab.org`); when set, only those addresses can sign up |
| `SESSION_REMEMBER_DAYS` | How long "Keep me signed in" lasts (default 30). Other sign-ins end when the browser closes |
| `AVATAR_MAX_UPLOAD_BYTES` | Largest profile picture accepted before resizing (default 5 MB) |
| `DOI_LOOKUP_ENABLED` | Optional Crossref metadata lookup |
| `FRONTEND_DIST_DIR` | Folder with the built web app (`frontend/dist`). When set, the API serves it too, so one process is the whole site |
| `SQLITE_JOURNAL_MODE` | `WAL` (default) or `DELETE` for hosts whose disks are network file systems |
| `TRUST_PROXY_HEADERS` | Only with `backend/wsgi.py`: take the visitor's address from the host's proxy headers |

Administration without email (list users, reset a password, mark an email verified):

```bash
cd backend
python scripts/admin.py list-users
python scripts/admin.py reset-password someone@university.edu
python scripts/admin.py verify-email someone@university.edu
```

## 4. Deploy

Two free ways to put ResearchFlow online:

| | Guide | Needs a card | Good for |
| --- | --- | --- | --- |
| **PythonAnywhere** | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | No | Small teams; 512 MB of disk; one command to update |
| **Your own server** (Oracle Cloud Always Free or any Ubuntu VPS) | [docs/DEPLOYMENT_SERVER.md](docs/DEPLOYMENT_SERVER.md) | Yes, to verify the account | More space, automatic deploys, nightly backups |

In both, GitHub runs the tests first. For PythonAnywhere the **Publish** workflow builds a ready-to-run copy on the `deploy` branch, where one process serves the web app and the API together (`FRONTEND_DIST_DIR`).

## 5. Test

```bash
cd backend
python -m pytest -q tests          # security workflows, saving and conflicts, versions, export/import, review, bibliography, files

cd ../frontend
npm run typecheck
npm run lint
npm run test                       # comment anchors, LaTeX structure check, offsets, LaTeX helpers, routing
npm run build
```

## 6. Features

- **Navigation**: sidebar with Overview, My Projects, Shared With Me, Papers & Drafts, Files & Datasets, Code & Results, Literature & References, Experiments, Tasks, Notifications and Account & Settings. Global search covers projects (including by member name), papers, source files, files, references, tasks, experiments, code and people.
- **Writing workspace**: file tree, outline and search on the left; the LaTeX editor in the middle; Tools, Review and History on the right. Panels are resizable and collapsible, layout is saved per user, and phones get a single-panel layout.
- **Editor**: CodeMirror 6 with LaTeX highlighting, line numbers, folding, find and replace, multi-cursor, snippets, autocomplete for commands, `\cite{}` keys, `\ref{}` labels and file paths, and a structure check for unbalanced braces and environments.
- **Saving**: autosave after a short pause, Ctrl/⌘+S, Cancel changes, clear *Saving / Saved / Save failed* states, and a warning before leaving with unsaved edits. If a co-author saved a newer version, you compare and decide; nothing is overwritten silently.
- **Versions**: automatic and named snapshots, compare any two versions or a version against the current text, and restore that can itself be undone.
- **LaTeX export**: complete project ZIP (folders, `.bib`, figures and a README), full paper as one `.tex`, any section from the outline (copy or download), the selection, the current file, the bibliography and the figures. A check reports missing files, figures, citations and labels.
- **Import**: LaTeX project ZIP (structure preserved), `.tex`, `.bib`, Markdown and Word (with conversion notes). Originals are kept under Files & data › Manuscripts. PDFs are stored as documents; ResearchFlow does not try to turn a PDF back into LaTeX.
- **Review**: comments on a selection or the whole paper, replies, @mentions, resolve and reopen. Reviewers suggest edits that editors accept or reject.
- **References**: BibTeX import with duplicate detection, export that keeps custom fields, cite-key rename that asks before updating citations, notes, adding project references to a paper's `.bib`, and optional DOI lookup.
- **Files & data**: drag-and-drop or multi-select uploads with progress, pause, retry and cancel. Folders with breadcrumbs, search, filters by type, uploader and date, sorting, grid and list views, multi-select move/download/trash, version history, previews (images, PDFs, text) and recoverable trash.
- **Code & results**: side-by-side or unified code comparison with syntax highlighting, and result comparison that aligns metrics and warns when datasets differ. Uploaded code is never executed.
- **Team**: invitations limited to the inviter's role rank, owner-only role changes and removals, explicit ownership transfer, owner-controlled publication status, and "Signal interest" requests that never grant access on their own.
- **Account & Settings**: profile, password change, signed-in sessions, notification categories, Light, Dark and System themes with an accent color, and keyboard shortcuts.

## 7. Email and production checklist

- `EMAIL_BACKEND=console` sends nothing; in development the codes are returned to the browser so you can test. In production use `smtp` with `SMTP_*`, or reset passwords with `scripts/admin.py`.
- Production: `APP_ENV=production`, `SESSION_COOKIE_SECURE=true`, an HTTPS `FRONTEND_ORIGIN`, strong secrets and `DATABASE_PATH` on persistent storage. The backend refuses to start otherwise. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## 8. Safe Git practices

`.env`, `backend/.env`, databases, uploads, build artifacts and `node_modules/` are git-ignored. Before committing:

```bash
python scripts/security_audit.py
git status
git diff --staged
```

## 9. Known limitations

- Two people cannot edit the same file at the same moment; the second save is stopped with a compare-and-choose step.
- SQLite only at runtime; moving to PostgreSQL means replacing the database layer.
- No PDF compilation, and therefore no PDF preview of the paper itself.
- No malware scanning integration. Uploads are validated by extension and magic bytes, and nothing uploaded is executed.
- `ruff check` reports pre-existing style findings across the codebase (line length, typing aliases); Pyflakes checks are clean.
