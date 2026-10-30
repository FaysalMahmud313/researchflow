"""Cross-project views for the sidebar: everything the caller can see across their projects.

Every query is scoped by joining `project_memberships` on the caller, so nothing from a
project the user does not belong to is ever returned.
"""
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from app.api.v1.context import ApiContext

MEMBER_JOIN = "JOIN project_memberships m ON m.project_id = {a}.project_id AND m.user_id = ? JOIN projects p ON p.id = {a}.project_id"


def _like(q: Optional[str]) -> Optional[str]:
    if not q or not q.strip():
        return None
    escaped = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def build_workspace_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter(prefix="/api/v1/me")
    auth = ctx.get_current_session_and_user

    def rows(sql: str, params: list[Any]) -> list[Dict[str, Any]]:
        with ctx.db.transaction() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    @router.get("/overview")
    def overview(session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        with ctx.db.transaction() as conn:
            counts = {
                "projects": conn.execute("SELECT COUNT(*) FROM project_memberships WHERE user_id = ?", (uid,)).fetchone()[0],
                "papers": conn.execute(
                    "SELECT COUNT(*) FROM documents d " + MEMBER_JOIN.format(a="d") + " WHERE d.doc_kind = 'latex' AND d.is_deleted = 0",  # noqa: S608 - fixed SQL text; every user value is a bound ? parameter
                    (uid,),
                ).fetchone()[0],
                "open_tasks": conn.execute(
                    "SELECT COUNT(*) FROM tasks t JOIN task_assignees ta ON ta.task_id = t.id AND ta.user_id = ? WHERE t.status != 'done'",
                    (uid,),
                ).fetchone()[0],
                "unread_notifications": conn.execute(
                    "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0", (uid,)
                ).fetchone()[0],
                "pending_invitations": conn.execute(
                    "SELECT COUNT(*) FROM project_invitations WHERE invited_user_id = ? AND status = 'pending'", (uid,)
                ).fetchone()[0],
            }
            papers = [dict(r) for r in conn.execute(
                "SELECT d.id, d.title, d.publication_status AS status, d.updated_at, d.last_editor_name, p.title AS project_title, d.project_id "
                "FROM documents d " + MEMBER_JOIN.format(a="d") + " WHERE d.doc_kind = 'latex' AND d.is_deleted = 0 "
                "ORDER BY d.updated_at DESC LIMIT 6",
                (uid,),
            ).fetchall()]
            tasks = [dict(r) for r in conn.execute(
                "SELECT t.id, t.title, t.status, t.priority, t.due_date, t.project_id, p.title AS project_title FROM tasks t "
                "JOIN task_assignees ta ON ta.task_id = t.id AND ta.user_id = ? JOIN projects p ON p.id = t.project_id "
                "WHERE t.status != 'done' ORDER BY CASE WHEN t.due_date = '' THEN 1 ELSE 0 END, t.due_date LIMIT 8",
                (uid,),
            ).fetchall()]
            activity = [dict(r) for r in conn.execute(
                "SELECT a.id, a.actor_id, a.summary, a.created_at, a.project_id, u.full_name AS actor_name, p.title AS project_title "
                "FROM activity_events a " + MEMBER_JOIN.format(a="a") + " JOIN users u ON u.id = a.actor_id "
                "ORDER BY a.created_at DESC LIMIT 12",
                (uid,),
            ).fetchall()]
        return {"counts": counts, "recent_papers": papers, "my_tasks": tasks, "activity": activity}

    @router.get("/manuscripts")
    def my_manuscripts(q: Optional[str] = Query(default=None, max_length=100), status: Optional[str] = Query(default=None, max_length=40),
                       session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        sql = ("SELECT d.id, d.title, d.publication_status AS status, d.review_status, d.updated_at, d.last_editor_name, d.project_id, "  # noqa: S608 - fixed SQL text; every user value is a bound ? parameter
               "p.title AS project_title, m.role AS my_role FROM documents d " + MEMBER_JOIN.format(a="d") +
               " WHERE d.doc_kind = 'latex' AND d.is_deleted = 0")
        params: list[Any] = [session["user_id"]]
        if (pat := _like(q)):
            sql += " AND (LOWER(d.title) LIKE ? ESCAPE '\\' OR LOWER(p.title) LIKE ? ESCAPE '\\')"
            params += [pat, pat]
        if status:
            sql += " AND d.publication_status = ?"
            params.append(status)
        return {"manuscripts": rows(sql + " ORDER BY d.updated_at DESC LIMIT 300", params)}

    @router.get("/files")
    def my_files(q: Optional[str] = Query(default=None, max_length=100), artifact_type: Optional[str] = Query(default=None, max_length=40),
                 session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        sql = ("SELECT f.id, f.project_id, f.folder, f.original_name, f.size_bytes, f.media_type, f.artifact_type, f.updated_at, "  # noqa: S608 - fixed SQL text; every user value is a bound ? parameter
               "f.current_version, p.title AS project_title, u.full_name AS owner_name FROM datasets_files f " + MEMBER_JOIN.format(a="f") +
               " JOIN users u ON u.id = f.uploaded_by_id WHERE f.is_deleted = 0")
        params: list[Any] = [session["user_id"]]
        if (pat := _like(q)):
            sql += " AND LOWER(f.original_name) LIKE ? ESCAPE '\\'"
            params.append(pat)
        if artifact_type:
            sql += " AND f.artifact_type = ?"
            params.append(artifact_type)
        return {"files": rows(sql + " ORDER BY f.updated_at DESC LIMIT 500", params)}

    @router.get("/artifacts")
    def my_artifacts(session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        items = rows(
            "SELECT a.id, a.project_id, a.name, a.artifact_type, a.language, a.linked_code_version, a.metrics_json, a.updated_at, "  # noqa: S608 - fixed SQL text; every user value is a bound ? parameter
            "a.last_editor_name, p.title AS project_title FROM research_artifacts a " + MEMBER_JOIN.format(a="a") +
            " ORDER BY a.updated_at DESC LIMIT 300",
            [session["user_id"]],
        )
        for it in items:
            it["metrics"] = json.loads(it.pop("metrics_json") or "{}")
        return {"artifacts": items}

    @router.get("/references")
    def my_references(q: Optional[str] = Query(default=None, max_length=100), session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        sql = ("SELECT r.id, r.project_id, r.cite_key, r.title, r.authors, r.year, r.doi, r.journal_or_conference, p.title AS project_title "
               "FROM literature_references r " + MEMBER_JOIN.format(a="r"))
        params: list[Any] = [session["user_id"]]
        if (pat := _like(q)):
            sql += (" WHERE (LOWER(r.title) LIKE ? ESCAPE '\\' OR LOWER(r.authors) LIKE ? ESCAPE '\\' "
                    "OR LOWER(r.doi) LIKE ? ESCAPE '\\' OR LOWER(r.cite_key) LIKE ? ESCAPE '\\')")
            params += [pat] * 4
        return {"references": rows(sql + " ORDER BY r.year DESC, r.title LIMIT 500", params)}

    @router.get("/experiments")
    def my_experiments(session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        return {"experiments": rows(
            "SELECT e.id, e.project_id, e.name, e.method_or_model, e.dataset_ref, e.dataset_version, e.status, e.created_at, "  # noqa: S608 - fixed SQL text; every user value is a bound ? parameter
            "p.title AS project_title FROM experiment_runs e " + MEMBER_JOIN.format(a="e") + " ORDER BY e.created_at DESC LIMIT 300",
            [session["user_id"]],
        )}

    @router.get("/tasks")
    def my_tasks(assigned: bool = Query(default=False), session: Dict[str, Any] = Depends(auth)) -> Dict[str, Any]:
        uid = session["user_id"]
        if assigned:
            sql = ("SELECT t.id, t.project_id, t.title, t.status, t.priority, t.due_date, p.title AS project_title FROM tasks t "
                   "JOIN task_assignees ta ON ta.task_id = t.id AND ta.user_id = ? JOIN projects p ON p.id = t.project_id")
        else:
            sql = ("SELECT t.id, t.project_id, t.title, t.status, t.priority, t.due_date, p.title AS project_title FROM tasks t "  # noqa: S608 - fixed SQL text; every user value is a bound ? parameter
                   + MEMBER_JOIN.format(a="t"))
        return {"tasks": rows(sql + " ORDER BY t.status = 'done', t.updated_at DESC LIMIT 500", [uid])}

    return router
