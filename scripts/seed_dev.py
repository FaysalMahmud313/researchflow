"""Create the local demo account and a small sample workspace (development only).

    python scripts/seed_dev.py                 # uses backend/.env
    python scripts/seed_dev.py --env-file other.env

Signs in as:  username researchflow_demo  (or demo@researchflow.local)
              password ResearchFlowDemo!2026
The credentials are defined in app/core/demo.py. Re-running is safe: the account is reused
(its password is restored if it was changed) and the sample project is not duplicated.
Refuses to run unless APP_ENV is development or testing. No running server is needed.
"""
import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

SAMPLE_BIBTEX = (
    "@inproceedings{ho2020ddpm, author={Ho, Jonathan and Jain, Ajay and Abbeel, Pieter}, "
    "title={Denoising Diffusion Probabilistic Models}, booktitle={NeurIPS}, year={2020}}"
)


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", default=str(BACKEND / ".env"))
    args = parser.parse_args()
    load_env(Path(args.env_file))
    app_env = os.environ.get("APP_ENV", "development").strip().lower()
    if app_env not in ("development", "testing"):
        print(f"Refusing to seed: APP_ENV is '{app_env}'. The demo account is for local development only.", file=sys.stderr)
        return 2
    os.chdir(BACKEND)  # relative DATABASE_PATH / PRIVATE_STORAGE_DIR resolve like the server's

    from fastapi.testclient import TestClient

    from app.core.config import load_settings_from_env
    from app.core.demo import (
        DEMO_PASSWORD,
        DEMO_PROJECT_TITLE,
        DEMO_USERNAME,
        DemoSeedRefused,
        ensure_demo_account,
    )
    from app.main import create_app

    cfg = load_settings_from_env()

    app = create_app(cfg)  # runs migrations, same database as the server
    db = app.state.db
    try:
        with db.transaction() as conn:
            ensure_demo_account(conn, cfg)
    except DemoSeedRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # Build the sample workspace through the real API, in-process.
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"identifier": DEMO_USERNAME, "password": DEMO_PASSWORD})
        login.raise_for_status()
        client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        projects = client.get("/api/v1/projects").json()["projects"]
        if not any(p["title"] == DEMO_PROJECT_TITLE for p in projects):
            project = client.post("/api/v1/projects", json={
                "title": DEMO_PROJECT_TITLE,
                "description": "Sample workspace for trying ResearchFlow locally. Safe to edit or delete.",
                "research_domain": "Climate Science",
            }).json()
            client.post(f"/api/v1/projects/{project['id']}/references/import-bibtex", json={"bibtex": SAMPLE_BIBTEX})
            client.post(f"/api/v1/projects/{project['id']}/manuscripts",
                        json={"title": "Downscaling with Diffusion", "template": "structured"})
            print(f"Created sample project '{DEMO_PROJECT_TITLE}'.")

    print("Demo account ready. Open http://localhost:5173 and sign in as:")
    print(f"  username: {DEMO_USERNAME}")
    print(f"  password: {DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
