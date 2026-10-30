"""Reference manager: BibTeX import/export, duplicates, cite-key maintenance, manuscript sync.

The project library (`literature_references`) is the shared reference manager. Manuscripts
keep their own `.bib` source files; moving entries between the two is always an explicit
action, and renaming a cite key never silently breaks documents.
"""
import json
import re
import uuid
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.v1.context import ApiContext, utc_now_iso
from app.latex.analysis import find_citations
from app.latex.bibtex import (
    BibEntry,
    is_valid_cite_key,
    make_cite_key,
    normalize_doi,
    normalize_title,
    parse_bibtex,
    serialize_entry,
)
from app.latex.export import content_disposition, safe_download_name
from app.latex.paths import ManuscriptPathError, normalize_manuscript_path
from app.latex.textstore import get_text, replace_with_history
from app.permissions.rbac import Permission


class BibImportRequest(BaseModel):
    bibtex: str = Field(..., min_length=1, max_length=5_000_000)
    skip_duplicates: bool = True


class BibEntryUpdateRequest(BaseModel):
    cite_key: Optional[str] = Field(default=None, min_length=1, max_length=120)
    entry_type: Optional[str] = Field(default=None, min_length=2, max_length=40)
    fields: Optional[Dict[str, str]] = None
    rename_in_manuscripts: bool = False


class BibSyncRequest(BaseModel):
    path: str = Field(default="references.bib", max_length=400)
    mode: str = Field(default="merge", pattern="^(merge|replace)$")


class DoiLookupRequest(BaseModel):
    doi: str = Field(..., min_length=6, max_length=200)


def entry_from_row(row: Any) -> tuple[str, str, dict[str, str]]:
    fields = json.loads(row["fields_json"] or "{}")
    # Legacy columns fill gaps for references created before BibTeX fields were stored.
    defaults = {
        "title": row["title"],
        "author": row["authors"],
        "year": str(row["year"]) if row["year"] else "",
        "doi": row["doi"],
        "abstract": row["abstract"],
    }
    venue_field = "booktitle" if row["entry_type"] in ("inproceedings", "conference", "incollection") else "journal"
    defaults[venue_field] = row["journal_or_conference"]
    for k, v in defaults.items():
        if v and not fields.get(k):
            fields[k] = v
    return row["entry_type"] or "article", row["cite_key"], fields


def columns_from_entry(e: BibEntry) -> dict[str, Any]:
    year_m = re.search(r"\d{4}", e.get("year"))
    return {
        "title": (e.get("title") or e.key)[:300],
        "authors": (e.get("author") or e.get("editor") or "Unknown")[:500],
        "year": int(year_m.group(0)) if year_m and 1000 <= int(year_m.group(0)) <= 2100 else 1900,
        "doi": e.get("doi")[:160],
        "journal_or_conference": (e.get("journal") or e.get("booktitle") or e.get("publisher"))[:200],
        "abstract": e.get("abstract")[:4000],
    }


def build_bibliography_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    auth = ctx.get_current_session_and_user

    def find_duplicate(conn: Any, project_id: str, e: BibEntry) -> Optional[Dict[str, Any]]:
        row = conn.execute("SELECT id, cite_key, title FROM literature_references WHERE project_id = ? AND cite_key = ?",
                           (project_id, e.key)).fetchone()
        if row:
            return {"reason": "same cite key", **dict(row)}
        doi = normalize_doi(e.get("doi"))
        title_norm = normalize_title(e.get("title"))
        for r in conn.execute("SELECT id, cite_key, title, doi FROM literature_references WHERE project_id = ?", (project_id,)).fetchall():
            if doi and normalize_doi(r["doi"]) == doi:
                return {"reason": "same DOI", "id": r["id"], "cite_key": r["cite_key"], "title": r["title"]}
            if title_norm and len(title_norm) > 12 and normalize_title(r["title"]) == title_norm:
                return {"reason": "same title", "id": r["id"], "cite_key": r["cite_key"], "title": r["title"]}
        return None

    @router.post("/projects/{project_id}/references/import-bibtex", status_code=201)
    def import_bibtex(project_id: str, payload: BibImportRequest, request: Request, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        ctx.enforce_rate_limit(request, "bib_import", 20, uid)
        entries, errors = parse_bibtex(payload.bibtex)
        created: list[dict[str, str]] = []
        duplicates: list[dict[str, Any]] = []
        now = utc_now_iso()
        with ctx.db.transaction() as conn:
            ctx.require_project_permission(conn, project_id, uid, Permission.LIBRARY_WRITE)
            for e in entries:
                dup = find_duplicate(conn, project_id, e)
                if dup and payload.skip_duplicates:
                    duplicates.append({"key": e.key, "matches": dup})
                    continue
                key = e.key
                if dup and dup.get("reason") == "same cite key":
                    taken = {r["cite_key"] for r in conn.execute("SELECT cite_key FROM literature_references WHERE project_id = ?", (project_id,))}
                    n = 2
                    while f"{e.key}_{n}" in taken:
                        n += 1
                    key = f"{e.key}_{n}"
                cols = columns_from_entry(e)
                rid = f"ref_{uuid.uuid4().hex[:14]}"
                conn.execute(
                    "INSERT INTO literature_references (id, project_id, title, authors, year, doi, journal_or_conference, abstract, "
                    "keywords, tags, notes, created_by_id, created_at, cite_key, entry_type, fields_json, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', '', ?, ?, ?, ?, ?, ?)",
                    (rid, project_id, cols["title"], cols["authors"], cols["year"], cols["doi"], cols["journal_or_conference"],
                     cols["abstract"], json.dumps([k.strip() for k in e.get("keywords").split(",") if k.strip()]),
                     uid, now, key, e.entry_type, json.dumps(e.fields), now),
                )
                created.append({"id": rid, "cite_key": key})
            if created:
                ctx.log_activity(conn, project_id, uid, "reference.imported", "reference", project_id, f"Imported {len(created)} BibTeX entries")
        return {
            "created": created,
            "duplicates": duplicates,
            "errors": [{"line": err.line, "message": err.message} for err in errors],
        }

    @router.get("/projects/{project_id}/references/duplicates")
    def list_duplicates(project_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            ctx.require_project_permission(conn, project_id, uid, Permission.PROJECT_VIEW)
            rows = [dict(r) for r in conn.execute(
                "SELECT id, cite_key, title, doi, year, authors FROM literature_references WHERE project_id = ?", (project_id,)
            ).fetchall()]
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            for sig in (f"doi:{normalize_doi(r['doi'])}" if r["doi"] else "", f"title:{normalize_title(r['title'])}"):
                if sig and not sig.endswith(":"):
                    groups.setdefault(sig, []).append(r)
        seen: set[frozenset[str]] = set()
        out = []
        for sig, items in groups.items():
            ids = frozenset(i["id"] for i in items)
            if len(ids) > 1 and ids not in seen:
                seen.add(ids)
                out.append({"reason": sig.split(":", 1)[0], "references": items})
        return {"groups": out}

    def usages(conn: Any, project_id: str, key: str) -> list[dict[str, Any]]:
        hits = []
        for f in conn.execute(
            "SELECT f.id, f.path, d.id AS document_id, d.title FROM manuscript_files f JOIN documents d ON d.id = f.document_id "
            "WHERE f.project_id = ? AND f.file_kind = 'text' AND f.is_deleted = 0 AND d.is_deleted = 0 AND f.path LIKE '%.tex'",
            (project_id,),
        ).fetchall():
            text = get_text(conn, f["id"])
            count = sum(1 for k in find_citations(text) if k == key)
            if count:
                hits.append({"file_id": f["id"], "path": f["path"], "document_id": f["document_id"], "document_title": f["title"], "count": count})
        return hits

    @router.get("/references/{reference_id}/usages")
    def reference_usages(reference_id: str, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            ref = conn.execute("SELECT project_id, cite_key FROM literature_references WHERE id = ?", (reference_id,)).fetchone()
            if not ref:
                raise HTTPException(status_code=404, detail="Reference not found.")
            ctx.require_project_permission(conn, ref["project_id"], uid, Permission.PROJECT_VIEW)
            project_id, key = ref["project_id"], ref["cite_key"]
        with ctx.db.transaction() as conn:
            return {"cite_key": key, "usages": usages(conn, project_id, key)}

    @router.patch("/references/{reference_id}/bibtex")
    def update_bib_entry(reference_id: str, payload: BibEntryUpdateRequest, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            ref = conn.execute("SELECT * FROM literature_references WHERE id = ?", (reference_id,)).fetchone()
            if not ref:
                raise HTTPException(status_code=404, detail="Reference not found.")
            ctx.require_project_permission(conn, ref["project_id"], uid, Permission.LIBRARY_WRITE)
            ref = dict(ref)
        old_key = ref["cite_key"]
        new_key = payload.cite_key.strip() if payload.cite_key else old_key
        rewritten: list[str] = []
        if new_key != old_key:
            if not is_valid_cite_key(new_key):
                raise HTTPException(status_code=422, detail="Cite keys may not contain spaces, commas, braces or quotes.")
            with ctx.db.transaction() as conn:
                if conn.execute("SELECT 1 FROM literature_references WHERE project_id = ? AND cite_key = ? AND id != ?",
                                (ref["project_id"], new_key, reference_id)).fetchone():
                    raise HTTPException(status_code=409, detail=f"Cite key '{new_key}' is already used in this library.")
                used = usages(conn, ref["project_id"], old_key)
            if used and not payload.rename_in_manuscripts:
                raise HTTPException(
                    status_code=409,
                    detail={"message": f"'{old_key}' is cited in {len(used)} file(s). Confirm to update those citations too.", "usages": used},
                )
            pattern = re.compile(
                r"(\\(?:no)?(?:cite|citep|citet|citealp|citealt|citeauthor|citeyear|parencite|textcite|autocite|footcite|fullcite|smartcite)\*?"
                r"\s*(?:\[[^\]]*\]\s*){0,2}\{)([^}]*)(\})"
            )

            key_re = re.compile(r"(?<![^\s,])" + re.escape(old_key) + r"(?![^\s,])")

            def swap(m: re.Match[str]) -> str:
                # Replace only the key token so the author's spacing and ordering are preserved.
                return m.group(1) + key_re.sub(new_key, m.group(2)) + m.group(3)

            with ctx.db.transaction() as conn:
                for u in used:
                    replace_with_history(conn, u["file_id"], pattern.sub(swap, get_text(conn, u["file_id"])), uid,
                                         f"Renamed citation {old_key} → {new_key}")
                    rewritten.append(u["path"])
        fields = json.loads(ref["fields_json"] or "{}")
        if payload.fields is not None:
            fields = {k.lower().strip(): v for k, v in payload.fields.items() if re.fullmatch(r"[a-z][a-z0-9_\-:+.]*", k.lower().strip())}
        entry = BibEntry(payload.entry_type.lower() if payload.entry_type else ref["entry_type"], new_key, fields)
        cols = columns_from_entry(entry)
        with ctx.db.transaction() as conn:
            conn.execute(
                "UPDATE literature_references SET cite_key = ?, entry_type = ?, fields_json = ?, title = ?, authors = ?, year = ?, doi = ?, "
                "journal_or_conference = ?, abstract = ?, updated_at = ? WHERE id = ?",
                (new_key, entry.entry_type, json.dumps(fields), cols["title"], cols["authors"], cols["year"], cols["doi"],
                 cols["journal_or_conference"], cols["abstract"], utc_now_iso(), reference_id),
            )
            ctx.log_activity(conn, ref["project_id"], uid, "reference.updated", "reference", reference_id, f"Updated reference '{new_key}'")
        return {"id": reference_id, "cite_key": new_key, "rewritten_files": rewritten}

    @router.get("/projects/{project_id}/references/library.bib")
    def export_library_bib(project_id: str, session: Dict[str, Any] = Depends(auth)) -> Response:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            ctx.require_project_permission(conn, project_id, uid, Permission.PROJECT_VIEW)
            rows = conn.execute("SELECT * FROM literature_references WHERE project_id = ? ORDER BY cite_key", (project_id,)).fetchall()
            title = conn.execute("SELECT title FROM projects WHERE id = ?", (project_id,)).fetchone()["title"]
        body = "\n\n".join(serialize_entry(*entry_from_row(r)) for r in rows) + "\n"
        return Response(body.encode("utf-8"), media_type="text/plain; charset=utf-8",
                        headers={"Content-Disposition": content_disposition(safe_download_name(title, "library") + ".bib")})

    @router.post("/manuscripts/{document_id}/bibliography/sync")
    def sync_library_to_manuscript(document_id: str, payload: BibSyncRequest, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        """Write library entries into a manuscript .bib file (merge keeps existing entries untouched)."""
        uid = session["user_id"]
        try:
            path = normalize_manuscript_path(payload.path)
        except ManuscriptPathError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not path.endswith(".bib"):
            raise HTTPException(status_code=422, detail="The target must be a .bib file.")
        with ctx.db.transaction() as conn:
            doc = ctx.load_document_for(conn, document_id, uid, Permission.DOC_WRITE)
            target = conn.execute(
                "SELECT id FROM manuscript_files WHERE document_id = ? AND path = ? AND file_kind = 'text' AND is_deleted = 0",
                (document_id, path),
            ).fetchone()
            if not target:
                raise HTTPException(status_code=404, detail=f"'{path}' does not exist in this paper. Create it first.")
            rows = conn.execute("SELECT * FROM literature_references WHERE project_id = ? ORDER BY cite_key", (doc["project_id"],)).fetchall()
            current = get_text(conn, target["id"])
        existing_keys = {e.key for e in parse_bibtex(current)[0]}
        library = [entry_from_row(r) for r in rows]
        if payload.mode == "replace":
            new_text = "\n\n".join(serialize_entry(*e) for e in library) + "\n"
            added = len(library)
        else:
            missing = [e for e in library if e[1] not in existing_keys]
            added = len(missing)
            new_text = current.rstrip() + ("\n\n" if current.strip() else "") + "\n\n".join(serialize_entry(*e) for e in missing) + "\n" if missing else current
        with ctx.db.transaction() as conn:
            replace_with_history(conn, target["id"], new_text, uid, "Synced from project library")
            ctx.log_activity(conn, doc["project_id"], uid, "reference.synced", "document", document_id, f"Synced {added} references into {path}")
        return {"added": added, "path": path}

    @router.post("/references/lookup-doi")
    def lookup_doi(payload: DoiLookupRequest, request: Request, session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        """Optional Crossref lookup. Returns metadata for the user to review; never saves it automatically."""
        if not ctx.settings.doi_lookup_enabled:
            raise HTTPException(status_code=503, detail="DOI lookup is disabled on this server (DOI_LOOKUP_ENABLED=false).")
        ctx.enforce_rate_limit(request, "doi_lookup", 30, session["user_id"])
        doi = normalize_doi(payload.doi)
        if not re.fullmatch(r"10\.\d{4,9}/[^\s]+", doi):
            raise HTTPException(status_code=422, detail="That does not look like a DOI.")
        try:
            resp = httpx.get(f"https://api.crossref.org/works/{httpx.URL(doi).raw_path.decode()}", timeout=8.0,
                             headers={"User-Agent": "ResearchFlow/1.1 (DOI lookup)"})
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail="The DOI service could not be reached. Enter the details manually.") from exc
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="No record was found for this DOI.")
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="The DOI service returned an error.")
        msg = resp.json().get("message", {})
        authors = " and ".join(
            f"{a.get('family', '')}, {a.get('given', '')}".strip(", ") for a in msg.get("author", []) if a.get("family")
        )
        year = ""
        for k in ("published-print", "published-online", "issued"):
            parts = msg.get(k, {}).get("date-parts", [[None]])
            if parts and parts[0] and parts[0][0]:
                year = str(parts[0][0])
                break
        kind = {"journal-article": "article", "proceedings-article": "inproceedings", "book": "book", "book-chapter": "incollection"}.get(msg.get("type", ""), "misc")
        venue = (msg.get("container-title") or [""])[0]
        fields = {"title": (msg.get("title") or [""])[0], "author": authors, "year": year, "doi": doi,
                  "journal" if kind == "article" else "booktitle": venue, "volume": msg.get("volume", ""),
                  "number": msg.get("issue", ""), "pages": msg.get("page", ""), "publisher": msg.get("publisher", "")}
        fields = {k: v for k, v in fields.items() if v}
        return {"entry_type": kind, "fields": fields, "suggested_key": make_cite_key(authors, year, fields.get("title", ""), set())}

    return router
