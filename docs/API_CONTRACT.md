# ResearchFlow API Contract (`/api/v1`)

All endpoints are prefixed with `/api/v1` and return JSON unless streaming a file download or plain-text BibTeX/RIS export.

## 1. Authentication, Session & CSRF Strategy

- **Session Cookie**: `POST /api/v1/auth/login` sets an `HttpOnly`, `SameSite=Lax` (`Secure=true` in staging/production) cookie named `rf_session`.
- **Database Storage**: Raw session tokens, email verification tokens, and password reset tokens are never stored in plaintext; the backend hashes tokens using `HMAC-SHA256` with `TOKEN_HASH_PEPPER`.
- **CSRF Protection**: State-changing requests (`POST`, `PATCH`, `PUT`, `DELETE`) on authenticated endpoints require the `X-CSRF-Token` header containing the session-bound HMAC token returned by `/api/v1/auth/login` and `/api/v1/auth/me`.

## 2. Role Permission Matrix

| Operation / Resource | Owner | Editor | Reviewer | Viewer |
| :--- | :---: | :---: | :---: | :---: |
| View authorized project, tasks, documents, files, experiments | Allowed | Allowed | Allowed | Allowed |
| Post comments & review manuscripts (`DOC_REVIEW`, `COMMENT_WRITE`) | Allowed | Allowed | Allowed | Denied (`403`) |
| Create/update/delete tasks, documents, references, files, experiments | Allowed | Allowed | Denied (`403`) | Denied (`403`) |
| Invite collaborators, cancel invitations, change roles, remove members | Allowed | Denied (`403`) | Denied (`403`) | Denied (`403`) |
| Transfer ownership, archive, or delete project | Allowed | Denied (`403`) | Denied (`403`) | Denied (`403`) |

## 3. Core Endpoint Reference

### Authentication (`/api/v1/auth`)
- `GET /api/v1/auth/password-policy` — The password rules the server enforces (`min_length`, `max_length`, `rules[]`), shown live on the sign-up form.
- `POST /api/v1/auth/register/check-email` — Step 1 of sign-up: validates `email` (`422`), the optional domain allowlist (`403`) and whether it is taken (`409`). Creates and reserves nothing. Rate limited.
- `GET /api/v1/auth/username-available?username=` — `{ username, available, reason }`. Rate limited.
- `POST /api/v1/auth/register` — Register with `full_name`, `username`, `email`, `password`. Returns `201 Created`. `409` names whether the email or the username is taken.
- `POST /api/v1/auth/resend-verification` — New verification code for an unverified address; older codes stop working. Same response whether or not the address has an account.
- `POST /api/v1/auth/verify-email` — Consume one-time `token` to mark `email_verified = true`.
- `POST /api/v1/auth/login` — Authenticate with `identifier` (username or email), `password` and optional `remember_me`. Without it the cookie ends with the browser session (server lifetime `SESSION_TTL_MINUTES`); with it the cookie and session last `SESSION_REMEMBER_DAYS`. Returns `{ user, csrf_token, expires_at }`; `user.avatar_version` is empty when there is no picture.
- `GET /api/v1/auth/dev-demo` — Development only (`APP_ENV=development` and the demo account seeded): the demo credentials for the login-page hint. `404` everywhere else.
- `POST /api/v1/auth/logout` — Revoke current session and clear cookie.
- `GET /api/v1/auth/me` — Inspect current authenticated user and refresh `csrf_token`.
- `POST /api/v1/auth/forgot-password` — Issue one-time password reset token (generic `200 OK` response prevents account enumeration).
- `POST /api/v1/auth/reset-password` — Reset password using one-time `token` and revoke all active sessions for the user.

### Users (`/api/v1/users`)
- `PUT /api/v1/users/me/avatar` — Multipart `file` (JPEG, PNG or WebP, up to `AVATAR_MAX_UPLOAD_BYTES`). The image is decoded, EXIF-rotated, center-cropped, resized to 256×256 and re-encoded as WebP; the original is not stored. Returns `{ avatar_version }`.
- `DELETE /api/v1/users/me/avatar` — Remove the picture.
- `GET /api/v1/users/avatars?ids=usr_…,usr_…` — Batch lookup `{ avatars: { id: version } }` (users without a picture are omitted). Signed-in users only.
- `GET /api/v1/users/{id}/avatar?v=<version>` — The WebP image (`Cache-Control: private, immutable`; the version makes URLs change when the picture does). Signed-in users only.
- `GET /api/v1/users/me` — Retrieve current user and academic profile (`institution`, `department`, `orcid_id`, `bio`, `research_interests`).
- `PATCH /api/v1/users/me` — Update profile fields.
- `PATCH /api/v1/users/me/password` — Change password (requires `current_password` verification; revokes other sessions).
- `GET /api/v1/users/search?q=<query>` — Rate-limited collaborator lookup by username, email, or name.

### Projects & Collaboration (`/api/v1/projects`, `/api/v1/invitations`)
- `GET /api/v1/projects` — List projects where the authenticated user is an active member.
- `POST /api/v1/projects` — Create a project and assign creator as `owner`.
- `GET /api/v1/projects/{project_id}` — Fetch project metadata, quota usage, and caller's role.
- `PATCH /api/v1/projects/{project_id}` — Update project metadata (`Editor`/`Owner`) or visibility/status (`Owner`).
- `DELETE /api/v1/projects/{project_id}` — Delete project and purge associated private storage blobs (`Owner` only).
- `GET /api/v1/projects/{project_id}/members` — List active members and pending invitations.
- `POST /api/v1/projects/{project_id}/invitations` — Invite a registered user as `editor`, `reviewer`, or `viewer` (`Owner` only).
- `PATCH /api/v1/invitations/{invitation_id}` — Invitee accepts (`accept`) or declines (`reject`); owner cancels (`cancel`).
- `PATCH /api/v1/projects/{project_id}/members/{user_id}` — Update member role (`Owner` only).
- `DELETE /api/v1/projects/{project_id}/members/{user_id}` — Remove member and immediately revoke resource access (`Owner` only).
- `POST /api/v1/projects/{project_id}/transfer-ownership` — Atomically transfer ownership to an existing member (`Owner` only).

### Workspace Resources
- **Tasks**: `GET / POST /api/v1/projects/{project_id}/tasks`, `PATCH / DELETE /api/v1/tasks/{task_id}`
- **Documents & Versioning**:
  - `GET / POST /api/v1/projects/{project_id}/documents`
  - `GET / PATCH /api/v1/documents/{document_id}` (Requires `base_version`; returns `409 Conflict` if `base_version != current_version`)
  - `GET /api/v1/documents/{document_id}/versions`
- **Research Library**:
  - `GET / POST /api/v1/projects/{project_id}/references`
  - `GET /api/v1/projects/{project_id}/references/export?format=bibtex|ris`
- **Private Files & Datasets**:
  - `POST /api/v1/projects/{project_id}/files` (Multipart upload; validates extension, magic bytes, size limit, and project storage quota)
  - `GET /api/v1/projects/{project_id}/files`
  - `POST /api/v1/files/{file_id}/download` (Streams file with `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`)
  - `DELETE /api/v1/files/{file_id}`
- **Experiments, Comments, Activity, Notifications & Search**:
  - `GET / POST /api/v1/projects/{project_id}/experiments`
  - `POST /api/v1/projects/{project_id}/comments`
  - `GET /api/v1/projects/{project_id}/activity`
  - `GET /api/v1/notifications`, `PATCH /api/v1/notifications/{notification_id}`
  - `GET /api/v1/search?q=<query>`

## 4. Papers, Saving, Export & Review

All routes resolve project membership from the resource id (paper, file, version, comment, suggestion or build). Ids belonging to other projects behave as not found.

### Papers (`documents` with `doc_kind = 'latex'`)
- `GET /projects/{pid}/manuscripts?include_deleted=` lists papers with status, review state and last build.
- `POST /projects/{pid}/manuscripts` takes `{title, template: blank|article|ieee|structured, compiler}` (editor+). `compiler` is the TeX engine named in the export README; nothing is compiled.
- `POST /projects/{pid}/manuscripts/import` takes a multipart `file` (.zip LaTeX project, .tex, .bib, .md, .docx) and returns `warnings` and `skipped`.
- `GET /manuscripts/{id}` returns the paper plus its file tree, with live editor counts.
- `PATCH /manuscripts/{id}` updates `title`, `main_file_path`, `compiler`, `is_pinned`, `linked_artifacts`. Changing only `review_status` needs reviewer+.
- `PATCH /manuscripts/{id}/status` takes `{status}`. Submitted, Under Review, Revision Requested, Accepted, Published and Rejected are owner-only.
- `DELETE /manuscripts/{id}` moves the paper to Trash (the project is unaffected); `POST /manuscripts/{id}/restore`; `POST /manuscripts/{id}/copy` makes a revision copy.

### Source files
- `POST /manuscripts/{id}/files` takes `{path, kind: text|folder, content}`; `POST /manuscripts/{id}/files/upload` takes multipart `files[]`, `folder`, `replace`.
- `GET /manuscript-files/{fid}` (text files include the current `content`); `GET /manuscript-files/{fid}/raw?inline=`.
- `PATCH /manuscript-files/{fid}` renames or moves `{path}`. Folders move their children. Stale references are reported; source is never rewritten.
- `DELETE /manuscript-files/{fid}` moves to Trash (the main file is protected); `GET /manuscripts/{id}/trash`; `POST /manuscript-files/{fid}/restore`.

### Versions
- `GET /manuscript-files/{fid}/versions`; `POST /manuscript-files/{fid}/versions` with `{summary}`; `GET /file-versions/{vid}`.
- `POST /file-versions/{vid}/restore` snapshots the current text first, writes the old text as a new revision, and records a `restore` version.
- `GET /manuscript-files/{fid}/compare?left={vid}&right={vid|current}`.

### Saving
- `GET /manuscript-files/{fid}` returns `content`, `revision` and `updated_by_name` for text files.
- `PUT /manuscript-files/{fid}/content` with `{content, base_revision}` (editor+) saves and returns `{revision, changed, version_created, updated_at}`. If someone saved a newer revision first, it returns `409` with `{message, current_revision, current_content, updated_by_name, updated_at}` and nothing is overwritten.

### Analysis & export
- `GET /manuscript-files/{fid}/outline` lists sections, abstract, figures, tables and equations with `start`/`end` offsets (code points) and line numbers.
- `GET /manuscript-files/{fid}/section?start=&end=&download=` returns one section's LaTeX verbatim (`422` if the outline is stale).
- `GET /manuscripts/{id}/index` returns labels, cite keys (from the paper's `.bib` files and the project library) and file paths for completion.
- `GET /manuscripts/{id}/dependencies` reports missing inputs, figures and bibliographies, plus undefined citations and references.
- `GET /manuscripts/{id}/export/project.zip` (header `X-Export-Missing`), `/export/paper.tex` (flattened, header `X-Export-Warnings`), `/export/bibliography.bib`, `/export/assets.zip`.

### Comments & suggestions
- `GET|POST /manuscripts/{id}/comments` for threads with replies, anchors and mentions; `PATCH /doc-comments/{cid}` with `{body}` or `{status: open|resolved}`; `DELETE /doc-comments/{cid}` (author or owner).
- `GET|POST /manuscripts/{id}/suggestions` (reviewer+); `POST /doc-suggestions/{sid}/accept` (editor+; returns `409` and marks the suggestion `stale` if the text no longer matches); `POST /doc-suggestions/{sid}/reject`.

### Bibliography
- `GET /projects/{pid}/references?q=&year=` searches by title, author, DOI or cite key.
- `POST /projects/{pid}/references/import-bibtex` with `{bibtex, skip_duplicates}` returns `{created, duplicates, errors}`.
- `GET /projects/{pid}/references/duplicates`; `GET /projects/{pid}/references/library.bib`.
- `GET /references/{rid}/usages`; `PATCH /references/{rid}/bibtex` with `{cite_key, entry_type, fields, rename_in_manuscripts}`. Renaming a key cited in a paper returns `409` with the usages unless `rename_in_manuscripts=true`.
- `POST /manuscripts/{id}/bibliography/sync` with `{path, mode: merge|replace}` is an explicit library-to-.bib write (recorded in version history).
- `POST /references/lookup-doi` with `{doi}` is an optional Crossref lookup (`DOI_LOOKUP_ENABLED`). It returns metadata for review and never saves it.

### Files, uploads & preferences
- `GET /projects/{pid}/files?trash=&limit=&offset=`; `GET /files/{fid}/versions`; `GET /files/{fid}/versions/{n}/content`.
- `PUT /uploads/{uid}/chunks/{i}` is idempotent for chunks already received and rejects gaps (`409 {expected_chunk}`); `GET /uploads/{uid}` reports progress for resuming.
- `GET /invitations` lists the caller's pending invitations.
- `GET|PATCH /users/me/workspace-preferences` stores editor layout preferences.
- `GET /search?q=&category=&limit=&offset=` is a membership-scoped search over projects (by title or member name), papers, source files, files, references, tasks, experiments, artifacts and people.

### Cross-project views (`/api/v1/me`)
- `GET /me/overview` returns counts, recently edited papers, open tasks assigned to the caller and recent activity.
- `GET /me/manuscripts?q=&status=`, `GET /me/files?q=&artifact_type=`, `GET /me/artifacts`, `GET /me/references?q=`, `GET /me/experiments`, `GET /me/tasks?assigned=` list items from projects the caller belongs to. Membership is enforced in every query.
