# ResearchFlow Security Architecture & Threat Mitigations

## 1. Implemented Security Controls

1. **Password Hashing (`backend/app/security/passwords.py`)**:
   - Uses `Argon2id` (`argon2-cffi`, `memory_cost=65536`, `time_cost=2`) when available, with a built-in fallback to Python's memory-hard `hashlib.scrypt` (`N=16384, r=8, p=1, dklen=64`) and constant-time `hmac.compare_digest`.
   - Enforces minimum length (10–128 chars) and character class diversity.
   - Performs dummy verification when an unknown username/email is submitted to reduce timing-based account enumeration.

2. **Session & Token Security (`backend/app/security/tokens.py`)**:
   - Sessions use `HttpOnly`, `SameSite=Lax`, and (in staging/production) `Secure` cookies.
   - Session tokens, email verification tokens, and password reset tokens are hashed with `HMAC-SHA256` + `TOKEN_HASH_PEPPER` before database persistence.
   - Password reset and password change automatically revoke existing sessions.
   - Email verification and password reset tokens enforce strict expiration and one-time use (`used_at`).

3. **CSRF, CORS & Browser Headers (`backend/app/main.py`)**:
   - State-changing requests (`POST`, `PATCH`, `PUT`, `DELETE`) require a valid session-bound `X-CSRF-Token` header.
   - CORS is restricted to explicit `FRONTEND_ORIGIN` values (wildcard `*` is rejected by startup validation).
   - Every response sets `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, and `Content-Security-Policy`.

4. **Server-Enforced Authorization & IDOR Prevention (`backend/app/permissions/rbac.py`)**:
   - Every endpoint resolves project membership on the server and checks `ROLE_PERMISSION_MATRIX` (`owner`, `editor`, `reviewer`, `viewer`).
   - Pending invitations never grant access until explicitly accepted by the invited user.
   - Cross-project IDOR attempts return `403 Forbidden` and record an `UNAUTHORIZED_PROJECT_ACCESS` audit event.

5. **XSS & Rich-Text Sanitization (`backend/app/security/sanitizer.py`)**:
   - All rich-text manuscript HTML is parsed and sanitized on the server against a strict tag/attribute allowlist (`p, h1-h4, ul, ol, li, strong, em, code, pre, blockquote, table, a`), stripping `<script>`, `<iframe>`, `<svg>`, inline `on*` handlers, and `javascript:`/`data:` URLs.

6. **Private File Upload & Storage Isolation (`backend/app/storage/private_storage.py`)**:
   - Files are stored outside any static web root using random UUIDv4 keys (`{project_id}/{uuid4}.bin`).
   - Filenames are sanitized and verified with `Path.resolve().relative_to(root_dir)` to prevent path traversal.
   - File content is inspected for magic bytes (e.g., `%PDF-`, PNG/JPEG signatures) and blocks executable binaries (`MZ`, `ELF`, `#!`) and active HTML/SVG payloads.

7. **Startup Configuration Fail-Safe (`backend/app/core/config.py`)**:
   - When `APP_ENV` is `staging` or `production`, startup fails immediately if placeholder secrets are present, `DEBUG=true`, `SESSION_COOKIE_SECURE=false`, `FRONTEND_ORIGIN` is not `https://`, or a database superuser (`postgres`/`root`) is configured.

8. **SQL injection prevention**:
   - Every query passes user input as bound `?` parameters to `sqlite3`. Dynamic SQL is only ever assembled from fixed text chosen in code (for example, adding an `AND status = ?` clause); user values never become part of the SQL string. Sort orders and column names come from fixed allowlists.
   - Search uses `LIKE ? ESCAPE '\'` with `%`, `_` and `\` escaped, so wildcards in a search term match literally.
   - CI runs `ruff --select S608,…` (SQL built from strings, `exec`/`eval`, subprocess/shell calls) as a required step; the few fixed-template queries are annotated with the reason.
   - `backend/tests/test_sql_injection.py` sends classic payloads (`' OR '1'='1`, `UNION SELECT`, stacked `; DROP TABLE`, comment truncation, wildcard abuse) to login, global search, project/reference/`/me` filters, user search, IDs in paths and stored text fields, and asserts that nothing leaks, nothing is dropped and payloads are stored as plain text.

9. **Profile pictures (`backend/app/storage/avatars.py`)**:
   - Only JPEG, PNG and WebP are accepted, judged by decoding the file with Pillow, never by its name or MIME type. Images over 40 megapixels are rejected before decoding (decompression bombs), and uploads are capped by `AVATAR_MAX_UPLOAD_BYTES`.
   - The upload is rotated, cropped to a square, resized to 256×256 and re-encoded as WebP. The original is never stored, so metadata (GPS tags) and anything hidden in the file are dropped.
   - Users can change only their own picture (CSRF-protected `PUT`/`DELETE` on `/users/me/avatar`). Pictures are served only to signed-in users, from private storage, with `Content-Security-Policy: default-src 'none'; sandbox`.

10. **Sign-up and the demo account**:
   - Email is validated on the server (length limits, dot-atom local part, hostname labels, alphabetic TLD) and optionally limited to `ALLOWED_EMAIL_DOMAINS`. The email-first check creates nothing. Like registration itself, it says whether an address is taken, so it is rate limited. Sign-in, forgot-password and resend-verification give the same answer whether or not an account exists.
   - Verification and reset links carry the code in the URL fragment (`#/auth/…`), which browsers never send to servers or proxies. The page removes it from the address bar right away.
   - The demo account (`backend/app/core/demo.py`) can only be created when `APP_ENV` is `development` or `testing`. The seeding script and `ensure_demo_account` both refuse otherwise, and `GET /auth/dev-demo` answers 404 outside development. Production builds of the web app do not contain the demo hint at all.

11. **Editing integrity (`backend/app/latex/textstore.py`)**:
   - Every save names the revision it was based on. A save against an older revision is rejected with `409` and the newer text, so concurrent contributors can never silently overwrite each other. Server-side rewrites go through the same check.
   - Only roles with `doc:write` can save; reviewers propose changes as suggestions that an editor must accept.

12. **No code or document execution**: ResearchFlow does not compile LaTeX or run uploaded code. Source is stored and exported as text, so there is no build sandbox to escape.

13. **Archives and imports (`backend/app/latex/importer.py`)**:
    - ZIP imports reject absolute paths, `..` traversal, drive letters and symlinks. They also bound entry count, total uncompressed size and per-entry compression ratio (zip-bomb defense), and drop build artifacts and hidden files.
    - DOCX parsing rejects DTDs and entities (no XXE). Uploaded code and documents are never executed.
    - Manuscript paths are validated against a strict allowlist and are always relative to the paper root.

14. **Exports**: archives contain only the paper's own files at their relative paths, plus a generated README. Database records, user data, credentials and other projects' files are never included.

## 2. Secret Rotation & Incident Response Procedure

If a credential or signing key is ever suspected of exposure:
1. **Revoke & Rotate Immediately**: Generate new 64-character random values (`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`) for `SESSION_SECRET_KEY`, `CSRF_SECRET_KEY`, `TOKEN_HASH_PEPPER` in `/etc/researchflow/backend.env`, then restart the service.
2. **Invalidate Active Sessions**: Execute `UPDATE sessions SET revoked = 1;` and `DELETE FROM password_reset_tokens;` in the SQLite database (`sqlite3 /var/lib/researchflow/researchflow.sqlite3`).
3. **Purge Git History if Committed**: Use `git filter-repo` or BFG Repo-Cleaner to remove the secret from all historical commits and force-push cleaned history.
4. **Audit Access Logs**: Inspect `audit_events` for anomalous `LOGIN_SUCCESS`, `FILE_DOWNLOADED`, or `UNAUTHORIZED_PROJECT_ACCESS` entries during the exposure window.

## 3. Residual Risks & Production Deployment Responsibilities

- **Proxy headers**: `TRUST_PROXY_HEADERS` (used only by `backend/wsgi.py`) takes the visitor's address from `X-Real-IP`, or the last entry of `X-Forwarded-For`. Turn it on only where every request passes through the host's own proxy, as on PythonAnywhere; otherwise visitors could forge their address and dodge the login rate limit.
- **Single-service hosting**: with `FRONTEND_DIST_DIR` the API also serves the built web app. Requested paths are resolved and must stay inside that folder, and those pages carry the same strict Content Security Policy the Caddy setup uses.
- **Rate Limiting in Multi-Worker Deployments**: The default sliding-window rate limiter stores buckets in process memory; run the API with a single worker (as the service created by `deploy/server_setup.sh` does) or enforce rate limits at the reverse proxy.
- **Antivirus / Malware Scanning**: While magic-byte and extension checks block executables and active HTML/SVG uploads, high-assurance deployments should integrate ClamAV or object-storage malware scanning on uploaded archives.
