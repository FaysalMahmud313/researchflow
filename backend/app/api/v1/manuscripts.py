"""Manuscripts: LaTeX source projects, file trees, saving, versions, export/import, review.

A manuscript is a row in `documents` with `doc_kind = 'latex'`; there is no second
representation of a paper. Text files are stored in `manuscript_files.text_content` with a
`revision` counter: a save names the revision it started from and is rejected if someone
else saved in between, so newer work is never silently overwritten.

ResearchFlow generates and exports LaTeX source; it does not compile PDFs.
"""
import difflib
import hashlib
import json
import re
import uuid
from pathlib import PurePosixPath
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.api.v1.context import ApiContext, utc_now_iso
from app.latex.analysis import analyze_dependencies, build_outline, extract_range, find_labels
from app.latex.bibtex import parse_bibtex
from app.latex.export import (
    build_assets_zip,
    build_project_zip,
    build_readme,
    content_disposition,
    flatten_latex,
    safe_download_name,
)
from app.latex.importer import (
    ImportedFile,
    ImportErrorWithReason,
    decode_text,
    docx_to_latex,
    import_zip,
    markdown_to_latex,
)
from app.latex.paths import (
    ManuscriptPathError,
    is_text_path,
    normalize_manuscript_path,
    parent_folders,
)
from app.latex.templates import render_template
from app.latex.textstore import (
    RevisionConflict,
    create_version,
    current_state,
    get_text,
    write_text,
)
from app.permissions.rbac import Permission
from app.schemas.manuscript_schemas import (
    OWNER_ONLY_MANUSCRIPT_STATUSES,
    DocCommentCreateRequest,
    DocCommentUpdateRequest,
    FileContentSaveRequest,
    ManuscriptCopyRequest,
    ManuscriptCreateRequest,
    ManuscriptFileCreateRequest,
    ManuscriptFileUpdateRequest,
    ManuscriptStatusRequest,
    ManuscriptUpdateRequest,
    SuggestionCreateRequest,
    VersionCreateRequest,
    WorkspacePrefsRequest,
)
from app.security.sanitizer import sanitize_plain_text
from app.storage.private_storage import StorageSecurityError

_MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_.-]{3,32})")
FILE_COLUMNS = (
    "id, document_id, project_id, path, file_kind, storage_key, size_bytes, media_type, checksum_sha256, "
    "is_deleted, deleted_at, created_by_id, updated_by_id, created_at, updated_at, revision"
)
MAX_TEXT_FILE_BYTES = 4_000_000


def build_manuscripts_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    settings = ctx.settings
    auth = ctx.get_current_session_and_user

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def norm_path(raw: str) -> str:
        try:
            return normalize_manuscript_path(raw)
        except ManuscriptPathError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def load_manuscript(conn: Any, document_id: str, uid: str, perm: Permission, include_deleted: bool = False) -> Dict[str, Any]:
        doc = ctx.load_document_for(conn, document_id, uid, perm, include_deleted=include_deleted)
        if doc["doc_kind"] != "latex":
            raise HTTPException(status_code=404, detail="Manuscript not found.")
        return doc

    def load_file(conn: Any, file_id: str, uid: str, perm: Permission, include_deleted: bool = False) -> tuple[Dict[str, Any], Dict[str, Any]]:
        f = conn.execute(f"SELECT {FILE_COLUMNS} FROM manuscript_files WHERE id = ?", (file_id,)).fetchone()  # noqa: S608
        if not f or (f["is_deleted"] and not include_deleted):
            raise HTTPException(status_code=404, detail="File not found.")
        doc = load_manuscript(conn, f["document_id"], uid, perm)
        return dict(f), doc

    def active_files(conn: Any, document_id: str) -> list[Dict[str, Any]]:
        rows = conn.execute(
            f"SELECT {FILE_COLUMNS} FROM manuscript_files WHERE document_id = ? AND is_deleted = 0 ORDER BY path",  # noqa: S608
            (document_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def path_taken(conn: Any, document_id: str, path: str, exclude_id: str = "") -> bool:
        row = conn.execute(
            "SELECT 1 FROM manuscript_files WHERE document_id = ? AND is_deleted = 0 AND id != ? "
            "AND (path = ? OR (file_kind != 'folder' AND ? LIKE path || '/%'))",
            (document_id, exclude_id, path, path),
        ).fetchone()
        return row is not None

    def insert_folder_chain(conn: Any, doc: Dict[str, Any], path: str, uid: str) -> None:
        now = utc_now_iso()
        for folder in parent_folders(path):
            exists = conn.execute(
                "SELECT file_kind FROM manuscript_files WHERE document_id = ? AND path = ? AND is_deleted = 0",
                (doc["id"], folder),
            ).fetchone()
            if exists and exists["file_kind"] != "folder":
                raise HTTPException(status_code=409, detail=f"'{folder}' is a file, not a folder.")
            if not exists:
                conn.execute(
                    "INSERT INTO manuscript_files (id, document_id, project_id, path, file_kind, created_by_id, updated_by_id, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'folder', ?, ?, ?, ?)",
                    (f"mf_{uuid.uuid4().hex[:16]}", doc["id"], doc["project_id"], folder, uid, uid, now, now),
                )

    def insert_text_file(conn: Any, doc: Dict[str, Any], path: str, text: str, uid: str, version_kind: str = "initial") -> str:
        if path_taken(conn, doc["id"], path):
            raise HTTPException(status_code=409, detail=f"A file or folder named '{path}' already exists.")
        insert_folder_chain(conn, doc, path, uid)
        now = utc_now_iso()
        fid = f"mf_{uuid.uuid4().hex[:16]}"
        conn.execute(
            "INSERT INTO manuscript_files (id, document_id, project_id, path, file_kind, text_content, size_bytes, "
            "media_type, created_by_id, updated_by_id, created_at, updated_at) VALUES (?, ?, ?, ?, 'text', ?, ?, ?, ?, ?, ?, ?)",
            (fid, doc["id"], doc["project_id"], path, text, len(text.encode("utf-8")),
             "application/x-tex" if path.endswith(".tex") else "text/plain", uid, uid, now, now),
        )
        conn.execute(
            "INSERT INTO file_text_versions (id, file_id, document_id, version_number, content, content_sha256, summary, version_kind, author_id, created_at) "
            "VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, fid, doc["id"], text, hashlib.sha256(text.encode("utf-8")).hexdigest(),
             "Initial version" if version_kind == "initial" else "Imported", version_kind, uid, now),
        )
        return fid

    def insert_binary_file(conn: Any, doc: Dict[str, Any], path: str, data: bytes, uid: str, replace: bool = False) -> str:
        proj = conn.execute("SELECT storage_used_bytes FROM projects WHERE id = ?", (doc["project_id"],)).fetchone()
        if int(proj["storage_used_bytes"]) + len(data) > settings.project_storage_quota_bytes:
            raise HTTPException(status_code=413, detail="Project storage quota exceeded.")
        try:
            stored = ctx.storage.store_bytes(doc["project_id"], PurePosixPath(path).name, data)
        except StorageSecurityError as exc:
            raise HTTPException(status_code=400, detail=f"{path}: {exc}") from exc
        now = utc_now_iso()
        existing = conn.execute(
            "SELECT id, file_kind, storage_key, size_bytes FROM manuscript_files WHERE document_id = ? AND path = ? AND is_deleted = 0",
            (doc["id"], path),
        ).fetchone()
        if existing:
            if not replace or existing["file_kind"] != "binary":
                ctx.storage.delete_key(str(stored["storage_key"]))
                raise HTTPException(status_code=409, detail=f"A file or folder named '{path}' already exists.")
            conn.execute(
                "UPDATE manuscript_files SET storage_key = ?, size_bytes = ?, media_type = ?, checksum_sha256 = ?, updated_by_id = ?, updated_at = ? WHERE id = ?",
                (stored["storage_key"], stored["size_bytes"], stored["media_type"], stored["checksum_sha256"], uid, now, existing["id"]),
            )
            conn.execute(
                "UPDATE projects SET storage_used_bytes = MAX(0, storage_used_bytes - ?) + ? WHERE id = ?",
                (existing["size_bytes"], stored["size_bytes"], doc["project_id"]),
            )
            ctx.storage.delete_key(existing["storage_key"])
            return str(existing["id"])
        if path_taken(conn, doc["id"], path):
            ctx.storage.delete_key(str(stored["storage_key"]))
            raise HTTPException(status_code=409, detail=f"A file or folder named '{path}' already exists.")
        insert_folder_chain(conn, doc, path, uid)
        fid = f"mf_{uuid.uuid4().hex[:16]}"
        conn.execute(
            "INSERT INTO manuscript_files (id, document_id, project_id, path, file_kind, storage_key, size_bytes, media_type, "
            "checksum_sha256, created_by_id, updated_by_id, created_at, updated_at) VALUES (?, ?, ?, ?, 'binary', ?, ?, ?, ?, ?, ?, ?, ?)",
            (fid, doc["id"], doc["project_id"], path, stored["storage_key"], stored["size_bytes"], stored["media_type"],
             stored["checksum_sha256"], uid, uid, now, now),
        )
        conn.execute(
            "UPDATE projects SET storage_used_bytes = storage_used_bytes + ? WHERE id = ?", (stored["size_bytes"], doc["project_id"])
        )
        return fid

    def snapshot_texts(conn: Any, files: list[Dict[str, Any]]) -> tuple[dict[str, str], dict[str, str], list[str]]:
        texts: dict[str, str] = {}
        binaries: dict[str, str] = {}
        folders: list[str] = []
        for f in files:
            if f["file_kind"] == "text":
                texts[f["path"]] = get_text(conn, f["id"])
            elif f["file_kind"] == "binary":
                binaries[f["path"]] = f["storage_key"]
            else:
                folders.append(f["path"])
        return texts, binaries, folders

    def store_original_upload(conn: Any, project_id: str, name: str, data: bytes, uid: str, doc_id: str) -> str:
        """Keep an uploaded manuscript exactly as received, as an ordinary project file."""
        proj = conn.execute("SELECT storage_used_bytes FROM projects WHERE id = ?", (project_id,)).fetchone()
        if int(proj["storage_used_bytes"]) + len(data) > settings.project_storage_quota_bytes:
            raise HTTPException(status_code=413, detail="Project storage quota exceeded.")
        try:
            stored = ctx.storage.store_bytes(project_id, name, data)
        except StorageSecurityError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        now = utc_now_iso()
        file_id = f"fil_{uuid.uuid4().hex[:14]}"
        conn.execute(
            "INSERT INTO datasets_files (id, project_id, folder, original_name, storage_key, size_bytes, media_type, checksum_sha256, "
            "artifact_type, description, current_version, linked_entity_type, linked_entity_id, last_editor_name, uploaded_by_id, "
            "created_at, updated_at) VALUES (?, ?, '/Manuscripts', ?, ?, ?, ?, ?, 'manuscript', 'Original upload', 1, ?, ?, '', ?, ?, ?)",
            (file_id, project_id, stored["original_name"], stored["storage_key"], stored["size_bytes"], stored["media_type"],
             stored["checksum_sha256"], "document" if doc_id else "", doc_id, uid, now, now),
        )
        conn.execute(
            "INSERT INTO file_versions (id, file_id, version_number, storage_key, size_bytes, checksum_sha256, uploaded_by_id, created_at) "
            "VALUES (?, ?, 1, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, file_id, stored["storage_key"], stored["size_bytes"], stored["checksum_sha256"], uid, now),
        )
        conn.execute("UPDATE projects SET storage_used_bytes = storage_used_bytes + ? WHERE id = ?", (stored["size_bytes"], project_id))
        return file_id

    def library_keys(conn: Any, project_id: str) -> list[str]:
        return [
            r["cite_key"]
            for r in conn.execute(
                "SELECT cite_key FROM literature_references WHERE project_id = ? AND cite_key != ''", (project_id,)
            ).fetchall()
        ]

    def serialize_manuscript(doc: Dict[str, Any], role: str) -> Dict[str, Any]:
        return {
            "id": doc["id"],
            "project_id": doc["project_id"],
            "title": doc["title"],
            "status": doc["publication_status"],
            "review_status": doc["review_status"],
            "main_file_path": doc["main_file_path"],
            "compiler": doc["compiler"],
            "is_pinned": bool(doc["is_pinned"]),
            "is_deleted": bool(doc["is_deleted"]),
            "deleted_at": doc["deleted_at"],
            "linked_artifacts": json.loads(doc["linked_artifacts_json"] or "[]"),
            "last_editor_name": doc.get("last_editor_name", ""),
            "created_at": doc["created_at"],
            "updated_at": doc["updated_at"],
            "my_role": role,
        }

    def touch_document(conn: Any, doc: Dict[str, Any], uid: str, name: str) -> None:
        now = utc_now_iso()
        conn.execute(
            "UPDATE documents SET updated_at = ?, updated_by_id = ?, last_editor_name = ? WHERE id = ?", (now, uid, name, doc["id"])
        )

    # ------------------------------------------------------------------
    # Manuscripts
    # ------------------------------------------------------------------
    @router.get("/projects/{project_id}/manuscripts")
    def list_manuscripts(
        project_id: str,
        include_deleted: bool = Query(default=False),
        session: Dict[str, Any] = Depends(auth),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            role = ctx.require_project_permission(conn, project_id, uid, Permission.PROJECT_VIEW)
            rows = conn.execute(
                "SELECT * FROM documents WHERE project_id = ? AND doc_kind = 'latex' AND (is_deleted = 0 OR ?) "
                "ORDER BY is_deleted, is_pinned DESC, updated_at DESC",
                (project_id, int(include_deleted)),
            ).fetchall()
            return {"manuscripts": [serialize_manuscript(dict(r), role) for r in rows]}

    @router.post("/projects/{project_id}/manuscripts", status_code=201)
    def create_manuscript(project_id: str, payload: ManuscriptCreateRequest, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        doc_id = f"doc_{uuid.uuid4().hex[:14]}"
        title = sanitize_plain_text(payload.title)
        with ctx.db.transaction() as conn:
            ctx.require_project_permission(conn, project_id, uid, Permission.DOC_WRITE)
            authors = [
                r["full_name"]
                for r in conn.execute(
                    "SELECT u.full_name FROM project_memberships pm JOIN users u ON u.id = pm.user_id "
                    "WHERE pm.project_id = ? AND pm.role IN ('owner','editor') ORDER BY pm.joined_at",
                    (project_id,),
                ).fetchall()
            ]
            files = render_template(payload.template, title, authors)
            conn.execute(
                "INSERT INTO documents (id, project_id, title, content_html, current_version, is_pinned, review_status, publication_status, "
                "doc_kind, main_file_path, compiler, last_editor_name, created_by_id, updated_by_id, created_at, updated_at) "
                "VALUES (?, ?, ?, '', 1, 0, 'draft', 'Working Draft', 'latex', 'main.tex', ?, ?, ?, ?, ?, ?)",
                (doc_id, project_id, title, payload.compiler, session["full_name"], uid, uid, now, now),
            )
            doc = dict(conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone())
            for path, text in files.items():
                insert_text_file(conn, doc, path, text, uid)
            if payload.template == "structured":
                insert_folder_chain(conn, doc, "figures/x", uid)
            ctx.log_activity(conn, project_id, uid, "manuscript.created", "document", doc_id, f"Started paper '{title}'")
            return serialize_manuscript(doc, ctx.get_project_role(conn, project_id, uid) or "")

    @router.post("/projects/{project_id}/manuscripts/import", status_code=201)
    async def import_manuscript(
        project_id: str,
        request: Request,
        file: UploadFile = File(...),
        title: str = Form(""),
        session: Dict[str, Any] = Depends(auth),
    ) -> Dict[str, Any]:
        ctx.enforce_rate_limit(request, "manuscript_import", settings.rate_limit_upload_per_minute, session["user_id"])
        uid = session["user_id"]
        data = await file.read(settings.max_upload_size_bytes + 1)
        if len(data) > settings.max_upload_size_bytes:
            raise HTTPException(status_code=413, detail="Upload exceeds the configured size limit.")
        name = file.filename or "upload"
        suffix = PurePosixPath(name).suffix.lower()
        stem_title = sanitize_plain_text(title.strip() or PurePosixPath(name).stem.replace("_", " ") or "Imported paper")[:200]
        warnings: list[str] = []
        skipped: list[str] = []
        files: list[ImportedFile] = []
        main_file = "main.tex"
        try:
            if suffix == ".zip":
                result = import_zip(data, settings.max_archive_entries, settings.max_archive_uncompressed_bytes)
                files, warnings, skipped = result.files, result.warnings, result.skipped
                main_file = result.main_file or next((f.path for f in files if f.path.endswith(".tex")), "main.tex")
            elif suffix == ".tex":
                files = [ImportedFile("main.tex", "text", text=decode_text(data, name, warnings))]
            elif suffix == ".bib":
                text = decode_text(data, name, warnings)
                files = [
                    ImportedFile("main.tex", "text", text=render_template("article", stem_title, [session["full_name"]])["main.tex"]),
                    ImportedFile("references.bib", "text", text=text),
                ]
            elif suffix in (".md", ".markdown"):
                tex, warnings = markdown_to_latex(decode_text(data, name, warnings), stem_title)
                warnings.insert(0, "Converted from Markdown. Review the generated LaTeX.")
                files = [ImportedFile("main.tex", "text", text=tex)]
            elif suffix == ".docx":
                tex, assets, warnings = docx_to_latex(data, stem_title)
                warnings.insert(0, "Converted from Word. Only headings, paragraphs, bold/italic, simple tables and images are preserved.")
                files = [ImportedFile("main.tex", "text", text=tex), *assets]
            elif suffix == ".pdf":
                # A compiled PDF cannot be turned back into faithful LaTeX; keep it as a document.
                with ctx.db.transaction() as conn:
                    ctx.require_project_permission(conn, project_id, uid, Permission.FILE_UPLOAD)
                    file_id = store_original_upload(conn, project_id, name, data, uid, "")
                    ctx.log_activity(conn, project_id, uid, "file.uploaded", "file", file_id, f"Uploaded manuscript PDF '{name}'")
                return {
                    "stored_only": True,
                    "file_id": file_id,
                    "message": "The PDF was saved under Files & data › Manuscripts. PDFs can't be converted to editable LaTeX.",
                }
            else:
                raise HTTPException(status_code=415, detail="Supported imports: .zip (LaTeX project), .tex, .bib, .md, .docx, .pdf.")
        except ImportErrorWithReason as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not files:
            raise HTTPException(status_code=400, detail="The upload did not contain any usable files.")

        now = utc_now_iso()
        doc_id = f"doc_{uuid.uuid4().hex[:14]}"
        with ctx.db.transaction() as conn:
            ctx.require_project_permission(conn, project_id, uid, Permission.DOC_WRITE)
            conn.execute(
                "INSERT INTO documents (id, project_id, title, content_html, current_version, is_pinned, review_status, publication_status, "
                "doc_kind, main_file_path, compiler, last_editor_name, created_by_id, updated_by_id, created_at, updated_at) "
                "VALUES (?, ?, ?, '', 1, 0, 'draft', 'Working Draft', 'latex', ?, 'pdflatex', ?, ?, ?, ?, ?)",
                (doc_id, project_id, stem_title, main_file, session["full_name"], uid, uid, now, now),
            )
            doc = dict(conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone())
            for f in files:
                if f.kind == "text":
                    insert_text_file(conn, doc, f.path, f.text, uid, version_kind="import")
                else:
                    insert_binary_file(conn, doc, f.path, f.data, uid)
            if any("fontspec" in f.text or "xeCJK" in f.text for f in files if f.kind == "text"):
                conn.execute("UPDATE documents SET compiler = 'xelatex' WHERE id = ?", (doc_id,))
                warnings.append("The source uses fontspec; the export README recommends XeLaTeX.")
            if suffix != ".tex":
                store_original_upload(conn, project_id, name, data, uid, doc_id)
            ctx.log_activity(conn, project_id, uid, "manuscript.imported", "document", doc_id, f"Imported paper '{stem_title}' from {suffix}")
            out = serialize_manuscript(dict(conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()),
                                       ctx.get_project_role(conn, project_id, uid) or "")
        out["warnings"] = warnings
        out["skipped"] = skipped
        return out

    @router.get("/manuscripts/{document_id}")
    def get_manuscript(document_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            doc = load_manuscript(conn, document_id, uid, Permission.PROJECT_VIEW, include_deleted=True)
            role = ctx.get_project_role(conn, doc["project_id"], uid) or ""
            out = serialize_manuscript(doc, role)
            out["files"] = active_files(conn, document_id)
            proj = conn.execute("SELECT title, publication_status FROM projects WHERE id = ?", (doc["project_id"],)).fetchone()
            out["project_title"] = proj["title"]
            out["project_publication_status"] = proj["publication_status"]
            return out

    @router.patch("/manuscripts/{document_id}")
    def update_manuscript(document_id: str, payload: ManuscriptUpdateRequest, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        only_review = payload.review_status is not None and all(
            v is None for v in (payload.title, payload.main_file_path, payload.compiler, payload.is_pinned, payload.linked_artifacts)
        )
        with ctx.db.transaction() as conn:
            doc = load_manuscript(conn, document_id, uid, Permission.DOC_REVIEW if only_review else Permission.DOC_WRITE)
            if payload.title is not None:
                conn.execute("UPDATE documents SET title = ? WHERE id = ?", (sanitize_plain_text(payload.title), document_id))
            if payload.main_file_path is not None:
                path = norm_path(payload.main_file_path)
                ok = conn.execute(
                    "SELECT 1 FROM manuscript_files WHERE document_id = ? AND path = ? AND file_kind = 'text' AND is_deleted = 0",
                    (document_id, path),
                ).fetchone()
                if not ok:
                    raise HTTPException(status_code=422, detail="The main file must be an existing .tex file in this manuscript.")
                conn.execute("UPDATE documents SET main_file_path = ? WHERE id = ?", (path, document_id))
            if payload.compiler is not None:
                conn.execute("UPDATE documents SET compiler = ? WHERE id = ?", (payload.compiler, document_id))
            if payload.is_pinned is not None:
                conn.execute("UPDATE documents SET is_pinned = ? WHERE id = ?", (int(payload.is_pinned), document_id))
            if payload.review_status is not None:
                conn.execute("UPDATE documents SET review_status = ? WHERE id = ?", (payload.review_status, document_id))
                if payload.review_status in ("in_review", "changes_requested", "approved"):
                    label = {"in_review": "ready for review", "changes_requested": "changes requested", "approved": "approved"}[payload.review_status]
                    for m in conn.execute(
                        "SELECT user_id FROM project_memberships WHERE project_id = ? AND user_id != ?", (doc["project_id"], uid)
                    ).fetchall():
                        ctx.notify(conn, m["user_id"], doc["project_id"], "review", "Review update",
                                   f"{session['full_name']} marked '{doc['title']}' as {label}.")
            if payload.linked_artifacts is not None:
                links = []
                tables = {"file": "datasets_files", "artifact": "research_artifacts", "experiment": "experiment_runs",
                          "reference": "literature_references", "task": "tasks"}
                for link in payload.linked_artifacts:
                    table = tables.get(link.get("type", ""))
                    if not table:
                        raise HTTPException(status_code=422, detail=f"Unknown link type '{link.get('type')}'.")
                    row = conn.execute(f"SELECT 1 FROM {table} WHERE id = ? AND project_id = ?", (link.get("id", ""), doc["project_id"])).fetchone()  # noqa: S608
                    if not row:
                        raise HTTPException(status_code=422, detail="Linked item not found in this project.")
                    links.append({"type": link["type"], "id": link["id"]})
                conn.execute("UPDATE documents SET linked_artifacts_json = ? WHERE id = ?", (json.dumps(links), document_id))
            conn.execute(
                "UPDATE documents SET updated_at = ?, updated_by_id = ?, last_editor_name = ? WHERE id = ?",
                (now, uid, session["full_name"], document_id),
            )
            ctx.log_activity(conn, doc["project_id"], uid, "manuscript.updated", "document", document_id, f"Updated paper settings for '{doc['title']}'")
            fresh = dict(conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone())
            return serialize_manuscript(fresh, ctx.get_project_role(conn, doc["project_id"], uid) or "")

    @router.patch("/manuscripts/{document_id}/status")
    def update_manuscript_status(document_id: str, payload: ManuscriptStatusRequest, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        perm = Permission.PUBLICATION_STATUS_MANAGE if payload.status in OWNER_ONLY_MANUSCRIPT_STATUSES else Permission.DOC_WRITE
        with ctx.db.transaction() as conn:
            doc = load_manuscript(conn, document_id, uid, Permission.PROJECT_VIEW)
            ctx.require_project_permission(conn, doc["project_id"], uid, perm)
            conn.execute(
                "UPDATE documents SET publication_status = ?, updated_at = ?, updated_by_id = ?, last_editor_name = ? WHERE id = ?",
                (payload.status, utc_now_iso(), uid, session["full_name"], document_id),
            )
            ctx.log_activity(conn, doc["project_id"], uid, "manuscript.status", "document", document_id,
                             f"Set '{doc['title']}' to {payload.status}")
            return {"id": document_id, "status": payload.status}

    @router.delete("/manuscripts/{document_id}")
    def delete_manuscript(document_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            doc = load_manuscript(conn, document_id, uid, Permission.DOC_WRITE)
            conn.execute("UPDATE documents SET is_deleted = 1, deleted_at = ? WHERE id = ?", (utc_now_iso(), document_id))
            ctx.log_activity(conn, doc["project_id"], uid, "manuscript.trashed", "document", document_id, f"Moved paper '{doc['title']}' to Trash")
        return {"status": "trashed", "message": "Paper moved to Trash. It can be restored."}

    @router.post("/manuscripts/{document_id}/restore")
    def restore_manuscript(document_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            doc = load_manuscript(conn, document_id, uid, Permission.DOC_WRITE, include_deleted=True)
            conn.execute("UPDATE documents SET is_deleted = 0, deleted_at = NULL WHERE id = ?", (document_id,))
            ctx.log_activity(conn, doc["project_id"], uid, "manuscript.restored", "document", document_id, f"Restored paper '{doc['title']}'")
        return {"status": "restored"}

    @router.post("/manuscripts/{document_id}/copy", status_code=201)
    def copy_manuscript(document_id: str, payload: ManuscriptCopyRequest, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        """Create a new draft/revision from the current state of a manuscript."""
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            src = load_manuscript(conn, document_id, uid, Permission.DOC_WRITE)
            files = active_files(conn, document_id)
            texts, binaries, folders = snapshot_texts(conn, files)
        now = utc_now_iso()
        new_id = f"doc_{uuid.uuid4().hex[:14]}"
        with ctx.db.transaction() as conn:
            ctx.require_project_permission(conn, src["project_id"], uid, Permission.DOC_WRITE)
            conn.execute(
                "INSERT INTO documents (id, project_id, title, content_html, current_version, is_pinned, review_status, publication_status, "
                "doc_kind, main_file_path, compiler, last_editor_name, created_by_id, updated_by_id, created_at, updated_at) "
                "VALUES (?, ?, ?, '', 1, 0, 'draft', 'Working Draft', 'latex', ?, ?, ?, ?, ?, ?, ?)",
                (new_id, src["project_id"], sanitize_plain_text(payload.title), src["main_file_path"], src["compiler"],
                 session["full_name"], uid, uid, now, now),
            )
            doc = dict(conn.execute("SELECT * FROM documents WHERE id = ?", (new_id,)).fetchone())
            for path, text in texts.items():
                insert_text_file(conn, doc, path, text, uid, version_kind="import")
            for path, key in binaries.items():
                insert_binary_file(conn, doc, path, ctx.storage.read_bytes(key), uid)
            for folder in folders:
                insert_folder_chain(conn, doc, folder + "/x", uid)
            ctx.log_activity(conn, src["project_id"], uid, "manuscript.copied", "document", new_id,
                             f"Created revision '{doc['title']}' from '{src['title']}'")
            return serialize_manuscript(doc, ctx.get_project_role(conn, src["project_id"], uid) or "")

    # ------------------------------------------------------------------
    # File tree
    # ------------------------------------------------------------------
    @router.post("/manuscripts/{document_id}/files", status_code=201)
    def create_manuscript_file(document_id: str, payload: ManuscriptFileCreateRequest, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        path = norm_path(payload.path)
        with ctx.db.transaction() as conn:
            doc = load_manuscript(conn, document_id, uid, Permission.DOC_WRITE)
            if payload.kind == "folder":
                if path_taken(conn, document_id, path):
                    raise HTTPException(status_code=409, detail=f"'{path}' already exists.")
                insert_folder_chain(conn, doc, path + "/x", uid)
                fid = conn.execute(
                    "SELECT id FROM manuscript_files WHERE document_id = ? AND path = ? AND is_deleted = 0", (document_id, path)
                ).fetchone()["id"]
            else:
                if not is_text_path(path):
                    raise HTTPException(status_code=422, detail="Use upload for binary files such as images or PDFs.")
                fid = insert_text_file(conn, doc, path, payload.content, uid)
            touch_document(conn, doc, uid, session["full_name"])
            ctx.log_activity(conn, doc["project_id"], uid, "manuscript.file_created", "manuscript_file", fid, f"Created '{path}' in '{doc['title']}'")
            return dict(conn.execute(f"SELECT {FILE_COLUMNS} FROM manuscript_files WHERE id = ?", (fid,)).fetchone())  # noqa: S608

    @router.post("/manuscripts/{document_id}/files/upload", status_code=201)
    async def upload_manuscript_files(
        document_id: str,
        request: Request,
        files: list[UploadFile] = File(...),
        folder: str = Form(""),
        replace: bool = Form(False),
        session: Dict[str, Any] = Depends(auth),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        ctx.enforce_rate_limit(request, "manuscript_upload", settings.rate_limit_upload_per_minute, uid)
        base = norm_path(folder.strip("/ ")) if folder.strip("/ ") else ""
        payloads: list[tuple[str, bytes]] = []
        for up in files[:50]:
            data = await up.read(settings.max_upload_size_bytes + 1)
            if len(data) > settings.max_upload_size_bytes:
                raise HTTPException(status_code=413, detail=f"{up.filename}: exceeds the configured size limit.")
            name = PurePosixPath((up.filename or "file").replace("\\", "/")).name
            payloads.append((norm_path(f"{base}/{name}" if base else name), data))
        created = []
        with ctx.db.transaction() as conn:
            doc = load_manuscript(conn, document_id, uid, Permission.DOC_WRITE)
            for path, data in payloads:
                if is_text_path(path) and not path.endswith(".pdf"):
                    warnings: list[str] = []
                    text = decode_text(data, path, warnings)
                    existing = conn.execute(
                        "SELECT id FROM manuscript_files WHERE document_id = ? AND path = ? AND is_deleted = 0", (document_id, path)
                    ).fetchone()
                    if existing:
                        raise HTTPException(status_code=409, detail=f"'{path}' already exists. Edit it in the editor or restore a version instead.")
                    fid = insert_text_file(conn, doc, path, text, uid, version_kind="import")
                else:
                    fid = insert_binary_file(conn, doc, path, data, uid, replace=replace)
                created.append({"id": fid, "path": path})
            touch_document(conn, doc, uid, session["full_name"])
            ctx.log_activity(conn, doc["project_id"], uid, "manuscript.files_uploaded", "document", document_id,
                             f"Uploaded {len(created)} file(s) to '{doc['title']}'")
        return {"files": created}

    @router.get("/manuscript-files/{file_id}")
    def get_manuscript_file(file_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            f, _doc = load_file(conn, file_id, uid, Permission.PROJECT_VIEW)
            if f["file_kind"] == "text":
                state = current_state(conn, file_id)
                f["content"] = state["text_content"]
                f["updated_by_name"] = state["updated_by_name"]
        return f

    @router.get("/manuscript-files/{file_id}/raw")
    def download_manuscript_file(file_id: str, inline: bool = Query(default=False), session: Dict[str, Any] = Depends(auth)) -> Response:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            f, _doc = load_file(conn, file_id, uid, Permission.PROJECT_VIEW)
            text = get_text(conn, file_id) if f["file_kind"] == "text" else ""
        name = PurePosixPath(f["path"]).name
        if f["file_kind"] == "text":
            return Response(
                text.encode("utf-8"),
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": content_disposition(name), "X-Content-Type-Options": "nosniff"},
            )
        if f["file_kind"] != "binary":
            raise HTTPException(status_code=400, detail="Folders cannot be downloaded individually.")
        safe_inline = inline and f["media_type"] in ("image/png", "image/jpeg", "image/webp", "application/pdf")
        return FileResponse(
            ctx.storage.path_for(f["storage_key"]),
            media_type=f["media_type"],
            headers={
                "Content-Disposition": ("inline" if safe_inline else content_disposition(name)),
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; sandbox",
            },
        )

    @router.patch("/manuscript-files/{file_id}")
    def rename_manuscript_file(file_id: str, payload: ManuscriptFileUpdateRequest, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        new_path = norm_path(payload.path)
        now = utc_now_iso()
        with ctx.db.transaction() as conn:
            f, doc = load_file(conn, file_id, uid, Permission.DOC_WRITE)
            old_path = f["path"]
            if new_path == old_path:
                return {"id": file_id, "path": new_path}
            if f["file_kind"] == "folder" and (new_path + "/").startswith(old_path + "/"):
                raise HTTPException(status_code=422, detail="A folder cannot be moved into itself.")
            if path_taken(conn, doc["id"], new_path, exclude_id=file_id):
                raise HTTPException(status_code=409, detail=f"'{new_path}' already exists.")
            insert_folder_chain(conn, doc, new_path, uid)
            conn.execute("UPDATE manuscript_files SET path = ?, updated_at = ?, updated_by_id = ? WHERE id = ?", (new_path, now, uid, file_id))
            moved = 1
            if f["file_kind"] == "folder":
                children = conn.execute(
                    "SELECT id, path FROM manuscript_files WHERE document_id = ? AND is_deleted = 0 AND path LIKE ?",
                    (doc["id"], old_path + "/%"),
                ).fetchall()
                for child in children:
                    conn.execute(
                        "UPDATE manuscript_files SET path = ?, updated_at = ? WHERE id = ?",
                        (new_path + child["path"][len(old_path):], now, child["id"]),
                    )
                moved += len(children)
            if doc["main_file_path"] == old_path or doc["main_file_path"].startswith(old_path + "/"):
                conn.execute(
                    "UPDATE documents SET main_file_path = ? WHERE id = ?",
                    (new_path + doc["main_file_path"][len(old_path):], doc["id"]),
                )
            touch_document(conn, doc, uid, session["full_name"])
            ctx.log_activity(conn, doc["project_id"], uid, "manuscript.file_moved", "manuscript_file", file_id, f"Renamed '{old_path}' to '{new_path}'")
        warning = None
        if f["file_kind"] != "folder":
            # Renames never rewrite source; report references that now point at the old path.
            old_ref = re.sub(r"\.(tex|bib)$", "", old_path)
            with ctx.db.transaction() as conn:
                hits = [
                    r["path"] for r in conn.execute(
                        "SELECT path, text_content FROM manuscript_files WHERE document_id = ? AND file_kind = 'text' AND is_deleted = 0",
                        (doc["id"],),
                    ).fetchall()
                    if old_ref in r["text_content"]
                ]
            if hits:
                warning = f"'{old_path}' is still referenced in: {', '.join(hits[:10])}. Update those references."
        return {"id": file_id, "path": new_path, "moved": moved, "warning": warning}

    @router.delete("/manuscript-files/{file_id}")
    def delete_manuscript_file(file_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        with ctx.db.transaction() as conn:
            f, doc = load_file(conn, file_id, uid, Permission.DOC_WRITE)
            affected = [f]
            if f["file_kind"] == "folder":
                affected += [dict(r) for r in conn.execute(
                    "SELECT id, path FROM manuscript_files WHERE document_id = ? AND is_deleted = 0 AND path LIKE ?",
                    (doc["id"], f["path"] + "/%"),
                ).fetchall()]
            if any(a["path"] == doc["main_file_path"] for a in affected):
                raise HTTPException(status_code=409, detail="The main file cannot be deleted. Choose another main file first.")
            batch = uuid.uuid4().hex[:8]
            for a in affected:
                conn.execute(
                    "UPDATE manuscript_files SET is_deleted = 1, deleted_at = ?, updated_by_id = ? WHERE id = ?",
                    (f"{now}#{batch}", uid, a["id"]),
                )
            touch_document(conn, doc, uid, session["full_name"])
            ctx.log_activity(conn, doc["project_id"], uid, "manuscript.file_trashed", "manuscript_file", file_id, f"Moved '{f['path']}' to Trash")
        return {"status": "trashed", "count": len(affected)}

    @router.get("/manuscripts/{document_id}/trash")
    def list_trashed_files(document_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            load_manuscript(conn, document_id, uid, Permission.PROJECT_VIEW)
            rows = conn.execute(
                f"SELECT {FILE_COLUMNS} FROM manuscript_files WHERE document_id = ? AND is_deleted = 1 ORDER BY deleted_at DESC LIMIT 200",  # noqa: S608
                (document_id,),
            ).fetchall()
            return {"files": [dict(r) for r in rows]}

    @router.post("/manuscript-files/{file_id}/restore")
    def restore_manuscript_file(file_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            f, doc = load_file(conn, file_id, uid, Permission.DOC_WRITE, include_deleted=True)
            group = conn.execute(
                "SELECT id, path FROM manuscript_files WHERE document_id = ? AND is_deleted = 1 AND deleted_at = ?",
                (doc["id"], f["deleted_at"]),
            ).fetchall() if f["deleted_at"] else [f]
            for g in group:
                if path_taken(conn, doc["id"], g["path"]):
                    raise HTTPException(status_code=409, detail=f"'{g['path']}' exists again; rename it before restoring.")
            for g in group:
                conn.execute("UPDATE manuscript_files SET is_deleted = 0, deleted_at = NULL WHERE id = ?", (g["id"],))
            insert_folder_chain(conn, doc, f["path"], uid)
            ctx.log_activity(conn, doc["project_id"], uid, "manuscript.file_restored", "manuscript_file", file_id, f"Restored '{f['path']}'")
        return {"status": "restored", "count": len(group)}

    # ------------------------------------------------------------------
    # Saving (optimistic concurrency: never silently overwrite a newer save)
    # ------------------------------------------------------------------
    @router.put("/manuscript-files/{file_id}/content")
    def save_file_content(file_id: str, payload: FileContentSaveRequest, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        if len(payload.content.encode("utf-8")) > MAX_TEXT_FILE_BYTES:
            raise HTTPException(status_code=413, detail="This file is too large to edit in the browser.")
        with ctx.db.transaction() as conn:
            f, doc = load_file(conn, file_id, uid, Permission.DOC_WRITE)
            if f["file_kind"] != "text":
                raise HTTPException(status_code=400, detail="Only text files can be edited.")
            try:
                result = write_text(conn, file_id, payload.content, uid, expected_revision=payload.base_revision)
            except RevisionConflict as conflict:
                cur = conflict.current
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": f"{cur['updated_by_name'] or 'Someone'} saved a newer version of this file. "
                        "Compare or reload before saving again.",
                        "current_revision": cur["revision"],
                        "current_content": cur["text_content"],
                        "updated_by_name": cur["updated_by_name"],
                        "updated_at": cur["updated_at"],
                    },
                ) from None
            if result["changed"]:
                touch_document(conn, doc, uid, session["full_name"])
                conn.execute(
                    "UPDATE projects SET last_editor_id = ?, last_editor_name = ?, last_edited_at = ?, updated_at = ? WHERE id = ?",
                    (uid, session["full_name"], result["updated_at"], result["updated_at"], doc["project_id"]),
                )
            if result["version_created"]:
                ctx.log_activity(conn, doc["project_id"], uid, "manuscript.edited", "manuscript_file", file_id, f"Edited '{f['path']}'")
            return {"revision": result["revision"], "changed": result["changed"], "version_created": result["version_created"],
                    "updated_at": result.get("updated_at", f["updated_at"])}

    # ------------------------------------------------------------------
    # Version history
    # ------------------------------------------------------------------
    @router.get("/manuscript-files/{file_id}/versions")
    def list_file_versions(file_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            load_file(conn, file_id, uid, Permission.PROJECT_VIEW)
            rows = conn.execute(
                "SELECT v.id, v.version_number, v.summary, v.version_kind, v.created_at, v.content_sha256, LENGTH(v.content) AS length, "
                "u.full_name AS author_name FROM file_text_versions v LEFT JOIN users u ON u.id = v.author_id "
                "WHERE v.file_id = ? ORDER BY v.version_number DESC LIMIT 500",
                (file_id,),
            ).fetchall()
            return {"versions": [dict(r) for r in rows]}

    @router.post("/manuscript-files/{file_id}/versions", status_code=201)
    def save_file_version(file_id: str, payload: VersionCreateRequest, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            f, doc = load_file(conn, file_id, uid, Permission.DOC_WRITE)
            if f["file_kind"] != "text":
                raise HTTPException(status_code=400, detail="Only text files have version history.")
            result = create_version(conn, file_id, "manual", sanitize_plain_text(payload.summary) or "Saved version", uid,
                                    get_text(conn, file_id), force=True)
            ctx.log_activity(conn, doc["project_id"], uid, "manuscript.version_saved", "manuscript_file", file_id,
                             f"Saved a version of '{f['path']}'")
        return result or {}

    @router.get("/file-versions/{version_id}")
    def get_file_version(version_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            v = conn.execute("SELECT * FROM file_text_versions WHERE id = ?", (version_id,)).fetchone()
            if not v:
                raise HTTPException(status_code=404, detail="Version not found.")
            load_file(conn, v["file_id"], uid, Permission.PROJECT_VIEW, include_deleted=True)
            return dict(v)

    @router.post("/file-versions/{version_id}/restore")
    def restore_file_version(version_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            v = conn.execute("SELECT * FROM file_text_versions WHERE id = ?", (version_id,)).fetchone()
            if not v:
                raise HTTPException(status_code=404, detail="Version not found.")
            f, doc = load_file(conn, v["file_id"], uid, Permission.DOC_WRITE)
            # Preserve the current state first so the restore itself can be undone.
            create_version(conn, f["id"], "auto", "Before restoring an earlier version", uid, get_text(conn, f["id"]))
            result = write_text(conn, f["id"], v["content"], uid, auto_version=False)
            create_version(conn, f["id"], "restore", f"Restored version {v['version_number']}", uid, v["content"], force=True)
            touch_document(conn, doc, uid, session["full_name"])
            ctx.log_activity(conn, doc["project_id"], uid, "manuscript.version_restored", "manuscript_file", f["id"],
                             f"Restored '{f['path']}' to version {v['version_number']}")
        return {"status": "restored", "restored_version": v["version_number"], "revision": result["revision"]}

    @router.get("/manuscript-files/{file_id}/compare")
    def compare_file_versions(
        file_id: str,
        left: str = Query(..., max_length=64),
        right: str = Query(default="current", max_length=64),
        session: Dict[str, Any] = Depends(auth),
    ) -> Dict[str, Any]:
        uid = session["user_id"]

        def load_side(conn: Any, ref: str) -> tuple[str, str]:
            if ref == "current":
                return "Current", get_text(conn, file_id)
            v = conn.execute("SELECT version_number, content FROM file_text_versions WHERE id = ? AND file_id = ?", (ref, file_id)).fetchone()
            if not v:
                raise HTTPException(status_code=404, detail="Version not found.")
            return f"Version {v['version_number']}", v["content"]

        with ctx.db.transaction() as conn:
            load_file(conn, file_id, uid, Permission.PROJECT_VIEW)
            ltitle, ltext = load_side(conn, left)
            rtitle, rtext = load_side(conn, right)
        unified = "\n".join(difflib.unified_diff(ltext.splitlines(), rtext.splitlines(), ltitle, rtitle, lineterm=""))
        return {"left_title": ltitle, "right_title": rtitle, "left": ltext, "right": rtext, "unified_diff": unified}

    # ------------------------------------------------------------------
    # Analysis: outline, completion index, dependencies
    # ------------------------------------------------------------------
    @router.get("/manuscript-files/{file_id}/outline")
    def file_outline(file_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            f, _ = load_file(conn, file_id, uid, Permission.PROJECT_VIEW)
            text = get_text(conn, file_id)
        if f["file_kind"] != "text":
            raise HTTPException(status_code=400, detail="Outlines are available for text files only.")
        return {"items": [i.as_dict() for i in build_outline(text)]}

    @router.get("/manuscript-files/{file_id}/section")
    def export_section(
        file_id: str,
        start: int = Query(..., ge=0),
        end: int = Query(..., ge=1),
        download: bool = Query(default=False),
        session: Dict[str, Any] = Depends(auth),
    ) -> Response:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            f, doc = load_file(conn, file_id, uid, Permission.PROJECT_VIEW)
            text = get_text(conn, file_id)
        try:
            body = extract_range(text, start, end)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="The section no longer matches the current source. Refresh the outline.") from exc
        item = next((i for i in build_outline(text) if i.start == start and i.end == end), None)
        name = safe_download_name((item.title if item else "section").lower(), "section") + ".tex"
        headers = {"Content-Disposition": content_disposition(name)} if download else {}
        return Response(body.encode("utf-8"), media_type="text/plain; charset=utf-8", headers=headers)

    @router.get("/manuscripts/{document_id}/index")
    def completion_index(document_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        """Labels, citation keys and file paths for editor autocompletion."""
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            doc = load_manuscript(conn, document_id, uid, Permission.PROJECT_VIEW)
            files = active_files(conn, document_id)
            lib = conn.execute(
                "SELECT cite_key, title, authors, year, entry_type FROM literature_references WHERE project_id = ? AND cite_key != ''",
                (doc["project_id"],),
            ).fetchall()
            texts = {f["id"]: get_text(conn, f["id"]) for f in files if f["file_kind"] == "text"}
        labels: list[dict[str, Any]] = []
        citations: dict[str, dict[str, Any]] = {
            r["cite_key"]: {"key": r["cite_key"], "title": r["title"], "authors": r["authors"], "year": r["year"], "source": "library"}
            for r in lib
        }
        for f in files:
            if f["file_kind"] != "text":
                continue
            text = texts[f["id"]]
            if f["path"].endswith(".tex"):
                labels += [{**lbl, "file": f["path"]} for lbl in find_labels(text)]
            elif f["path"].endswith(".bib"):
                entries, _ = parse_bibtex(text)
                for e in entries:
                    citations[e.key] = {"key": e.key, "title": e.get("title"), "authors": e.get("author"),
                                        "year": e.get("year"), "source": f["path"]}
        return {
            "labels": labels,
            "citations": list(citations.values()),
            "files": [{"path": f["path"], "kind": f["file_kind"]} for f in files if f["file_kind"] != "folder"],
        }

    @router.get("/manuscripts/{document_id}/dependencies")
    def manuscript_dependencies(document_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            doc = load_manuscript(conn, document_id, uid, Permission.PROJECT_VIEW)
            files = active_files(conn, document_id)
            keys = library_keys(conn, doc["project_id"])
            texts, binaries, _f = snapshot_texts(conn, files)
        return analyze_dependencies(texts, binaries.keys(), doc["main_file_path"], keys).as_dict()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export_inputs(document_id: str, uid: str) -> tuple[Dict[str, Any], dict[str, str], dict[str, str], list[str]]:
        with ctx.db.transaction() as conn:
            doc = load_manuscript(conn, document_id, uid, Permission.PROJECT_VIEW)
            files = active_files(conn, document_id)
            ctx.log_audit(conn, "MANUSCRIPT_EXPORTED", f"Exported {document_id}", actor_id=uid, project_id=doc["project_id"])
            texts, binaries, folders = snapshot_texts(conn, files)
        return doc, texts, binaries, folders

    @router.get("/manuscripts/{document_id}/export/project.zip")
    def export_project_zip(document_id: str, request: Request, session: Dict[str, Any] = Depends(auth)) -> Response:
        uid = session["user_id"]
        ctx.enforce_rate_limit(request, "export", 30, uid)
        doc, texts, binaries, folders = export_inputs(document_id, uid)
        report = analyze_dependencies(texts, binaries.keys(), doc["main_file_path"])
        readme = build_readme(doc["title"], doc["main_file_path"], doc["compiler"], report)
        root = safe_download_name(doc["title"], "paper")
        data = build_project_zip(texts, binaries, folders, ctx.storage.read_bytes, readme, root)
        return Response(
            data,
            media_type="application/zip",
            headers={
                "Content-Disposition": content_disposition(f"{root}.zip"),
                "X-Export-Missing": str(len(report.missing_inputs) + len(report.missing_figures) + len(report.missing_bibliographies)),
            },
        )

    @router.get("/manuscripts/{document_id}/export/paper.tex")
    def export_flattened(document_id: str, session: Dict[str, Any] = Depends(auth)) -> Response:
        uid = session["user_id"]
        doc, texts, _b, _f = export_inputs(document_id, uid)
        try:
            flat, warnings = flatten_latex(texts, doc["main_file_path"])
        except KeyError as exc:
            raise HTTPException(status_code=409, detail="The main file is missing.") from exc
        return Response(
            flat.encode("utf-8"),
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": content_disposition(safe_download_name(doc["title"]) + ".tex"),
                "X-Export-Warnings": json.dumps(warnings[:20]),
            },
        )

    @router.get("/manuscripts/{document_id}/export/bibliography.bib", response_class=PlainTextResponse)
    def export_manuscript_bib(document_id: str, session: Dict[str, Any] = Depends(auth)) -> Response:
        uid = session["user_id"]
        doc, texts, _b, _f = export_inputs(document_id, uid)
        bibs = [texts[p] for p in sorted(texts) if p.endswith(".bib")]
        if not bibs:
            raise HTTPException(status_code=404, detail="This paper has no .bib file. Export the project library from References instead.")
        return Response(
            "\n\n".join(b.strip() for b in bibs).encode("utf-8") + b"\n",
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": content_disposition(safe_download_name(doc["title"]) + ".bib")},
        )

    @router.get("/manuscripts/{document_id}/export/assets.zip")
    def export_assets(document_id: str, session: Dict[str, Any] = Depends(auth)) -> Response:
        uid = session["user_id"]
        doc, _t, binaries, _f = export_inputs(document_id, uid)
        if not binaries:
            raise HTTPException(status_code=404, detail="This paper has no figures or other binary assets.")
        root = safe_download_name(doc["title"]) + "-assets"
        return Response(
            build_assets_zip(binaries, ctx.storage.read_bytes, root),
            media_type="application/zip",
            headers={"Content-Disposition": content_disposition(root + ".zip")},
        )

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------
    def notify_mentions(conn: Any, doc: Dict[str, Any], body: str, author: Dict[str, Any]) -> list[str]:
        mentioned: list[str] = []
        for username in set(_MENTION_RE.findall(body)):
            row = conn.execute(
                "SELECT u.id, u.username FROM users u JOIN project_memberships pm ON pm.user_id = u.id "
                "WHERE pm.project_id = ? AND LOWER(u.username) = LOWER(?)",
                (doc["project_id"], username),
            ).fetchone()
            if row and row["id"] != author["user_id"]:
                mentioned.append(row["username"])
                ctx.notify(conn, row["id"], doc["project_id"], "mention", "You were mentioned",
                           f"{author['full_name']} mentioned you on '{doc['title']}'.")
        return mentioned

    def serialize_comment(row: Any) -> Dict[str, Any]:
        d = dict(row)
        d["anchor"] = json.loads(d.pop("anchor_json") or "{}")
        d["mentions"] = json.loads(d.pop("mentions_json") or "[]")
        return d

    @router.get("/manuscripts/{document_id}/comments")
    def list_doc_comments(
        document_id: str,
        file_id: Optional[str] = Query(default=None),
        status: Optional[str] = Query(default=None, pattern="^(open|resolved)$"),
        session: Dict[str, Any] = Depends(auth),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            load_manuscript(conn, document_id, uid, Permission.PROJECT_VIEW)
            sql = (
                "SELECT c.*, u.full_name AS author_name, u.username AS author_username, r.full_name AS resolved_by_name "
                "FROM doc_comments c JOIN users u ON u.id = c.author_id LEFT JOIN users r ON r.id = c.resolved_by_id "
                "WHERE c.document_id = ? AND c.is_deleted = 0"
            )
            params: list[Any] = [document_id]
            if file_id:
                sql += " AND (c.file_id = ? OR c.parent_id IS NOT NULL)"
                params.append(file_id)
            if status:
                sql += " AND (c.status = ? OR c.parent_id IS NOT NULL)"
                params.append(status)
            rows = conn.execute(sql + " ORDER BY c.created_at", params).fetchall()
        all_comments = [serialize_comment(r) for r in rows]
        roots = [c for c in all_comments if not c["parent_id"]]
        root_ids = {c["id"] for c in roots}
        for root in roots:
            root["replies"] = [c for c in all_comments if c["parent_id"] == root["id"]]
        orphans = [c for c in all_comments if c["parent_id"] and c["parent_id"] not in root_ids]
        del orphans
        return {"threads": roots}

    @router.post("/manuscripts/{document_id}/comments", status_code=201)
    def create_doc_comment(document_id: str, payload: DocCommentCreateRequest, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        cid = f"dc_{uuid.uuid4().hex[:16]}"
        with ctx.db.transaction() as conn:
            doc = load_manuscript(conn, document_id, uid, Permission.COMMENT_WRITE)
            file_id = payload.file_id
            if payload.parent_id:
                parent = conn.execute(
                    "SELECT id, file_id, author_id FROM doc_comments WHERE id = ? AND document_id = ? AND parent_id IS NULL AND is_deleted = 0",
                    (payload.parent_id, document_id),
                ).fetchone()
                if not parent:
                    raise HTTPException(status_code=404, detail="Comment thread not found.")
                file_id = parent["file_id"]
                if parent["author_id"] != uid:
                    ctx.notify(conn, parent["author_id"], doc["project_id"], "comment", "New reply",
                               f"{session['full_name']} replied to your comment on '{doc['title']}'.")
            elif file_id:
                ok = conn.execute(
                    "SELECT 1 FROM manuscript_files WHERE id = ? AND document_id = ? AND is_deleted = 0", (file_id, document_id)
                ).fetchone()
                if not ok:
                    raise HTTPException(status_code=404, detail="File not found.")
            body = sanitize_plain_text(payload.body, max_length=5000)
            mentions = notify_mentions(conn, doc, body, session)
            anchor = payload.anchor.model_dump(by_alias=True) if payload.anchor and not payload.parent_id else {}
            conn.execute(
                "INSERT INTO doc_comments (id, project_id, document_id, file_id, parent_id, body, anchor_json, quoted_text, status, "
                "mentions_json, author_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)",
                (cid, doc["project_id"], document_id, file_id, payload.parent_id, body, json.dumps(anchor),
                 sanitize_plain_text(payload.quoted_text, max_length=2000), json.dumps(mentions), uid, now, now),
            )
            if payload.parent_id:
                conn.execute("UPDATE doc_comments SET updated_at = ? WHERE id = ?", (now, payload.parent_id))
            ctx.log_activity(conn, doc["project_id"], uid, "comment.created", "doc_comment", cid, f"Commented on '{doc['title']}'")
            row = conn.execute(
                "SELECT c.*, u.full_name AS author_name, u.username AS author_username, NULL AS resolved_by_name "
                "FROM doc_comments c JOIN users u ON u.id = c.author_id WHERE c.id = ?",
                (cid,),
            ).fetchone()
            out = serialize_comment(row)
            out["replies"] = []
            return out

    @router.patch("/doc-comments/{comment_id}")
    def update_doc_comment(comment_id: str, payload: DocCommentUpdateRequest, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        with ctx.db.transaction() as conn:
            c = conn.execute("SELECT * FROM doc_comments WHERE id = ? AND is_deleted = 0", (comment_id,)).fetchone()
            if not c:
                raise HTTPException(status_code=404, detail="Comment not found.")
            doc = load_manuscript(conn, c["document_id"], uid, Permission.COMMENT_WRITE)
            if payload.body is not None:
                if c["author_id"] != uid:
                    raise HTTPException(status_code=403, detail="Only the author can edit a comment.")
                conn.execute("UPDATE doc_comments SET body = ?, updated_at = ? WHERE id = ?",
                             (sanitize_plain_text(payload.body, max_length=5000), now, comment_id))
            if payload.status is not None:
                if c["parent_id"]:
                    raise HTTPException(status_code=422, detail="Resolve the thread, not an individual reply.")
                conn.execute(
                    "UPDATE doc_comments SET status = ?, resolved_by_id = ?, updated_at = ? WHERE id = ?",
                    (payload.status, uid if payload.status == "resolved" else None, now, comment_id),
                )
                ctx.log_activity(conn, doc["project_id"], uid, f"comment.{payload.status}", "doc_comment", comment_id,
                                 f"{'Resolved' if payload.status == 'resolved' else 'Reopened'} a comment on '{doc['title']}'")
        return {"id": comment_id, "status": payload.status or c["status"]}

    @router.delete("/doc-comments/{comment_id}")
    def delete_doc_comment(comment_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            c = conn.execute("SELECT * FROM doc_comments WHERE id = ? AND is_deleted = 0", (comment_id,)).fetchone()
            if not c:
                raise HTTPException(status_code=404, detail="Comment not found.")
            doc = load_manuscript(conn, c["document_id"], uid, Permission.PROJECT_VIEW)
            role = ctx.get_project_role(conn, doc["project_id"], uid)
            if c["author_id"] != uid and role != "owner":
                raise HTTPException(status_code=403, detail="Only the author or the project owner can delete a comment.")
            conn.execute("UPDATE doc_comments SET is_deleted = 1, updated_at = ? WHERE id = ? OR parent_id = ?",
                         (utc_now_iso(), comment_id, comment_id))
        return {"status": "deleted"}

    # ------------------------------------------------------------------
    # Suggestions (proposed edits applied only on explicit acceptance)
    # ------------------------------------------------------------------
    @router.get("/manuscripts/{document_id}/suggestions")
    def list_suggestions(
        document_id: str,
        file_id: Optional[str] = Query(default=None),
        status: str = Query(default="pending", pattern="^(pending|accepted|rejected|stale|all)$"),
        session: Dict[str, Any] = Depends(auth),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            load_manuscript(conn, document_id, uid, Permission.PROJECT_VIEW)
            sql = (
                "SELECT s.*, u.full_name AS author_name, r.full_name AS resolved_by_name FROM doc_suggestions s "
                "JOIN users u ON u.id = s.author_id LEFT JOIN users r ON r.id = s.resolved_by_id WHERE s.document_id = ?"
            )
            params: list[Any] = [document_id]
            if file_id:
                sql += " AND s.file_id = ?"
                params.append(file_id)
            if status != "all":
                sql += " AND s.status = ?"
                params.append(status)
            rows = conn.execute(sql + " ORDER BY s.created_at", params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["anchor"] = json.loads(d.pop("anchor_json") or "{}")
            out.append(d)
        return {"suggestions": out}

    @router.post("/manuscripts/{document_id}/suggestions", status_code=201)
    def create_suggestion(document_id: str, payload: SuggestionCreateRequest, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        if payload.original_text == payload.proposed_text:
            raise HTTPException(status_code=422, detail="The suggestion does not change anything.")
        with ctx.db.transaction() as conn:
            doc = load_manuscript(conn, document_id, uid, Permission.COMMENT_WRITE)
            ok = conn.execute(
                "SELECT 1 FROM manuscript_files WHERE id = ? AND document_id = ? AND file_kind = 'text' AND is_deleted = 0",
                (payload.file_id, document_id),
            ).fetchone()
            if not ok:
                raise HTTPException(status_code=404, detail="File not found.")
        with ctx.db.transaction() as conn:
            current = get_text(conn, payload.file_id)
        a = payload.anchor
        if current[a.from_offset : a.to_offset] != payload.original_text:
            raise HTTPException(status_code=409, detail="The selected text changed while you were writing the suggestion. Select it again.")
        sid = f"sg_{uuid.uuid4().hex[:16]}"
        with ctx.db.transaction() as conn:
            conn.execute(
                "INSERT INTO doc_suggestions (id, project_id, document_id, file_id, author_id, anchor_json, original_text, proposed_text, note, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (sid, doc["project_id"], document_id, payload.file_id, uid, json.dumps(a.model_dump(by_alias=True)),
                 payload.original_text, payload.proposed_text, sanitize_plain_text(payload.note, max_length=2000), utc_now_iso()),
            )
            ctx.log_activity(conn, doc["project_id"], uid, "suggestion.created", "doc_suggestion", sid, f"Suggested an edit to '{doc['title']}'")
        return {"id": sid, "status": "pending"}

    def locate_suggestion(text: str, s: Dict[str, Any]) -> Optional[tuple[int, int]]:
        anchor = json.loads(s["anchor_json"] or "{}")
        start, end = int(anchor.get("from", 0)), int(anchor.get("to", 0))
        original = s["original_text"]
        if text[start:end] == original:
            return start, end
        # Text moved: look for the original with its recorded context; accept only a unique match.
        needle = anchor.get("context_before", "") + original + anchor.get("context_after", "")
        hits = [m.start() for m in re.finditer(re.escape(needle), text)] if needle and original else []
        if len(hits) == 1:
            s0 = hits[0] + len(anchor.get("context_before", ""))
            return s0, s0 + len(original)
        if original:
            plain = [m.start() for m in re.finditer(re.escape(original), text)]
            if len(plain) == 1:
                return plain[0], plain[0] + len(original)
        return None

    @router.post("/doc-suggestions/{suggestion_id}/accept")
    def accept_suggestion(suggestion_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            s = conn.execute("SELECT * FROM doc_suggestions WHERE id = ?", (suggestion_id,)).fetchone()
            if not s:
                raise HTTPException(status_code=404, detail="Suggestion not found.")
            doc = load_manuscript(conn, s["document_id"], uid, Permission.DOC_WRITE)
            if s["status"] != "pending":
                raise HTTPException(status_code=409, detail=f"Suggestion is already {s['status']}.")
            s = dict(s)
        now = utc_now_iso()
        with ctx.db.transaction() as conn:
            text = get_text(conn, s["file_id"])
            span = locate_suggestion(text, s)
            if span is None:
                conn.execute("UPDATE doc_suggestions SET status = 'stale', resolved_at = ? WHERE id = ?", (now, suggestion_id))
        if span is None:
            raise HTTPException(status_code=409, detail="The suggested text was changed or removed, so the suggestion can no longer be applied.")
        with ctx.db.transaction() as conn:
            write_text(conn, s["file_id"], text[: span[0]] + s["proposed_text"] + text[span[1]:], uid)
            conn.execute(
                "UPDATE doc_suggestions SET status = 'accepted', resolved_by_id = ?, resolved_at = ? WHERE id = ?", (uid, now, suggestion_id)
            )
            if s["author_id"] != uid:
                ctx.notify(conn, s["author_id"], doc["project_id"], "suggestion", "Suggestion accepted",
                           f"{session['full_name']} accepted your suggestion on '{doc['title']}'.")
            ctx.log_activity(conn, doc["project_id"], uid, "suggestion.accepted", "doc_suggestion", suggestion_id, f"Accepted a suggestion on '{doc['title']}'")
        return {"id": suggestion_id, "status": "accepted"}

    @router.post("/doc-suggestions/{suggestion_id}/reject")
    def reject_suggestion(suggestion_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            s = conn.execute("SELECT * FROM doc_suggestions WHERE id = ?", (suggestion_id,)).fetchone()
            if not s:
                raise HTTPException(status_code=404, detail="Suggestion not found.")
            # The author may withdraw their own suggestion; otherwise rejecting requires write access.
            perm = Permission.COMMENT_WRITE if s["author_id"] == uid else Permission.DOC_WRITE
            doc = load_manuscript(conn, s["document_id"], uid, perm)
            if s["status"] != "pending":
                raise HTTPException(status_code=409, detail=f"Suggestion is already {s['status']}.")
            conn.execute(
                "UPDATE doc_suggestions SET status = 'rejected', resolved_by_id = ?, resolved_at = ? WHERE id = ?",
                (uid, utc_now_iso(), suggestion_id),
            )
            ctx.log_activity(conn, doc["project_id"], uid, "suggestion.rejected", "doc_suggestion", suggestion_id, f"Rejected a suggestion on '{doc['title']}'")
        return {"id": suggestion_id, "status": "rejected"}

    # ------------------------------------------------------------------
    # Per-user workspace preferences (panel sizes, view mode, autosave...)
    # ------------------------------------------------------------------
    @router.get("/users/me/workspace-preferences")
    def get_workspace_prefs(session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        with ctx.db.transaction() as conn:
            row = conn.execute("SELECT workspace_prefs_json FROM user_profiles WHERE user_id = ?", (session["user_id"],)).fetchone()
        return {"prefs": json.loads(row["workspace_prefs_json"]) if row else {}}

    @router.patch("/users/me/workspace-preferences")
    def update_workspace_prefs(payload: WorkspacePrefsRequest, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        encoded = json.dumps(payload.prefs, separators=(",", ":"))
        if len(encoded) > 8000:
            raise HTTPException(status_code=413, detail="Preferences are too large.")
        with ctx.db.transaction() as conn:
            row = conn.execute("SELECT workspace_prefs_json FROM user_profiles WHERE user_id = ?", (session["user_id"],)).fetchone()
            merged = {**(json.loads(row["workspace_prefs_json"]) if row else {}), **payload.prefs}
            conn.execute("UPDATE user_profiles SET workspace_prefs_json = ?, updated_at = ? WHERE user_id = ?",
                         (json.dumps(merged), utc_now_iso(), session["user_id"]))
        return {"prefs": merged}

    return router
