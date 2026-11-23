"""WSGI entry point, for hosts that run WSGI apps only (PythonAnywhere).

The host's WSGI file needs two lines (see docs/DEPLOYMENT.md):

    import sys; sys.path.insert(0, "/home/YOURNAME/researchflow")
    from wsgi import application

Settings come from ~/researchflow.env (or the file named by RESEARCHFLOW_ENV_FILE).
The built web app in ./web, when present, is served by the same process.
Everywhere else, run the app with uvicorn (app.main:app) instead.
"""
import os
from pathlib import Path
from typing import Any

from app.core.config import load_env_file
from app.wsgi_adapter import SingleThreadedWSGI, run_blocking_calls_inline

HERE = Path(__file__).resolve().parent

load_env_file(Path(os.environ.get("RESEARCHFLOW_ENV_FILE") or Path.home() / "researchflow.env"))
if (HERE / "web" / "index.html").is_file():
    os.environ.setdefault("FRONTEND_DIST_DIR", str(HERE / "web"))
run_blocking_calls_inline()


def _create_app() -> Any:
    from app.main import app

    return app


application = SingleThreadedWSGI(
    _create_app,
    trust_proxy_headers=os.environ.get("TRUST_PROXY_HEADERS", "").strip().lower() in ("1", "true", "yes", "on"),
)
