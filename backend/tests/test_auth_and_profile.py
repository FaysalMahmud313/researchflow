"""Sign-up (email first), username checks, remember-me sessions, profile pictures, the
development demo account, and expired verification/reset codes."""
import io
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import AppSettings
from app.core.demo import DEMO_PASSWORD, DEMO_USERNAME, DemoSeedRefused, ensure_demo_account
from app.main import create_app

PASSWORD = "SecurePass123!"


def png_bytes(size: tuple[int, int] = (640, 480), color: tuple[int, int, int] = (90, 80, 220)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


class AuthAndProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = AppSettings(
            app_env="testing",
            session_secret_key="test-only-session-secret-key-at-least-32-bytes-long-9999",
            csrf_secret_key="test-only-csrf-secret-key-at-least-32-bytes-long-999999",
            token_hash_pepper="test-only-token-hash-pepper-32-bytes-99",
            private_storage_dir=Path(self.tmp.name) / "storage",
            rate_limit_enabled=False,
            avatar_max_upload_bytes=200_000,
        )
        self.app = create_app(settings=self.settings, db_path=str(Path(self.tmp.name) / "t.sqlite3"))
        self.anon = TestClient(self.app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def register(self, username: str, email: str | None = None) -> Any:
        return self.anon.post("/api/v1/auth/register", json={
            "full_name": username.title(), "username": username,
            "email": email or f"{username}@lab.edu", "password": PASSWORD,
        })

    def signed_in(self, username: str) -> TestClient:
        self.assertEqual(self.register(username).status_code, 201)
        c = TestClient(self.app)
        res = c.post("/api/v1/auth/login", json={"identifier": username, "password": PASSWORD}).json()
        c.headers["X-CSRF-Token"] = res["csrf_token"]
        return c

    def user_count(self) -> int:
        with self.app.state.db.transaction() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    # ---- sign-up -------------------------------------------------------------
    def test_password_policy_matches_server_rules(self) -> None:
        policy = self.anon.get("/api/v1/auth/password-policy").json()
        self.assertEqual(policy["min_length"], 10)
        self.assertEqual([r["id"] for r in policy["rules"]], ["upper", "lower", "digit"])
        weak = self.anon.post("/api/v1/auth/register", json={
            "full_name": "Weak", "username": "weakpw", "email": "weak@lab.edu", "password": "alllowercase1"})
        self.assertEqual(weak.status_code, 422)
        self.assertIn("uppercase", weak.json()["detail"])

    def test_email_check_validates_without_creating_anything(self) -> None:
        for bad in ["plainaddress", "a@b", "two@@lab.edu", "dots..x@lab.edu", "x@-lab.edu", "x@lab.c0m", " @lab.edu"]:
            r = self.anon.post("/api/v1/auth/register/check-email", json={"email": bad})
            self.assertEqual(r.status_code, 422, bad)
        ok = self.anon.post("/api/v1/auth/register/check-email", json={"email": "  New.Person@Lab.EDU "})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["email"], "new.person@lab.edu")
        self.assertEqual(self.user_count(), 0)  # nothing created or reserved

        self.register("taken", "taken@lab.edu")
        dup = self.anon.post("/api/v1/auth/register/check-email", json={"email": "TAKEN@lab.edu"})
        self.assertEqual(dup.status_code, 409)
        self.assertIn("Forgot password", dup.json()["detail"])

    def test_allowed_email_domains_restrict_registration(self) -> None:
        app = create_app(settings=replace(self.settings, allowed_email_domains=["uni.edu"]),
                         db_path=str(Path(self.tmp.name) / "d.sqlite3"))
        c = TestClient(app)
        self.assertEqual(c.post("/api/v1/auth/register/check-email", json={"email": "a@gmail.com"}).status_code, 403)
        self.assertEqual(c.post("/api/v1/auth/register/check-email", json={"email": "a@uni.edu"}).status_code, 200)
        r = c.post("/api/v1/auth/register", json={"full_name": "Out Sider", "username": "outsider",
                                                  "email": "o@gmail.com", "password": PASSWORD})
        self.assertEqual(r.status_code, 403)

    def test_username_availability_and_specific_conflicts(self) -> None:
        self.register("alice")
        taken = self.anon.get("/api/v1/auth/username-available", params={"username": "ALICE"}).json()
        self.assertFalse(taken["available"])
        free = self.anon.get("/api/v1/auth/username-available", params={"username": "alice.b"}).json()
        self.assertTrue(free["available"])
        bad = self.anon.get("/api/v1/auth/username-available", params={"username": "a b"}).json()
        self.assertFalse(bad["available"])
        self.assertIn("3-32", bad["reason"])

        same_name = self.register("alice", "other@lab.edu")
        self.assertEqual(same_name.status_code, 409)
        self.assertIn("username is taken", same_name.json()["detail"])
        same_email = self.register("alice2", "alice@lab.edu")
        self.assertEqual(same_email.status_code, 409)
        self.assertIn("email already exists", same_email.json()["detail"])

    # ---- sign-in -------------------------------------------------------------
    def test_remember_me_controls_cookie_lifetime(self) -> None:
        self.register("bob")
        short = TestClient(self.app).post("/api/v1/auth/login", json={"identifier": "bob", "password": PASSWORD})
        self.assertNotIn("max-age", short.headers["set-cookie"].lower())
        long = TestClient(self.app).post("/api/v1/auth/login", json={"identifier": "bob@lab.edu", "password": PASSWORD, "remember_me": True})
        self.assertIn(f"max-age={30 * 86400}", long.headers["set-cookie"].lower())
        wrong = TestClient(self.app).post("/api/v1/auth/login", json={"identifier": "nobody", "password": PASSWORD})
        bad_pw = TestClient(self.app).post("/api/v1/auth/login", json={"identifier": "bob", "password": "Nope12345678"})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.json()["detail"], bad_pw.json()["detail"])  # no account enumeration

    def test_expired_and_reused_codes_are_rejected(self) -> None:
        reg = self.register("carol").json()
        token = reg["dev_verification_token"]
        with self.app.state.db.transaction() as conn:
            conn.execute("UPDATE email_verification_tokens SET expires_at = '2000-01-01T00:00:00+00:00'")
        self.assertEqual(self.anon.post("/api/v1/auth/verify-email", json={"token": token}).status_code, 400)

        fresh = self.anon.post("/api/v1/auth/resend-verification", json={"email": "carol@lab.edu"}).json()
        unknown = self.anon.post("/api/v1/auth/resend-verification", json={"email": "ghost@lab.edu"}).json()
        self.assertEqual(fresh["message"], unknown["message"])  # same answer either way
        self.assertNotIn("dev_verification_token", unknown)
        self.assertEqual(self.anon.post("/api/v1/auth/verify-email", json={"token": fresh["dev_verification_token"]}).status_code, 200)
        self.assertEqual(self.anon.post("/api/v1/auth/verify-email", json={"token": fresh["dev_verification_token"]}).status_code, 400)

        reset = self.anon.post("/api/v1/auth/forgot-password", json={"email": "carol@lab.edu"}).json()["dev_reset_token"]
        ok = self.anon.post("/api/v1/auth/reset-password", json={"token": reset, "new_password": "BrandNewPass456"})
        self.assertEqual(ok.status_code, 200)
        again = self.anon.post("/api/v1/auth/reset-password", json={"token": reset, "new_password": "AnotherPass789"})
        self.assertEqual(again.status_code, 400)

    # ---- profile pictures ----------------------------------------------------
    def test_avatar_upload_display_and_remove(self) -> None:
        dana = self.signed_in("dana")
        erik = self.signed_in("erik")
        dana_id = dana.get("/api/v1/auth/me").json()["user"]["id"]

        up = dana.put("/api/v1/users/me/avatar", files={"file": ("me.png", png_bytes(), "image/png")})
        self.assertEqual(up.status_code, 200, up.text)
        version = up.json()["avatar_version"]
        self.assertTrue(version)
        self.assertEqual(dana.get("/api/v1/auth/me").json()["user"]["avatar_version"], version)

        img = erik.get(f"/api/v1/users/{dana_id}/avatar?v={version}")  # another signed-in user sees it
        self.assertEqual(img.status_code, 200)
        self.assertEqual(img.headers["content-type"], "image/webp")
        with Image.open(io.BytesIO(img.content)) as served:
            self.assertEqual((served.format, served.size), ("WEBP", (256, 256)))
        self.assertEqual(erik.get("/api/v1/users/avatars", params={"ids": f"{dana_id},usr_0000000000000000,bad'id"}).json(),
                         {"avatars": {dana_id: version}})
        self.assertEqual(self.anon.get(f"/api/v1/users/{dana_id}/avatar").status_code, 401)

        self.assertEqual(dana.delete("/api/v1/users/me/avatar").status_code, 200)
        self.assertEqual(erik.get(f"/api/v1/users/{dana_id}/avatar").status_code, 404)
        self.assertEqual(list((Path(self.tmp.name) / "storage" / "_avatars").rglob("*.webp")), [])

    def test_avatar_rejects_bad_files_and_needs_csrf(self) -> None:
        fay = self.signed_in("fay")
        fake = fay.put("/api/v1/users/me/avatar", files={"file": ("x.png", b"<script>alert(1)</script>", "image/png")})
        self.assertEqual(fake.status_code, 422)
        gif = io.BytesIO()
        Image.new("RGB", (10, 10)).save(gif, format="GIF")
        self.assertEqual(fay.put("/api/v1/users/me/avatar", files={"file": ("x.gif", gif.getvalue(), "image/gif")}).status_code, 422)
        noisy = io.BytesIO()
        Image.frombytes("RGB", (600, 600), os.urandom(600 * 600 * 3)).save(noisy, format="PNG")
        big = fay.put("/api/v1/users/me/avatar", files={"file": ("big.png", noisy.getvalue(), "image/png")})
        self.assertEqual(big.status_code, 422)
        self.assertIn("up to", big.json()["detail"])
        no_csrf = TestClient(self.app, cookies=fay.cookies).put("/api/v1/users/me/avatar", files={"file": ("me.png", png_bytes(), "image/png")})
        self.assertEqual(no_csrf.status_code, 403)

    # ---- demo account --------------------------------------------------------
    def test_demo_account_is_idempotent_and_never_in_production(self) -> None:
        db = self.app.state.db
        with db.transaction() as conn:
            first = ensure_demo_account(conn, self.settings)
            conn.execute("UPDATE users SET password_hash = 'x' WHERE id = ?", (first,))
            second = ensure_demo_account(conn, self.settings)
        self.assertEqual(first, second)
        self.assertEqual(self.user_count(), 1)
        login = TestClient(self.app).post("/api/v1/auth/login", json={"identifier": DEMO_USERNAME, "password": DEMO_PASSWORD})
        self.assertEqual(login.status_code, 200)  # password restored on re-seed

        for env in ("staging", "production"):
            with db.transaction() as conn, self.assertRaises(DemoSeedRefused):
                ensure_demo_account(conn, replace(self.settings, app_env=env))
        # The login-page hint exists only in development.
        self.assertEqual(self.anon.get("/api/v1/auth/dev-demo").status_code, 404)
        dev = create_app(settings=replace(self.settings, app_env="development"),
                         db_path=str(Path(self.tmp.name) / "t.sqlite3"))
        hint = TestClient(dev).get("/api/v1/auth/dev-demo")
        self.assertEqual(hint.status_code, 200)
        self.assertEqual(hint.json()["username"], DEMO_USERNAME)


if __name__ == "__main__":
    unittest.main()
