import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import AppSettings, ConfigurationError
from app.main import create_app


class ResearchFlowSecurityAndWorkflowTests(unittest.TestCase):
    """End-to-end positive and negative security tests for ResearchFlow backend."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.temp_dir.name) / "private_uploads"
        self.settings = AppSettings(
            app_env="testing",
            session_secret_key="test-only-session-secret-key-at-least-32-bytes-long-9999",
            csrf_secret_key="test-only-csrf-secret-key-at-least-32-bytes-long-999999",
            token_hash_pepper="test-only-token-hash-pepper-32-bytes-99",
            private_storage_dir=self.storage_dir,
            max_upload_size_bytes=1024 * 1024,  # 1 MB
            project_storage_quota_bytes=2 * 1024 * 1024,  # 2 MB
            rate_limit_auth_per_minute=12,
        )
        self.app = create_app(settings=self.settings, db_path=":memory:")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _register_and_login(
        self, full_name: str, username: str, email: str, password: str = "SecurePass123!"
    ) -> tuple[TestClient, dict, str]:
        client = TestClient(self.app)
        reg = client.post(
            "/api/v1/auth/register",
            json={
                "full_name": full_name,
                "username": username,
                "email": email,
                "password": password,
            },
        )
        self.assertEqual(reg.status_code, 201, reg.text)
        reg_data = reg.json()
        # Verify email with one-time token
        ver = client.post(
            "/api/v1/auth/verify-email",
            json={"token": reg_data["dev_verification_token"]},
        )
        self.assertEqual(ver.status_code, 200, ver.text)

        # Re-using verification token must fail (one-time use)
        ver_again = client.post(
            "/api/v1/auth/verify-email",
            json={"token": reg_data["dev_verification_token"]},
        )
        self.assertEqual(ver_again.status_code, 400)

        login = client.post(
            "/api/v1/auth/login",
            json={"identifier": username, "password": password},
        )
        self.assertEqual(login.status_code, 200, login.text)
        login_data = login.json()
        csrf = login_data["csrf_token"]
        return client, login_data["user"], csrf

    def test_01_configuration_validation_fails_safely_in_production(self) -> None:
        """Production settings must reject placeholder secrets, HTTP origins, SQLite, or superuser DB URLs."""
        with self.assertRaises(ConfigurationError):
            bad_prod = AppSettings(
                app_env="production",
                frontend_origin="https://researchflow.example.edu",
                database_url="postgresql+psycopg://researchflow:pass@db:5432/rf",
                session_cookie_secure=True,
                session_secret_key="REPLACE_WITH_64_CHAR_RANDOM_SECRET_GENERATED_LOCALLY_DO_NOT_COMMIT",
            )
            bad_prod.validate()

        with self.assertRaises(ConfigurationError):
            superuser_prod = AppSettings(
                app_env="production",
                frontend_origin="https://researchflow.example.edu",
                database_url="postgresql+psycopg://postgres:pass@db:5432/rf",
                session_cookie_secure=True,
                session_secret_key="a" * 48,
                csrf_secret_key="b" * 48,
                token_hash_pepper="c" * 32,
            )
            superuser_prod.validate()

    def test_02_auth_rate_limiting_and_password_reset_revokes_sessions(self) -> None:
        """Login rate limiting blocks brute-force, and password reset revokes active sessions."""
        client, user, csrf = self._register_and_login("Dr. Ada Lovelace", "ada_lovelace", "ada@ox.ac.uk")
        # Request password reset
        forgot = client.post("/api/v1/auth/forgot-password", json={"email": "ada@ox.ac.uk"})
        self.assertEqual(forgot.status_code, 200)
        reset_token = forgot.json()["dev_reset_token"]

        # Reset password
        reset_res = client.post(
            "/api/v1/auth/reset-password",
            json={"token": reset_token, "new_password": "NewStrongPassword456!"},
        )
        self.assertEqual(reset_res.status_code, 200)

        # Previous session must now be revoked (401)
        me_after_reset = client.get("/api/v1/auth/me")
        self.assertEqual(me_after_reset.status_code, 401)

        # Brute-force rate limit check on login
        self.app.state.rate_limiter.reset()
        anon = TestClient(self.app)
        for _ in range(12):
            r = anon.post("/api/v1/auth/login", json={"identifier": "ada_lovelace", "password": "wrong"})
            self.assertEqual(r.status_code, 401)
        rate_limited = anon.post("/api/v1/auth/login", json={"identifier": "ada_lovelace", "password": "wrong"})
        self.assertEqual(rate_limited.status_code, 429)

    def test_03_csrf_protection_enforced_on_state_changing_endpoints(self) -> None:
        """Cookie-authenticated POST/PATCH/DELETE requests without valid X-CSRF-Token must be rejected (403)."""
        client, _, csrf = self._register_and_login("Dr. Alan Turing", "alan_turing", "alan@cam.ac.uk")
        # Attempt project creation WITHOUT X-CSRF-Token header
        no_csrf = client.post(
            "/api/v1/projects",
            json={"title": "Enigma Cryptanalysis", "research_domain": "Cryptography"},
        )
        self.assertEqual(no_csrf.status_code, 403)

        # With valid X-CSRF-Token header succeeds
        with_csrf = client.post(
            "/api/v1/projects",
            headers={"X-CSRF-Token": csrf},
            json={"title": "Enigma Cryptanalysis", "research_domain": "Cryptography"},
        )
        self.assertEqual(with_csrf.status_code, 201)

    def test_04_multi_user_collaboration_invitations_and_rbac_matrix(self) -> None:
        """Verify Owner, Editor, Reviewer, Viewer permissions and pending invitation isolation."""
        owner_c, owner_u, owner_csrf = self._register_and_login("Owner PI", "pi_owner", "owner@lab.edu")
        editor_c, editor_u, editor_csrf = self._register_and_login("Editor Researcher", "res_editor", "editor@lab.edu")
        reviewer_c, reviewer_u, reviewer_csrf = self._register_and_login("Peer Reviewer", "peer_rev", "reviewer@lab.edu")
        viewer_c, viewer_u, viewer_csrf = self._register_and_login("Lab Viewer", "lab_viewer", "viewer@lab.edu")
        outsider_c, outsider_u, outsider_csrf = self._register_and_login("Outsider User", "outsider", "out@other.edu")

        # Owner creates Project A
        proj_res = owner_c.post(
            "/api/v1/projects",
            headers={"X-CSRF-Token": owner_csrf},
            json={
                "title": "Neural Climate Downscaling",
                "description": "High-resolution precipitation forecasting",
                "research_domain": "Climate Informatics",
                "research_questions": ["Can diffusion models preserve extremes?"],
                "objectives": ["Benchmark ERA5 dataset"],
                "hypothesis": "Physics-informed loss reduces tail error by 18%",
                "keywords": ["climate", "diffusion"],
            },
        )
        self.assertEqual(proj_res.status_code, 201)
        project_id = proj_res.json()["id"]

        # Owner invites Editor, Reviewer, and Viewer
        inv_editor = owner_c.post(
            f"/api/v1/projects/{project_id}/invitations",
            headers={"X-CSRF-Token": owner_csrf},
            json={"identifier": "res_editor", "role": "editor"},
        ).json()
        inv_reviewer = owner_c.post(
            f"/api/v1/projects/{project_id}/invitations",
            headers={"X-CSRF-Token": owner_csrf},
            json={"identifier": "peer_rev", "role": "reviewer"},
        ).json()
        inv_viewer = owner_c.post(
            f"/api/v1/projects/{project_id}/invitations",
            headers={"X-CSRF-Token": owner_csrf},
            json={"identifier": "lab_viewer", "role": "viewer"},
        ).json()

        # Before accepting invitation, Editor CANNOT view project (pending invitation != membership)
        pre_accept = editor_c.get(f"/api/v1/projects/{project_id}")
        self.assertEqual(pre_accept.status_code, 403)

        # Outsider cannot accept someone else's invitation
        hijack = outsider_c.patch(
            f"/api/v1/invitations/{inv_editor['id']}",
            headers={"X-CSRF-Token": outsider_csrf},
            json={"action": "accept"},
        )
        self.assertEqual(hijack.status_code, 403)

        # Editor, Reviewer, Viewer accept their invitations
        for c, csrf, inv in (
            (editor_c, editor_csrf, inv_editor),
            (reviewer_c, reviewer_csrf, inv_reviewer),
            (viewer_c, viewer_csrf, inv_viewer),
        ):
            acc = c.patch(
                f"/api/v1/invitations/{inv['id']}",
                headers={"X-CSRF-Token": csrf},
                json={"action": "accept"},
            )
            self.assertEqual(acc.status_code, 200)

        # Editor can create tasks, documents, references, and experiments
        task_res = editor_c.post(
            f"/api/v1/projects/{project_id}/tasks",
            headers={"X-CSRF-Token": editor_csrf},
            json={"title": "Preprocess ERA5 tensors", "priority": "high", "assignee_ids": [editor_u["id"]]},
        )
        self.assertEqual(task_res.status_code, 201)

        # Reviewer and Viewer CANNOT create tasks (403)
        for c, csrf in ((reviewer_c, reviewer_csrf), (viewer_c, viewer_csrf)):
            denied_task = c.post(
                f"/api/v1/projects/{project_id}/tasks",
                headers={"X-CSRF-Token": csrf},
                json={"title": "Unauthorized task"},
            )
            self.assertEqual(denied_task.status_code, 403)

        # Reviewer CAN post review comments, but Viewer CANNOT
        rev_comment = reviewer_c.post(
            f"/api/v1/projects/{project_id}/comments",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"target_type": "task", "target_id": task_res.json()["id"], "body": "Verified spatial resolution."},
        )
        self.assertEqual(rev_comment.status_code, 201)

        view_comment = viewer_c.post(
            f"/api/v1/projects/{project_id}/comments",
            headers={"X-CSRF-Token": viewer_csrf},
            json={"target_type": "task", "target_id": task_res.json()["id"], "body": "Viewer comment attempt"},
        )
        self.assertEqual(view_comment.status_code, 403)

        # Editor CANNOT delete the project or invite members (Owner only)
        editor_del = editor_c.delete(f"/api/v1/projects/{project_id}", headers={"X-CSRF-Token": editor_csrf})
        self.assertEqual(editor_del.status_code, 403)

        # Removing a member immediately revokes access
        rem = owner_c.delete(
            f"/api/v1/projects/{project_id}/members/{viewer_u['id']}",
            headers={"X-CSRF-Token": owner_csrf},
        )
        self.assertEqual(rem.status_code, 200)
        after_rem = viewer_c.get(f"/api/v1/projects/{project_id}")
        self.assertEqual(after_rem.status_code, 403)

    def test_05_document_xss_sanitization_and_version_conflict_detection(self) -> None:
        """Rich text sanitizer strips scripts/handlers and optimistic locking rejects stale base_version."""
        client, _, csrf = self._register_and_login("Doc Author", "doc_author", "doc@lab.edu")
        proj_id = client.post(
            "/api/v1/projects",
            headers={"X-CSRF-Token": csrf},
            json={"title": "Manuscript Workspace"},
        ).json()["id"]

        malicious_html = (
            '<h2>Methodology</h2><script>alert("xss")</script>'
            '<p onclick="evil()">Clean paragraph <a href="javascript:alert(1)">Bad Link</a> '
            '<a href="https://doi.org/10.1038/nature">Valid DOI</a></p>'
        )
        doc_res = client.post(
            f"/api/v1/projects/{proj_id}/documents",
            headers={"X-CSRF-Token": csrf},
            json={"title": "Draft Paper", "content_html": malicious_html},
        )
        self.assertEqual(doc_res.status_code, 201)
        doc = doc_res.json()
        self.assertNotIn("<script>", doc["content_html"])
        self.assertNotIn("onclick", doc["content_html"])
        self.assertNotIn("javascript:", doc["content_html"])
        self.assertIn("https://doi.org/10.1038/nature", doc["content_html"])

        # Update v1 -> v2 succeeds
        upd_v2 = client.patch(
            f"/api/v1/documents/{doc['id']}",
            headers={"X-CSRF-Token": csrf},
            json={
                "content_html": "<h2>Methodology</h2><p>Updated section v2.</p>",
                "base_version": 1,
                "change_summary": "Added baseline equations",
            },
        )
        self.assertEqual(upd_v2.status_code, 200)
        self.assertEqual(upd_v2.json()["current_version"], 2)

        # Concurrent stale edit with base_version=1 must fail with 409 Conflict
        stale_upd = client.patch(
            f"/api/v1/documents/{doc['id']}",
            headers={"X-CSRF-Token": csrf},
            json={
                "content_html": "<p>Overwriting with stale base_version=1</p>",
                "base_version": 1,
            },
        )
        self.assertEqual(stale_upd.status_code, 409)

    def test_06_private_file_upload_security_and_cross_project_idor_prevention(self) -> None:
        """User in Project A cannot access Project B files; executable/HTML/spoofed files are blocked."""
        alice_c, _, alice_csrf = self._register_and_login("Alice", "alice_res", "alice@lab.edu")
        bob_c, _, bob_csrf = self._register_and_login("Bob", "bob_res", "bob@lab.edu")

        res_a = alice_c.post(
            "/api/v1/projects",
            headers={"X-CSRF-Token": alice_csrf},
            json={"title": "Alice Project A"},
        )
        self.assertEqual(res_a.status_code, 201)
        proj_b = bob_c.post(
            "/api/v1/projects",
            headers={"X-CSRF-Token": bob_csrf},
            json={"title": "Bob Private Project B"},
        ).json()["id"]

        # Bob uploads a valid PDF to Project B
        valid_pdf = b"%PDF-1.7\\n1 0 obj\\n<< /Type /Catalog >>\\nendobj\\n%%EOF"
        upload_res = bob_c.post(
            f"/api/v1/projects/{proj_b}/files",
            headers={"X-CSRF-Token": bob_csrf},
            files={"file": ("supplementary_proofs.pdf", valid_pdf, "application/pdf")},
            data={"folder": "/papers", "description": "Appendix proofs"},
        )
        self.assertEqual(upload_res.status_code, 201, upload_res.text)
        file_b_id = upload_res.json()["id"]

        # Alice (Project A owner, not in Project B) attempts IDOR download & deletion of Bob's file
        idor_download = alice_c.post(
            f"/api/v1/files/{file_b_id}/download",
            headers={"X-CSRF-Token": alice_csrf},
        )
        self.assertEqual(idor_download.status_code, 403)

        idor_delete = alice_c.delete(
            f"/api/v1/files/{file_b_id}",
            headers={"X-CSRF-Token": alice_csrf},
        )
        self.assertEqual(idor_delete.status_code, 403)

        # Spoofed PDF containing HTML/script is rejected
        spoofed_pdf = b"<script>alert(1)</script>"
        bad_upload = bob_c.post(
            f"/api/v1/projects/{proj_b}/files",
            headers={"X-CSRF-Token": bob_csrf},
            files={"file": ("exploit.pdf", spoofed_pdf, "application/pdf")},
        )
        self.assertEqual(bad_upload.status_code, 400)

        # Path traversal filename is rejected
        traversal_upload = bob_c.post(
            f"/api/v1/projects/{proj_b}/files",
            headers={"X-CSRF-Token": bob_csrf},
            files={"file": ("../../etc/passwd.txt", b"safe text", "text/plain")},
        )
        self.assertEqual(traversal_upload.status_code, 400)


    def test_07_theme_preferences_sessions_and_expanded_search_isolation(self) -> None:
        """Theme/accent preferences persist across reload; global search covers 7 categories and enforces project isolation."""
        alice_c, alice_u, alice_csrf = self._register_and_login("Dr. Alice Vance", "alice_v", "alice_v@lab.edu")
        bob_c, bob_u, bob_csrf = self._register_and_login("Dr. Bob Stone", "bob_s", "bob_s@lab.edu")

        # 1. Save theme, accent, density, and notification preferences
        pref_res = alice_c.patch(
            "/api/v1/users/me/preferences",
            headers={"X-CSRF-Token": alice_csrf},
            json={
                "theme_mode": "dark",
                "accent_color": "teal",
                "ui_density": "compact",
                "reduced_motion": True,
                "notification_preferences": {
                    "invitations": True,
                    "task_assignments": True,
                    "mentions": True,
                    "comments": False,
                },
            },
        )
        self.assertEqual(pref_res.status_code, 200, pref_res.text)

        # Verify persistence via GET /api/v1/users/me
        me_res = alice_c.get("/api/v1/users/me")
        self.assertEqual(me_res.status_code, 200)
        prof = me_res.json()["profile"]
        self.assertEqual(prof["theme_mode"], "dark")
        self.assertEqual(prof["accent_color"], "teal")
        self.assertEqual(prof["ui_density"], "compact")
        self.assertTrue(prof["reduced_motion"])

        # 2. Verify active session listing and revocation
        sessions_res = alice_c.get("/api/v1/users/me/sessions")
        self.assertEqual(sessions_res.status_code, 200)
        self.assertEqual(len(sessions_res.json()["sessions"]), 1)
        self.assertTrue(sessions_res.json()["sessions"][0]["is_current"])

        # 3. Create private project & resources for Bob, and ensure Alice's global search NEVER leaks Bob's resources
        bob_proj = bob_c.post(
            "/api/v1/projects",
            headers={"X-CSRF-Token": bob_csrf},
            json={"title": "Classified Quantum Photonics", "research_domain": "Quantum Optics"},
        ).json()["id"]
        bob_c.post(
            f"/api/v1/projects/{bob_proj}/tasks",
            headers={"X-CSRF-Token": bob_csrf},
            json={"title": "Quantum Cryostat Calibration"},
        )
        bob_c.post(
            f"/api/v1/projects/{bob_proj}/experiments",
            headers={"X-CSRF-Token": bob_csrf},
            json={"name": "Photon Entanglement Run 9", "method_or_model": "QKD-Stabilizer"},
        )

        # Bob finds his own project, task, and experiment in global search
        bob_search = bob_c.get("/api/v1/search?q=Quantum").json()
        self.assertEqual(len(bob_search["projects"]), 1)
        self.assertEqual(len(bob_search["tasks"]), 1)

        # Alice searches for "Quantum" and must get ZERO results from Bob's private project
        alice_search = alice_c.get("/api/v1/search?q=Quantum").json()
        self.assertEqual(len(alice_search["projects"]), 0)
        self.assertEqual(len(alice_search["tasks"]), 0)
        self.assertEqual(len(alice_search["experiments"]), 0)
        self.assertEqual(len(alice_search["files"]), 0)


    def test_08_chunked_uploads_trash_restore_linked_warnings_latex_and_code_diff(self) -> None:
        """Verify chunked resumable uploads, Trash/restore, linked-file deletion warning, LaTeX export, and code diff."""
        client, user, csrf = self._register_and_login("Dr. Elena Vance", "elena_v3", "elena_v3@lab.edu")
        proj_id = client.post(
            "/api/v1/projects",
            headers={"X-CSRF-Token": csrf},
            json={
                "title": "Monsoon Physics-Informed Diffusion",
                "description": "High-resolution precipitation downscaling over South Asia.",
                "keywords": ["diffusion", "monsoon"],
            },
        ).json()["id"]

        # 1. Chunked / resumable upload of a multi-chunk LaTeX .tex file
        init_res = client.post(
            f"/api/v1/projects/{proj_id}/uploads/init",
            headers={"X-CSRF-Token": csrf},
            json={
                "filename": "manuscript_main.tex",
                "folder": "/manuscript",
                "artifact_type": "manuscript",
                # Exact size of the two chunks below; the server now rejects data beyond the declared size.
                "total_size_bytes": len(b"\\documentclass{article}\n") + len(b"\\begin{document}Hello\\end{document}"),
                "total_chunks": 2,
            },
        )
        self.assertEqual(init_res.status_code, 201, init_res.text)
        upload_id = init_res.json()["upload_id"]

        c0 = client.put(
            f"/api/v1/uploads/{upload_id}/chunks/0",
            headers={"X-CSRF-Token": csrf},
            content=b"\\documentclass{article}\n",
        )
        self.assertEqual(c0.status_code, 200)
        c1 = client.put(
            f"/api/v1/uploads/{upload_id}/chunks/1",
            headers={"X-CSRF-Token": csrf},
            content=b"\\begin{document}Hello\\end{document}",
        )
        self.assertEqual(c1.status_code, 200)

        comp = client.post(f"/api/v1/uploads/{upload_id}/complete", headers={"X-CSRF-Token": csrf})
        self.assertEqual(comp.status_code, 200, comp.text)
        file_id = comp.json()["file_id"]

        # 2. Link file to an experiment and verify deletion is blocked without force=true (409 Conflict)
        link_res = client.patch(
            f"/api/v1/files/{file_id}",
            headers={"X-CSRF-Token": csrf},
            json={"linked_entity_type": "experiment", "linked_entity_id": "exp_503"},
        )
        self.assertEqual(link_res.status_code, 200)

        warn_del = client.delete(f"/api/v1/files/{file_id}", headers={"X-CSRF-Token": csrf})
        self.assertEqual(warn_del.status_code, 409)

        # Force soft-delete moves to Trash, and restore recovers it
        trash_del = client.delete(f"/api/v1/files/{file_id}?force=true", headers={"X-CSRF-Token": csrf})
        self.assertEqual(trash_del.status_code, 200)
        self.assertEqual(trash_del.json()["status"], "trashed")

        restore_res = client.post(f"/api/v1/files/{file_id}/restore", headers={"X-CSRF-Token": csrf})
        self.assertEqual(restore_res.status_code, 200)

        # 3. Create document + reference and test full-paper and section-level LaTeX export
        client.post(
            f"/api/v1/projects/{proj_id}/references",
            headers={"X-CSRF-Token": csrf},
            json={"title": "Score-Based Generative Modeling", "authors": "Song, Y.", "year": 2021, "doi": "10.1000/sde"},
        )
        doc_id = client.post(
            f"/api/v1/projects/{proj_id}/documents",
            headers={"X-CSRF-Token": csrf},
            json={
                "title": "Spectral Conservation Paper",
                "content_html": "<h2>Introduction</h2><p>Monsoon extremes.</p><h2>Methodology</h2><p>Spectral penalty Eq. 1.</p>",
            },
        ).json()["id"]

        full_tex = client.get(f"/api/v1/documents/{doc_id}/latex?template=ieee&section=all")
        self.assertEqual(full_tex.status_code, 200)
        self.assertIn("\\documentclass[conference]{IEEEtran}", full_tex.json()["latex_source"])
        self.assertIn("\\section{Methodology}", full_tex.json()["latex_source"])
        self.assertIn("@article{song2021", full_tex.json()["bibtex_source"])

        sec_tex = client.get(f"/api/v1/documents/{doc_id}/latex?template=article&section=Methodology")
        self.assertEqual(sec_tex.status_code, 200)
        self.assertIn("\\section{Methodology}", sec_tex.json()["latex_source"])
        self.assertNotIn("\\section{Introduction}", sec_tex.json()["latex_source"])

        # 4. Side-by-side Code Diff
        diff_res = client.post(
            f"/api/v1/projects/{proj_id}/compare/code",
            headers={"X-CSRF-Token": csrf},
            json={
                "left_title": "trainer.py (v1)",
                "right_title": "trainer.py (v2)",
                "left_code": "lr = 1e-3\nloss = l2_loss(pred, target)\n",
                "right_code": "lr = 1e-4\nloss = l2_loss(pred, target) + 0.25 * div_penalty(pred)\n",
            },
        )
        self.assertEqual(diff_res.status_code, 200)
        self.assertGreaterEqual(diff_res.json()["stats"]["modified"], 1)

    def test_09_publication_status_owner_only_member_rules_raise_hand_and_last_editor(self) -> None:
        """Verify Owner-only publication status, non-owner invite vs non-owner remove denial, Raise Hand, and last editor."""
        owner_c, owner_u, owner_csrf = self._register_and_login("Dr. Owner PI", "pi_v3", "pi_v3@lab.edu")
        editor_c, editor_u, editor_csrf = self._register_and_login("Marcus Editor", "marcus_v3", "marcus_v3@lab.edu")
        viewer_c, viewer_u, viewer_csrf = self._register_and_login("Sam Viewer", "sam_v3", "sam_v3@lab.edu")
        guest_c, guest_u, guest_csrf = self._register_and_login("Nadia Guest", "nadia_v3", "nadia_v3@lab.edu")

        proj_id = owner_c.post(
            "/api/v1/projects",
            headers={"X-CSRF-Token": owner_csrf},
            json={"title": "Allosteric GNN Benchmark", "research_domain": "Structural Bio"},
        ).json()["id"]

        # Owner invites Editor, Editor accepts
        inv1 = owner_c.post(
            f"/api/v1/projects/{proj_id}/invitations",
            headers={"X-CSRF-Token": owner_csrf},
            json={"identifier": "marcus_v3", "role": "editor"},
        ).json()
        editor_c.patch(f"/api/v1/invitations/{inv1['id']}", headers={"X-CSRF-Token": editor_csrf}, json={"action": "accept"})

        # Editor CAN invite a Viewer (within Editor's authority), and Viewer accepts
        inv2 = editor_c.post(
            f"/api/v1/projects/{proj_id}/invitations",
            headers={"X-CSRF-Token": editor_csrf},
            json={"identifier": "sam_v3", "role": "viewer"},
        )
        self.assertEqual(inv2.status_code, 201, inv2.text)
        viewer_c.patch(
            f"/api/v1/invitations/{inv2.json()['id']}",
            headers={"X-CSRF-Token": viewer_csrf},
            json={"action": "accept"},
        )

        # Viewer CANNOT invite someone with a higher role ('editor') -> 403 Forbidden
        escalate_inv = viewer_c.post(
            f"/api/v1/projects/{proj_id}/invitations",
            headers={"X-CSRF-Token": viewer_csrf},
            json={"identifier": "nadia_v3", "role": "editor"},
        )
        self.assertEqual(escalate_inv.status_code, 403)

        # Editor CANNOT remove any existing project member -> 403 Forbidden
        editor_remove_attempt = editor_c.delete(
            f"/api/v1/projects/{proj_id}/members/{viewer_u['id']}",
            headers={"X-CSRF-Token": editor_csrf},
        )
        self.assertEqual(editor_remove_attempt.status_code, 403)

        # Editor CANNOT change project publication status -> 403 Forbidden
        editor_pub_attempt = editor_c.patch(
            f"/api/v1/projects/{proj_id}/publication-status",
            headers={"X-CSRF-Token": editor_csrf},
            json={"publication_status": "Published"},
        )
        self.assertEqual(editor_pub_attempt.status_code, 403)

        # Owner CAN update project publication status to 'Submitted' -> 200 OK
        owner_pub = owner_c.patch(
            f"/api/v1/projects/{proj_id}/publication-status",
            headers={"X-CSRF-Token": owner_csrf},
            json={"publication_status": "Submitted"},
        )
        self.assertEqual(owner_pub.status_code, 200)
        self.assertEqual(owner_pub.json()["publication_status"], "Submitted")

        # Editor performs a task creation -> updates project's last_editor_name to 'Marcus Editor'
        editor_c.post(
            f"/api/v1/projects/{proj_id}/tasks",
            headers={"X-CSRF-Token": editor_csrf},
            json={"title": "Run MD trajectory equilibration"},
        )

        # Viewing the project as Viewer does NOT overwrite last_editor_name
        viewer_c.get(f"/api/v1/projects/{proj_id}")

        # Combined search by member ('marcus_v3') and filter by publication_status ('Submitted')
        filtered = owner_c.get("/api/v1/projects?member=marcus_v3&publication_status=Submitted").json()["projects"]
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["last_editor_name"], "Marcus Editor")

        # Guest raises a Research Hand -> succeeds once, duplicate blocked with 409, withdrawal succeeds
        sig1 = guest_c.post(
            f"/api/v1/projects/{proj_id}/collaboration-signals",
            headers={"X-CSRF-Token": guest_csrf},
            json={"message": "Can contribute cryo-EM docking scripts", "proposed_contribution": "Docking validation"},
        )
        self.assertEqual(sig1.status_code, 201)

        sig_dup = guest_c.post(
            f"/api/v1/projects/{proj_id}/collaboration-signals",
            headers={"X-CSRF-Token": guest_csrf},
            json={"message": "Duplicate click"},
        )
        self.assertEqual(sig_dup.status_code, 409)

        # Raising a hand must NOT grant Guest access to private project files
        guest_files = guest_c.get(f"/api/v1/projects/{proj_id}/files")
        self.assertEqual(guest_files.status_code, 403)

        withdraw = guest_c.delete(
            f"/api/v1/projects/{proj_id}/collaboration-signals/me",
            headers={"X-CSRF-Token": guest_csrf},
        )
        self.assertEqual(withdraw.status_code, 200)


if __name__ == "__main__":
    unittest.main()
