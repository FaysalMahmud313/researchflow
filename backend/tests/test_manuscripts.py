"""End-to-end tests for papers: saving with conflict protection, versions, export/import,
review, bibliography, research files, permissions and cross-project views."""
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

import app.latex.textstore as textstore
from app.core.config import AppSettings
from app.main import create_app

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF_BYTES = b"%PDF-1.4\n% research article\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"


class User:
    def __init__(self, app: Any, name: str, username: str) -> None:
        self.client = TestClient(app)
        reg = self.client.post("/api/v1/auth/register", json={"full_name": name, "username": username, "email": f"{username}@lab.example.edu", "password": "SecurePass123!"})
        assert reg.status_code == 201, reg.text
        self.client.post("/api/v1/auth/verify-email", json={"token": reg.json()["dev_verification_token"]})
        login = self.client.post("/api/v1/auth/login", json={"identifier": username, "password": "SecurePass123!"})
        assert login.status_code == 200, login.text
        self.id = login.json()["user"]["id"]
        self.username = username
        self.client.headers["X-CSRF-Token"] = login.json()["csrf_token"]

    def get(self, url: str, **kw: Any) -> Any:
        return self.client.get("/api/v1" + url, **kw)

    def post(self, url: str, **kw: Any) -> Any:
        return self.client.post("/api/v1" + url, **kw)

    def put(self, url: str, **kw: Any) -> Any:
        return self.client.put("/api/v1" + url, **kw)

    def patch(self, url: str, **kw: Any) -> Any:
        return self.client.patch("/api/v1" + url, **kw)

    def delete(self, url: str, **kw: Any) -> Any:
        return self.client.delete("/api/v1" + url, **kw)


class ManuscriptPlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        settings = AppSettings(
            app_env="testing",
            session_secret_key="test-only-session-secret-key-at-least-32-bytes-long-9999",
            csrf_secret_key="test-only-csrf-secret-key-at-least-32-bytes-long-999999",
            token_hash_pepper="test-only-token-hash-pepper-32-bytes-99",
            private_storage_dir=root / "storage",
            rate_limit_auth_per_minute=500,
            rate_limit_api_per_minute=5000,
            rate_limit_upload_per_minute=500,
        )
        cls.app = create_app(settings=settings, db_path=":memory:")
        cls.owner = User(cls.app, "Dr. Grace Hopper", "ghopper")
        cls.editor = User(cls.app, "Dr. Alan Turing", "aturing")
        cls.reviewer = User(cls.app, "Dr. Rosalind Franklin", "rfranklin")
        cls.viewer = User(cls.app, "Dr. Carl Sagan", "csagan")
        cls.outsider = User(cls.app, "Mallory Intruder", "mallory")
        proj = cls.owner.post("/projects", json={"title": "Diffusion Models for Climate", "description": "Downscaling study"})
        assert proj.status_code == 201, proj.text
        cls.project_id = proj.json()["id"]
        for user, role in ((cls.editor, "editor"), (cls.reviewer, "reviewer"), (cls.viewer, "viewer")):
            inv = cls.owner.post(f"/projects/{cls.project_id}/invitations", json={"identifier": user.username, "role": role})
            assert inv.status_code == 201, inv.text
            assert user.patch(f"/invitations/{inv.json()['id']}", json={"action": "accept"}).status_code == 200

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    # ------------------------------------------------------------------
    def new_paper(self, template: str = "article", title: str = "Climate Paper") -> dict[str, Any]:
        r = self.owner.post(f"/projects/{self.project_id}/manuscripts", json={"title": title, "template": template})
        self.assertEqual(r.status_code, 201, r.text)
        return self.owner.get(f"/manuscripts/{r.json()['id']}").json()

    def file_id(self, doc: dict[str, Any], path: str) -> str:
        return next(f["id"] for f in doc["files"] if f["path"] == path)

    def save(self, user: User, fid: str, content: str, base: int) -> Any:
        return user.put(f"/manuscript-files/{fid}/content", json={"content": content, "base_revision": base})

    # ------------------------------------------------------------------
    # 1. Create, edit, save, reload
    # ------------------------------------------------------------------
    def test_01_save_and_reload(self) -> None:
        doc = self.new_paper("article")
        fid = self.file_id(doc, "main.tex")
        f = self.editor.get(f"/manuscript-files/{fid}").json()
        self.assertEqual(f["revision"], 1)
        self.assertIn("\\section{Introduction}", f["content"])
        edited = f["content"].replace("\\section{Related Work}", "Diffusion models learn to denoise.\n\n\\section{Related Work}")
        r = self.save(self.editor, fid, edited, 1)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["revision"], 2)
        again = self.viewer.get(f"/manuscript-files/{fid}").json()
        self.assertEqual(again["content"], edited)
        self.assertEqual(again["updated_by_name"], "Dr. Alan Turing")
        # Saving identical text is a no-op and keeps the revision.
        unchanged = self.save(self.editor, fid, edited, 2).json()
        self.assertEqual((unchanged["changed"], unchanged["revision"]), (False, 2))
        listed = next(m for m in self.owner.get(f"/projects/{self.project_id}/manuscripts").json()["manuscripts"] if m["id"] == doc["id"])
        self.assertEqual(listed["last_editor_name"], "Dr. Alan Turing")
        project = self.owner.get(f"/projects/{self.project_id}").json()
        self.assertEqual(project["last_editor_name"], "Dr. Alan Turing")

    # ------------------------------------------------------------------
    # 2. Conflicting saves never silently overwrite newer work
    # ------------------------------------------------------------------
    def test_02_conflicting_saves_are_rejected(self) -> None:
        doc = self.new_paper("blank", "Conflict Paper")
        fid = self.file_id(doc, "main.tex")
        base = self.owner.get(f"/manuscript-files/{fid}").json()
        # Both users opened revision 1.
        self.assertEqual(self.save(self.owner, fid, base["content"] + "% owner edit\n", 1).status_code, 200)
        conflict = self.save(self.editor, fid, base["content"] + "% editor edit\n", 1)
        self.assertEqual(conflict.status_code, 409)
        detail = conflict.json()["detail"]
        self.assertEqual(detail["current_revision"], 2)
        self.assertIn("% owner edit", detail["current_content"])
        self.assertEqual(detail["updated_by_name"], "Dr. Grace Hopper")
        stored = self.owner.get(f"/manuscript-files/{fid}").json()["content"]
        self.assertIn("% owner edit", stored)
        self.assertNotIn("% editor edit", stored)
        # After reviewing the newer version the editor can merge and save against it.
        merged = detail["current_content"] + "% editor edit\n"
        self.assertEqual(self.save(self.editor, fid, merged, detail["current_revision"]).json()["revision"], 3)
        # Roles without write access cannot save, and outsiders cannot see the file at all.
        self.assertEqual(self.save(self.reviewer, fid, "x", 3).status_code, 403)
        self.assertEqual(self.save(self.viewer, fid, "x", 3).status_code, 403)
        self.assertEqual(self.save(self.outsider, fid, "x", 3).status_code, 404)
        self.assertEqual(self.outsider.get(f"/manuscript-files/{fid}").status_code, 404)

    # ------------------------------------------------------------------
    # 3. Version history and restore
    # ------------------------------------------------------------------
    def test_03_versions_and_restore(self) -> None:
        doc = self.new_paper("blank", "Versioned Paper")
        fid = self.file_id(doc, "main.tex")
        original = self.owner.get(f"/manuscript-files/{fid}").json()["content"]
        self.save(self.owner, fid, "% second draft\n" + original, 1)
        saved = self.owner.post(f"/manuscript-files/{fid}/versions", json={"summary": "Second draft"})
        self.assertEqual(saved.status_code, 201, saved.text)
        versions = self.owner.get(f"/manuscript-files/{fid}/versions").json()["versions"]
        v1 = next(v for v in versions if v["version_number"] == 1)
        cmp = self.owner.get(f"/manuscript-files/{fid}/compare", params={"left": v1["id"], "right": "current"}).json()
        self.assertIn("+% second draft", cmp["unified_diff"])

        self.assertEqual(self.viewer.post(f"/file-versions/{v1['id']}/restore").status_code, 403)
        r = self.owner.post(f"/file-versions/{v1['id']}/restore")
        self.assertEqual(r.status_code, 200, r.text)
        current = self.owner.get(f"/manuscript-files/{fid}").json()
        self.assertEqual(current["content"], original)
        self.assertEqual(current["revision"], r.json()["revision"])
        history = self.owner.get(f"/manuscript-files/{fid}/versions").json()["versions"]
        self.assertEqual(history[0]["version_kind"], "restore")
        contents = [self.owner.get(f"/file-versions/{v['id']}").json()["content"] for v in history]
        self.assertTrue(any(c.startswith("% second draft") for c in contents), "pre-restore state must stay recoverable")
        # Editing continues from the restored revision.
        self.assertEqual(self.save(self.owner, fid, original + "% after restore\n", current["revision"]).status_code, 200)

    def test_04_auto_snapshot_after_idle_interval(self) -> None:
        doc = self.new_paper("blank", "Snapshot Paper")
        fid = self.file_id(doc, "main.tex")
        original_interval = textstore.AUTO_VERSION_INTERVAL_SECONDS
        try:
            textstore.AUTO_VERSION_INTERVAL_SECONDS = 0
            r = self.save(self.owner, fid, "% snapshot me\n", 1)
            self.assertTrue(r.json()["version_created"])
        finally:
            textstore.AUTO_VERSION_INTERVAL_SECONDS = original_interval
        kinds = [v["version_kind"] for v in self.owner.get(f"/manuscript-files/{fid}/versions").json()["versions"]]
        self.assertEqual(kinds[0], "auto")

    # ------------------------------------------------------------------
    # 4. Export: full project, flattened paper, single section, bibliography, assets
    # ------------------------------------------------------------------
    def test_05_exports(self) -> None:
        doc = self.new_paper("structured", "Export Paper")
        did = doc["id"]
        up = self.editor.post(f"/manuscripts/{did}/files/upload", files={"files": ("fig1.png", PNG_BYTES, "image/png")}, data={"folder": "figures"})
        self.assertEqual(up.status_code, 201, up.text)
        intro_id = self.file_id(self.owner.get(f"/manuscripts/{did}").json(), "sections/introduction.tex")
        intro = self.editor.get(f"/manuscript-files/{intro_id}").json()
        body = intro["content"] + (
            "We study $\\nabla \\cdot u = 0$ \\cite{ho2020}.\n\n\\begin{figure}[h]\n\\includegraphics{fig1}\n"
            "\\caption{Setup}\\label{fig:setup}\n\\end{figure}\n\n\\subsection{Scope}\nScope text.\n\\includegraphics{missing_plot}\n"
        )
        self.assertEqual(self.save(self.editor, intro_id, body, intro["revision"]).status_code, 200)

        z = self.viewer.get(f"/manuscripts/{did}/export/project.zip")
        self.assertEqual(z.status_code, 200, z.text)
        self.assertEqual(z.headers["x-export-missing"], "1")
        archive = zipfile.ZipFile(io.BytesIO(z.content))
        names = set(archive.namelist())
        root = "Export-Paper/"
        for expected in ("main.tex", "references.bib", "sections/introduction.tex", "sections/conclusion.tex", "figures/fig1.png", "README.md"):
            self.assertIn(root + expected, names)
        readme = archive.read(root + "README.md").decode()
        self.assertIn("has not been compiled", readme)
        self.assertIn("missing_plot", readme)
        self.assertEqual(archive.read(root + "figures/fig1.png"), PNG_BYTES)
        self.assertEqual(archive.read(root + "sections/introduction.tex").decode(), body)

        flat = self.owner.get(f"/manuscripts/{did}/export/paper.tex")
        self.assertIn("We study $\\nabla \\cdot u = 0$ \\cite{ho2020}.", flat.text)
        self.assertNotIn("\\input{sections/introduction}", flat.text)

        outline = self.owner.get(f"/manuscript-files/{intro_id}/outline").json()["items"]
        sec = next(i for i in outline if i["kind"] == "section")
        self.assertEqual(next(i for i in outline if i["kind"] == "figure")["label"], "fig:setup")
        section = self.owner.get(f"/manuscript-files/{intro_id}/section", params={"start": sec["start"], "end": sec["end"], "download": True})
        self.assertTrue(section.text.startswith("\\section{Introduction}"))
        self.assertIn("\\subsection{Scope}", section.text)
        self.assertIn("attachment", section.headers["content-disposition"])
        self.assertEqual(self.owner.get(f"/manuscript-files/{intro_id}/section", params={"start": 0, "end": 10_000_000}).status_code, 422)

        self.assertIn("BibTeX", self.owner.get(f"/manuscripts/{did}/export/bibliography.bib").text)
        assets = zipfile.ZipFile(io.BytesIO(self.owner.get(f"/manuscripts/{did}/export/assets.zip").content))
        self.assertEqual(assets.namelist(), ["Export-Paper-assets/figures/fig1.png"])
        deps = self.owner.get(f"/manuscripts/{did}/dependencies").json()
        self.assertEqual([m["path"] for m in deps["missing_figures"]], ["missing_plot"])
        self.assertIn("ho2020", deps["undefined_citations"])
        self.assertEqual(self.outsider.get(f"/manuscripts/{did}/export/project.zip").status_code, 404)

    # ------------------------------------------------------------------
    # 5. Import: LaTeX project ZIP, Markdown, PDF kept as an ordinary document
    # ------------------------------------------------------------------
    def test_06_imports_keep_originals(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("thesis/main.tex", "\\documentclass{article}\\begin{document}\\input{chapters/one}\\end{document}")
            zf.writestr("thesis/chapters/one.tex", "\\section{One}")
            zf.writestr("thesis/img/a.png", PNG_BYTES)
            zf.writestr("thesis/main.aux", "junk")
        r = self.editor.post(f"/projects/{self.project_id}/manuscripts/import", files={"file": ("thesis.zip", buf.getvalue(), "application/zip")})
        self.assertEqual(r.status_code, 201, r.text)
        doc = self.editor.get(f"/manuscripts/{r.json()['id']}").json()
        self.assertEqual({f["path"] for f in doc["files"]}, {"main.tex", "chapters", "chapters/one.tex", "img", "img/a.png"})
        originals = [f for f in self.editor.get(f"/projects/{self.project_id}/files").json()["files"] if f["folder"] == "/Manuscripts"]
        self.assertIn("thesis.zip", [f["original_name"] for f in originals])

        evil = io.BytesIO()
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("../../etc/passwd.tex", "x")
        self.assertEqual(self.editor.post(f"/projects/{self.project_id}/manuscripts/import", files={"file": ("evil.zip", evil.getvalue(), "application/zip")}).status_code, 400)
        self.assertEqual(self.viewer.post(f"/projects/{self.project_id}/manuscripts/import", files={"file": ("a.tex", b"x", "text/plain")}).status_code, 403)

        md = self.editor.post(f"/projects/{self.project_id}/manuscripts/import", files={"file": ("notes.md", b"# Intro\nSome *emphasis* and $x^2$ with 100% & more.\n", "text/markdown")})
        main = next(f for f in self.editor.get(f"/manuscripts/{md.json()['id']}").json()["files"] if f["path"] == "main.tex")
        tex = self.editor.get(f"/manuscript-files/{main['id']}").json()["content"]
        self.assertIn("\\section{Intro}", tex)
        self.assertIn("100\\% \\& more", tex)

        pdf = self.editor.post(f"/projects/{self.project_id}/manuscripts/import", files={"file": ("published.pdf", PDF_BYTES, "application/pdf")})
        self.assertEqual(pdf.status_code, 201, pdf.text)
        self.assertTrue(pdf.json()["stored_only"])
        download = self.viewer.post(f"/files/{pdf.json()['file_id']}/download")
        self.assertEqual(download.content, PDF_BYTES)
        self.assertEqual(download.headers["content-type"], "application/pdf")

    # ------------------------------------------------------------------
    # 6. File tree, permissions, recoverable deletion
    # ------------------------------------------------------------------
    def test_07_file_tree_and_trash(self) -> None:
        doc = self.new_paper("structured", "Tree Paper")
        did = doc["id"]
        r = self.editor.post(f"/manuscripts/{did}/files", json={"path": "appendix/proofs.tex", "content": "\\section{Proofs}"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(self.editor.post(f"/manuscripts/{did}/files", json={"path": "../escape.tex"}).status_code, 422)
        self.assertEqual(self.editor.post(f"/manuscripts/{did}/files", json={"path": "appendix/proofs.tex"}).status_code, 409)
        self.assertEqual(self.reviewer.post(f"/manuscripts/{did}/files", json={"path": "x.tex"}).status_code, 403)

        folder_id = self.file_id(self.owner.get(f"/manuscripts/{did}").json(), "sections")
        self.assertEqual(self.editor.patch(f"/manuscript-files/{folder_id}", json={"path": "chapters"}).status_code, 200)
        paths = {f["path"] for f in self.owner.get(f"/manuscripts/{did}").json()["files"]}
        self.assertIn("chapters/introduction.tex", paths)

        main_id = self.file_id(self.owner.get(f"/manuscripts/{did}").json(), "main.tex")
        self.assertEqual(self.editor.delete(f"/manuscript-files/{main_id}").status_code, 409)
        self.assertEqual(self.editor.delete(f"/manuscript-files/{folder_id}").json()["count"], 6)
        self.assertEqual(len(self.editor.get(f"/manuscripts/{did}/trash").json()["files"]), 6)
        self.assertEqual(self.editor.post(f"/manuscript-files/{folder_id}/restore").json()["count"], 6)

        self.assertEqual(self.editor.delete(f"/manuscripts/{did}").status_code, 200)
        self.assertEqual(self.owner.get(f"/projects/{self.project_id}").status_code, 200)
        self.assertEqual(self.editor.post(f"/manuscripts/{did}/restore").status_code, 200)

    def test_08_status_and_membership_rules(self) -> None:
        did = self.new_paper("blank", "Status Paper")["id"]
        self.assertEqual(self.editor.patch(f"/manuscripts/{did}/status", json={"status": "Internal Review"}).status_code, 200)
        self.assertEqual(self.editor.patch(f"/manuscripts/{did}/status", json={"status": "Submitted"}).status_code, 403)
        self.assertEqual(self.owner.patch(f"/manuscripts/{did}/status", json={"status": "Submitted"}).status_code, 200)
        self.assertEqual(self.editor.patch(f"/projects/{self.project_id}/publication-status", json={"publication_status": "Accepted"}).status_code, 403)
        self.assertEqual(self.reviewer.patch(f"/manuscripts/{did}", json={"title": "Hijacked"}).status_code, 403)
        # Only the owner removes members.
        extra = User(self.app, "Temp Member", "tempmember")
        inv = self.owner.post(f"/projects/{self.project_id}/invitations", json={"identifier": "tempmember", "role": "viewer"}).json()
        extra.patch(f"/invitations/{inv['id']}", json={"action": "accept"})
        self.assertEqual(self.editor.delete(f"/projects/{self.project_id}/members/{extra.id}").status_code, 403)
        self.assertEqual(self.owner.delete(f"/projects/{self.project_id}/members/{extra.id}").status_code, 200)
        self.assertEqual(extra.get(f"/projects/{self.project_id}").status_code, 403)

    # ------------------------------------------------------------------
    # 7. Comments and suggestions
    # ------------------------------------------------------------------
    def test_09_comments_and_suggestions(self) -> None:
        doc = self.new_paper("article", "Reviewed Paper")
        did, fid = doc["id"], self.file_id(doc, "main.tex")
        text = self.owner.get(f"/manuscript-files/{fid}").json()["content"]
        start = text.index("\\section{Methodology}")
        end = start + len("\\section{Methodology}")
        thread = self.reviewer.post(f"/manuscripts/{did}/comments", json={
            "file_id": fid, "body": "@aturing please expand this", "quoted_text": text[start:end],
            "anchor": {"from": start, "to": end, "line": text[:start].count("\n") + 1},
        })
        self.assertEqual(thread.status_code, 201, thread.text)
        self.assertEqual(thread.json()["mentions"], ["aturing"])
        self.assertTrue(any(n["kind"] == "mention" for n in self.editor.get("/notifications").json()["notifications"]))
        self.assertEqual(self.viewer.post(f"/manuscripts/{did}/comments", json={"body": "hi"}).status_code, 403)
        reply = self.editor.post(f"/manuscripts/{did}/comments", json={"parent_id": thread.json()["id"], "body": "Done."})
        self.assertEqual(reply.status_code, 201)
        self.assertEqual(self.editor.patch(f"/doc-comments/{thread.json()['id']}", json={"status": "resolved"}).status_code, 200)
        doc_comment = self.editor.post(f"/manuscripts/{did}/comments", json={"body": "Whole-paper note"})
        self.assertEqual(doc_comment.status_code, 201)

        sug = self.reviewer.post(f"/manuscripts/{did}/suggestions", json={
            "file_id": fid, "anchor": {"from": start, "to": end, "context_before": text[max(0, start - 10):start]},
            "original_text": "\\section{Methodology}", "proposed_text": "\\section{Methods}",
        })
        self.assertEqual(sug.status_code, 201, sug.text)
        self.assertEqual(self.reviewer.post(f"/doc-suggestions/{sug.json()['id']}/accept").status_code, 403)
        # The text shifts before acceptance; the suggestion is still applied in the right place.
        self.save(self.owner, fid, "% shifted\n" + text, 1)
        self.assertEqual(self.editor.post(f"/doc-suggestions/{sug.json()['id']}/accept").status_code, 200)
        after = self.owner.get(f"/manuscript-files/{fid}").json()
        self.assertIn("\\section{Methods}", after["content"])
        self.assertEqual(after["revision"], 3)

        s2 = after["content"].index("\\section{Results}")
        stale = self.reviewer.post(f"/manuscripts/{did}/suggestions", json={
            "file_id": fid, "anchor": {"from": s2, "to": s2 + 17}, "original_text": "\\section{Results}", "proposed_text": "\\section{Findings}",
        }).json()
        self.save(self.owner, fid, after["content"].replace("\\section{Results}", ""), after["revision"])
        self.assertEqual(self.editor.post(f"/doc-suggestions/{stale['id']}/accept").status_code, 409)

    # ------------------------------------------------------------------
    # 8. Bibliography
    # ------------------------------------------------------------------
    def test_10_bibliography(self) -> None:
        bib = r"""
        @string{neurips = "Advances in Neural Information Processing Systems"}
        @inproceedings{ho2020, author = {Ho, Jonathan and Jain, Ajay}, title = {Denoising Diffusion Probabilistic Models},
          booktitle = neurips, year = 2020, doi = {10.48550/arXiv.2006.11239}, customfield = {kept verbatim}}
        @article{dup_ho, title = {Denoising {D}iffusion Probabilistic Models}, author = {Ho, J.}, year = {2020}}
        @article{broken, title = {Missing brace, year = 2020
        @misc{sohl2015, author = "Sohl-Dickstein, Jascha", title = "Deep Unsupervised Learning", year = 2015}
        """
        out = self.editor.post(f"/projects/{self.project_id}/references/import-bibtex", json={"bibtex": bib}).json()
        self.assertEqual({c["cite_key"] for c in out["created"]}, {"ho2020", "sohl2015"})
        self.assertEqual(out["duplicates"][0]["key"], "dup_ho")
        self.assertTrue(out["errors"])
        exported = self.viewer.get(f"/projects/{self.project_id}/references/library.bib").text
        self.assertIn("customfield", exported)
        self.assertIn("Advances in Neural Information Processing Systems", exported)

        doc = self.new_paper("article", "Citing Paper")
        fid = self.file_id(doc, "main.tex")
        self.save(self.owner, fid, "See \\cite{ho2020, sohl2015} and \\citep[p.~3]{ho2020}.\n", 1)
        ref_id = next(r["id"] for r in self.viewer.get(f"/projects/{self.project_id}/references", params={"q": "diffusion"}).json()["references"])
        self.assertEqual(self.editor.patch(f"/references/{ref_id}/bibtex", json={"cite_key": "ho2020ddpm"}).status_code, 409)
        ok = self.editor.patch(f"/references/{ref_id}/bibtex", json={"cite_key": "ho2020ddpm", "rename_in_manuscripts": True})
        self.assertEqual(ok.status_code, 200, ok.text)
        content = self.owner.get(f"/manuscript-files/{fid}").json()["content"]
        self.assertIn("\\cite{ho2020ddpm, sohl2015}", content)
        self.assertIn("\\citep[p.~3]{ho2020ddpm}", content)

        sync = self.editor.post(f"/manuscripts/{doc['id']}/bibliography/sync", json={"path": "references.bib"})
        self.assertEqual(sync.json()["added"], 2)
        keys = {c["key"]: c["source"] for c in self.owner.get(f"/manuscripts/{doc['id']}/index").json()["citations"]}
        self.assertEqual(keys["ho2020ddpm"], "references.bib")

    # ------------------------------------------------------------------
    # 9. Research files: chunked uploads, versions, PDFs, trash
    # ------------------------------------------------------------------
    def test_11_research_files(self) -> None:
        payload = b"step,loss\n" + b"".join(f"{i},{1 / (i + 1):.6f}\n".encode() for i in range(30000))
        parts = [payload[i : i + 100_000] for i in range(0, len(payload), 100_000)]
        init = self.editor.post(f"/projects/{self.project_id}/uploads/init", json={
            "filename": "training_log.csv", "folder": "/runs", "artifact_type": "log", "total_size_bytes": len(payload), "total_chunks": len(parts)})
        uid = init.json()["upload_id"]
        put = lambda i: self.editor.client.put(f"/api/v1/uploads/{uid}/chunks/{i}", content=parts[i])  # noqa: E731
        self.assertEqual(put(0).status_code, 200)
        self.assertTrue(put(0).json()["duplicate"])
        self.assertEqual(put(2).status_code, 409)
        self.assertEqual(self.editor.post(f"/uploads/{uid}/complete").status_code, 409)
        for i in range(self.editor.get(f"/uploads/{uid}").json()["uploaded_chunks"], len(parts)):
            self.assertEqual(put(i).status_code, 200)
        fid = self.editor.post(f"/uploads/{uid}/complete").json()["file_id"]
        self.assertEqual(self.outsider.post(f"/files/{fid}/download").status_code, 403)
        self.assertEqual(self.viewer.post(f"/files/{fid}/download").content, payload)
        again = self.editor.post(f"/projects/{self.project_id}/files", files={"file": ("training_log.csv", b"step,loss\n0,1.0\n", "text/csv")}, data={"folder": "/runs"})
        self.assertEqual(again.json()["current_version"], 2)
        self.assertEqual(self.viewer.get(f"/files/{fid}/versions/1/content").content, payload)
        self.assertEqual(self.editor.patch(f"/files/{fid}", json={"original_name": "train_log.csv", "folder": "/runs/2026"}).status_code, 200)
        self.assertEqual(self.viewer.delete(f"/files/{fid}").status_code, 403)
        self.assertEqual(self.editor.delete(f"/files/{fid}").json()["status"], "trashed")
        self.assertEqual(self.editor.post(f"/files/{fid}/restore").status_code, 200)

        pdf = self.editor.post(f"/projects/{self.project_id}/files", files={"file": ("draft-v3.pdf", PDF_BYTES, "application/pdf")}, data={"folder": "/papers"})
        self.assertEqual(pdf.status_code, 201, pdf.text)
        self.assertEqual(self.viewer.post(f"/files/{pdf.json()['id']}/download").content, PDF_BYTES)

    # ------------------------------------------------------------------
    # 10. Search and cross-project views stay inside the caller's projects
    # ------------------------------------------------------------------
    def test_12_search_and_cross_project_views(self) -> None:
        self.new_paper("blank", "Zebrafish Regeneration Paper")
        self.assertEqual(len(self.viewer.get("/search", params={"q": "zebrafish"}).json()["manuscripts"]), 1)
        theirs = self.outsider.get("/search", params={"q": "zebrafish"}).json()
        self.assertTrue(all(len(v) == 0 for v in theirs.values() if isinstance(v, list)))
        self.assertTrue(self.viewer.get("/search", params={"q": "Hopper", "category": "projects"}).json()["projects"])
        self.assertTrue(all(len(v) == 0 for v in self.outsider.get("/search", params={"q": "%"}).json().values() if isinstance(v, list)))

        mine = self.viewer.get("/me/manuscripts", params={"q": "zebrafish"}).json()["manuscripts"]
        self.assertEqual([m["title"] for m in mine], ["Zebrafish Regeneration Paper"])
        self.assertEqual(self.outsider.get("/me/manuscripts").json()["manuscripts"], [])
        self.assertEqual(self.outsider.get("/me/files").json()["files"], [])
        overview = self.viewer.get("/me/overview").json()
        self.assertGreaterEqual(overview["counts"]["papers"], 1)
        self.assertEqual(self.outsider.get("/me/overview").json()["counts"]["papers"], 0)

    def test_13_notification_preferences_are_honored(self) -> None:
        doc = self.new_paper("blank", "Quiet Paper")
        self.assertEqual(self.viewer.patch("/users/me/preferences", json={"notification_preferences": {"mentions": False}}).status_code, 200)
        before = len(self.viewer.get("/notifications").json()["notifications"])
        self.editor.post(f"/manuscripts/{doc['id']}/comments", json={"body": "@csagan have a look"})
        self.assertEqual(len(self.viewer.get("/notifications").json()["notifications"]), before)
        self.viewer.patch("/users/me/preferences", json={"notification_preferences": {"mentions": True}})
        self.editor.post(f"/manuscripts/{doc['id']}/comments", json={"body": "@csagan second look"})
        self.assertEqual(len(self.viewer.get("/notifications").json()["notifications"]), before + 1)


if __name__ == "__main__":
    unittest.main()
