"""SQL injection regression tests: hostile input in every search box, filter, path and stored field.

Every query in the backend binds user values as `?` parameters (Ruff rule S608 guards the code
in CI). These tests prove it from the outside: payloads never change the schema, never widen
results beyond the caller's projects, and are stored as plain text.
"""
import tempfile
import unittest
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.core.config import AppSettings
from app.main import create_app

PAYLOADS = [
    "' OR '1'='1",
    "' OR 1=1 --",
    "\" OR \"\"=\"",
    "'; DROP TABLE users; --",
    "1; DELETE FROM projects",
    "' UNION SELECT id, email, password_hash, 1, 1, 1, 1 FROM users --",
    "%' OR title LIKE '%",
    "%",
    "_",
    "\\",
    "admin'--",
    "') OR ('a'='a",
    "1' AND (SELECT COUNT(*) FROM sqlite_master) > 0 --",
]


class SqlInjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = create_app(
            settings=AppSettings(
                app_env="testing",
                session_secret_key="test-only-session-secret-key-at-least-32-bytes-long-9999",
                csrf_secret_key="test-only-csrf-secret-key-at-least-32-bytes-long-999999",
                token_hash_pepper="test-only-token-hash-pepper-32-bytes-99",
                private_storage_dir=Path(cls.tmp.name) / "storage",
                rate_limit_enabled=False,
            ),
            db_path=":memory:",
        )
        cls.victim = cls.login("Victim Researcher", "victim")
        cls.attacker = cls.login("Attacker", "attacker")
        cls.victim_project = cls.post(cls.victim, "/projects", {"title": "Secret Vaccine Study", "description": "confidential"})["id"]
        cls.post(cls.victim, f"/projects/{cls.victim_project}/references",
                 {"title": "Private Trial Results", "authors": "Victim, V.", "year": 2026})
        cls.victim_paper = cls.post(cls.victim, f"/projects/{cls.victim_project}/manuscripts", {"title": "Secret Draft"})["id"]
        cls.attacker_project = cls.post(cls.attacker, "/projects", {"title": "Attacker Lab"})["id"]
        cls.tables_before = cls.tables()
        cls.user_count = cls.count("users")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    @classmethod
    def login(cls, name: str, username: str) -> TestClient:
        c = TestClient(cls.app)
        reg = c.post("/api/v1/auth/register", json={"full_name": name, "username": username, "email": f"{username}@x.edu", "password": "SecurePass123!"})
        assert reg.status_code == 201, reg.text
        res = c.post("/api/v1/auth/login", json={"identifier": username, "password": "SecurePass123!"}).json()
        c.headers["X-CSRF-Token"] = res["csrf_token"]
        return c

    @staticmethod
    def post(c: TestClient, url: str, body: dict[str, Any]) -> Any:
        r = c.post("/api/v1" + url, json=body)
        assert r.status_code in (200, 201), r.text
        return r.json()

    @classmethod
    def tables(cls) -> set[str]:
        with cls.app.state.db.transaction() as conn:
            return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    @classmethod
    def count(cls, table: str) -> int:
        with cls.app.state.db.transaction() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608 - test helper, constant names

    def assert_database_intact(self) -> None:
        self.assertEqual(self.tables(), self.tables_before)
        self.assertEqual(self.count("users"), self.user_count)
        self.assertEqual(self.victim.get(f"/api/v1/projects/{self.victim_project}").json()["title"], "Secret Vaccine Study")

    def assert_no_victim_data(self, payload: Any) -> None:
        text = str(payload)
        # Real hash values, not the word "password_hash" (which appears in the attacker's own payload-titled project).
        for secret in ("Secret Vaccine Study", "Private Trial Results", "Secret Draft", "victim@x.edu", "$argon2", "$scrypt"):
            self.assertNotIn(secret, text)

    def test_login_with_injection_payloads_is_rejected(self) -> None:
        anon = TestClient(self.app)
        for p in PAYLOADS:
            r = anon.post("/api/v1/auth/login", json={"identifier": p if len(p) >= 3 else p * 3, "password": p if p else "x"})
            self.assertIn(r.status_code, (401, 422), p)
        self.assert_database_intact()

    def test_search_and_filters_never_leak_or_break(self) -> None:
        for p in PAYLOADS:
            q = quote(p, safe="")
            urls = [
                f"/api/v1/search?q={q}",
                f"/api/v1/projects?q={q}&publication_status={q}&status={q}&domain={q}&member={q}&role={q}",
                f"/api/v1/projects?member={q}",
                f"/api/v1/projects/{self.attacker_project}/references?q={q}",
                f"/api/v1/me/manuscripts?q={q}&status={q}",
                f"/api/v1/me/files?q={q}&artifact_type={q}",
                f"/api/v1/me/references?q={q}",
                f"/api/v1/users/search?q={q}",
            ]
            for url in urls:
                r = self.attacker.get(url)
                self.assertIn(r.status_code, (200, 422), f"{url} -> {r.status_code}")
                if r.status_code == 200:
                    self.assert_no_victim_data(r.json())
        self.assert_database_intact()

    def test_wildcards_are_matched_literally(self) -> None:
        own = self.victim.get("/api/v1/search?q=%25").json()
        self.assertEqual(own["projects"], [], "a bare % must not match every project")
        self.assertEqual(self.victim.get(f"/api/v1/projects/{self.victim_project}/references?q=_").json()["references"], [])

    def test_injection_in_ids_and_paths(self) -> None:
        for p in PAYLOADS:
            seg = quote(p, safe="")
            for url in (f"/api/v1/projects/{seg}", f"/api/v1/manuscripts/{seg}", f"/api/v1/manuscript-files/{seg}",
                        f"/api/v1/projects/{seg}/files", f"/api/v1/files/{seg}/versions"):
                r = self.attacker.get(url)
                self.assertIn(r.status_code, (403, 404, 405, 422), f"{url} -> {r.status_code}")
                self.assert_no_victim_data(r.text)
        self.assert_database_intact()

    def test_payloads_are_stored_as_plain_text(self) -> None:
        for p in PAYLOADS[:6]:
            title = f"Study {p}"[:200]
            created = self.post(self.attacker, "/projects", {"title": title})
            self.assertEqual(self.attacker.get(f"/api/v1/projects/{created['id']}").json()["title"], title.strip())
        paper = self.post(self.attacker, f"/projects/{self.attacker_project}/manuscripts", {"title": "'; DROP TABLE documents; --"})
        comment = self.post(self.attacker, f"/manuscripts/{paper['id']}/comments", {"body": "' OR 1=1; DELETE FROM doc_comments; --"})
        self.assertEqual(comment["body"], "' OR 1=1; DELETE FROM doc_comments; --")
        bad_path = self.attacker.post(f"/api/v1/manuscripts/{paper['id']}/files", json={"path": "x'); DROP TABLE users;--.tex"})
        self.assertEqual(bad_path.status_code, 422)
        bad_key = self.attacker.post(f"/api/v1/projects/{self.attacker_project}/references/import-bibtex",
                                     json={"bibtex": "@article{x' OR '1'='1, title={T}, year={2020}}"})
        self.assertEqual(bad_key.json()["created"], [])
        self.assert_database_intact()


if __name__ == "__main__":
    unittest.main()
