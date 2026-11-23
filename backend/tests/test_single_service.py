"""One-process deployment: the API serving the built web app, and the thread-free WSGI adapter."""
import io
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

import anyio.to_thread
import httpx
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import AppSettings, ConfigurationError
from app.main import create_app
from app.wsgi_adapter import SingleThreadedWSGI, run_blocking_calls_inline

PASSWORD = "SecurePass123!"


def settings(tmp: str, **extra: object) -> AppSettings:
    return AppSettings(
        app_env="testing",
        session_secret_key="test-only-session-secret-key-at-least-32-bytes-long-9999",
        csrf_secret_key="test-only-csrf-secret-key-at-least-32-bytes-long-999999",
        token_hash_pepper="test-only-token-hash-pepper-32-bytes-99",
        private_storage_dir=Path(tmp) / "storage",
        **extra,  # type: ignore[arg-type]
    )


def make_web_dir(tmp: str) -> Path:
    web = Path(tmp) / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>ResearchFlow</title><div id=root></div>", encoding="utf-8")
    (web / "assets" / "index-abc123.js").write_text("console.log('app')", encoding="utf-8")
    (web / "theme-init.js").write_text("// theme", encoding="utf-8")
    (Path(tmp) / "secret.txt").write_text("outside the web folder", encoding="utf-8")
    return web


class WebAppServingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        web = make_web_dir(self.tmp.name)
        self.app = create_app(settings(self.tmp.name, frontend_dist_dir=str(web)), db_path=":memory:")
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_pages_and_assets(self) -> None:
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("ResearchFlow", home.text)
        self.assertTrue(home.headers["content-type"].startswith("text/html"))
        self.assertEqual(home.headers["cache-control"], "no-cache")
        self.assertIn("script-src 'self'", home.headers["content-security-policy"])
        self.assertEqual(home.headers["x-content-type-options"], "nosniff")

        asset = self.client.get("/assets/index-abc123.js")
        self.assertTrue(asset.headers["content-type"].startswith("text/javascript"))
        self.assertIn("immutable", asset.headers["cache-control"])
        self.assertEqual(self.client.get("/theme-init.js").headers["cache-control"], "no-cache")

        self.assertEqual(self.client.get("/some/page").text, home.text)  # unknown page: the app shell
        self.assertEqual(self.client.get("/assets/missing.js").status_code, 404)  # unknown file: 404

    def test_api_still_wins_and_nothing_escapes_the_folder(self) -> None:
        self.assertEqual(self.client.get("/api/v1/health").json()["status"], "ok")
        missing = self.client.get("/api/v1/does-not-exist")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json(), {"detail": "Not Found"})
        for sneaky in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt", "/assets/%2e%2e/%2e%2e/secret.txt"):
            res = self.client.get(sneaky)
            self.assertNotIn("outside the web folder", res.text, sneaky)

    def test_without_a_web_folder_the_root_redirects(self) -> None:
        app = create_app(settings(self.tmp.name), db_path=":memory:")
        res = TestClient(app).get("/", follow_redirects=False)
        self.assertEqual(res.status_code, 307)
        self.assertEqual(res.headers["location"], "http://localhost:5173")

    def test_journal_mode_setting(self) -> None:
        with self.assertRaises(ConfigurationError):
            replace(settings(self.tmp.name), sqlite_journal_mode="OFF").validate()
        db_file = Path(self.tmp.name) / "plain.sqlite3"
        app = create_app(settings(self.tmp.name, sqlite_journal_mode="DELETE"), db_path=db_file)
        with app.state.db.transaction() as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "delete")


class SingleThreadedWsgiTests(unittest.TestCase):
    """Full flows through the WSGI adapter; no thread may ever be started."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.original_run_sync = anyio.to_thread.run_sync
        run_blocking_calls_inline()
        web = make_web_dir(self.tmp.name)
        cfg = settings(self.tmp.name, frontend_dist_dir=str(web), rate_limit_auth_per_minute=3, sqlite_journal_mode="DELETE")
        self.started = 0

        def factory() -> object:
            self.started += 1
            return create_app(cfg, db_path=Path(self.tmp.name) / "wsgi.sqlite3")

        self.wsgi = SingleThreadedWSGI(factory, trust_proxy_headers=True)
        self.http = httpx.Client(transport=httpx.WSGITransport(app=self.wsgi), base_url="http://testserver")

    def tearDown(self) -> None:
        anyio.to_thread.run_sync = self.original_run_sync
        self.http.close()
        self.tmp.cleanup()

    def test_full_flow_uses_one_thread(self) -> None:
        threads_before = threading.active_count()
        self.assertEqual(self.started, 0)  # built on the first request, not at import

        self.assertIn("ResearchFlow", self.http.get("/").text)
        self.assertEqual(self.http.get("/assets/index-abc123.js").text, "console.log('app')")

        reg = self.http.post("/api/v1/auth/register", json={
            "full_name": "Wsgi User", "username": "wsgi.user", "email": "wsgi@lab.edu", "password": PASSWORD})
        self.assertEqual(reg.status_code, 201, reg.text)
        login = self.http.post("/api/v1/auth/login", json={"identifier": "wsgi.user", "password": PASSWORD})
        self.assertEqual(login.status_code, 200)
        self.assertIn("rf_session", self.http.cookies)
        csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
        user_id = login.json()["user"]["id"]

        picture = io.BytesIO()
        Image.new("RGB", (400, 300), (40, 90, 200)).save(picture, format="PNG")
        up = self.http.put("/api/v1/users/me/avatar", headers=csrf, files={"file": ("me.png", picture.getvalue(), "image/png")})
        self.assertEqual(up.status_code, 200, up.text)
        avatar = self.http.get(f"/api/v1/users/{user_id}/avatar")
        self.assertEqual(avatar.headers["content-type"], "image/webp")

        project = self.http.post("/api/v1/projects", headers=csrf, json={"title": "WSGI Project"}).json()
        payload = b"%PDF-1.4\n" + b"x" * 300_000  # larger than one read chunk
        stored = self.http.post(f"/api/v1/projects/{project['id']}/files", headers=csrf,
                                files={"file": ("report.pdf", payload, "application/pdf")}, data={"folder": "/Reports"})
        self.assertEqual(stored.status_code, 201, stored.text)
        back = self.http.post(f"/api/v1/files/{stored.json()['id']}/download", headers=csrf)
        self.assertEqual(back.status_code, 200)
        self.assertEqual(back.content, payload)

        paper = self.http.post(f"/api/v1/projects/{project['id']}/manuscripts", headers=csrf, json={"title": "Paper"}).json()
        export = self.http.get(f"/api/v1/manuscripts/{paper['id']}/export/project.zip")
        self.assertEqual(export.status_code, 200, export.text[:200])
        self.assertEqual(export.content[:2], b"PK")

        self.assertEqual(self.http.get("/api/v1/nope").status_code, 404)
        self.assertEqual(self.started, 1)
        self.assertEqual(threading.active_count(), threads_before)

    def test_visitor_address_comes_from_the_host_proxy(self) -> None:
        def attempt(ip: str) -> int:
            return self.http.post("/api/v1/auth/login", json={"identifier": "nobody", "password": "x"},
                                  headers={"X-Real-IP": ip, "X-Forwarded-For": f"9.9.9.9, {ip}"}).status_code

        self.assertEqual([attempt("203.0.113.5") for _ in range(4)], [401, 401, 401, 429])
        self.assertEqual(attempt("203.0.113.77"), 401)  # another visitor is not locked out


if __name__ == "__main__":
    unittest.main()
