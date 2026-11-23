"""Check a built bundle the way PythonAnywhere runs it: load the host's WSGI start file
and drive real requests through it, in production mode, without starting any thread.

    python deploy/pythonanywhere/smoke_test.py <wsgi-start-file> <site-domain>

Used by the Publish workflow before anything is published. Needs the bundle's packages.
"""
import runpy
import sys
import threading

import httpx


def main() -> int:
    wsgi_file, domain = sys.argv[1], sys.argv[2]
    application = runpy.run_path(wsgi_file)["application"]
    threads_before = threading.active_count()
    http = httpx.Client(transport=httpx.WSGITransport(app=application), base_url=f"https://{domain}")

    def check(label: str, ok: bool, detail: object = "") -> None:
        print(("ok   " if ok else "FAIL ") + label, detail if not ok else "")
        if not ok:
            raise SystemExit(1)

    home = http.get("/")
    check("web app is served at /", home.status_code == 200 and "<div id=\"root\">" in home.text, home.status_code)
    check("strict content security policy", "script-src 'self'" in home.headers.get("content-security-policy", ""))
    check("HTTPS-only header", "strict-transport-security" in home.headers)
    script = home.text.split('src="/assets/')[1].split('"')[0]
    asset = http.get(f"/assets/{script}")
    check("scripts load with the right type", asset.headers.get("content-type", "").startswith("text/javascript"), asset.headers)

    health = http.get("/api/v1/health")
    check("API answers in production mode", health.status_code == 200 and health.json()["environment"] == "production", health.text)
    check("API docs are hidden", http.get("/docs").status_code in (200, 404) and "swagger" not in http.get("/docs").text.lower())
    check("demo account hint does not exist", http.get("/api/v1/auth/dev-demo").status_code == 404)

    password = "Smoke-Test-2026-pw"
    reg = http.post("/api/v1/auth/register", json={
        "full_name": "Smoke Test", "username": "smoke.test", "email": "smoke@example.org", "password": password})
    check("registration works", reg.status_code == 201, reg.text)
    check("no verification code leaks in production", "dev_verification_token" not in reg.json())
    login = http.post("/api/v1/auth/login", json={"identifier": "smoke.test", "password": password})
    check("sign-in works", login.status_code == 200, login.text)
    cookie = login.headers.get("set-cookie", "").lower()
    check("session cookie is Secure and HttpOnly", "secure" in cookie and "httponly" in cookie, cookie)
    csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
    project = http.post("/api/v1/projects", headers=csrf, json={"title": "Smoke project"})
    check("creating a project works", project.status_code == 201, project.text)
    pdf = b"%PDF-1.4\n" + b"0" * 200_000
    up = http.post(f"/api/v1/projects/{project.json()['id']}/files", headers=csrf, files={"file": ("a.pdf", pdf, "application/pdf")})
    check("file upload works", up.status_code == 201, up.text)
    down = http.post(f"/api/v1/files/{up.json()['id']}/download", headers=csrf)
    check("file download returns the same bytes", down.content == pdf, down.status_code)

    check("no threads were started", threading.active_count() == threads_before, threading.enumerate())
    print("Bundle smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
