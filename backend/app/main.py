import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.v1.bibliography import build_bibliography_router
from app.api.v1.context import ApiContext
from app.api.v1.manuscripts import build_manuscripts_router
from app.api.v1.router import build_v1_router
from app.api.v1.workspace import build_workspace_router
from app.core.config import AppSettings, load_settings_from_env
from app.models.database import RelationalDatabase
from app.security.rate_limit import SlidingWindowRateLimiter
from app.storage.private_storage import PrivateStorageEngine

logger = logging.getLogger("researchflow")


def resolve_db_path(cfg: AppSettings) -> str:
    if cfg.database_path:
        return cfg.database_path
    if cfg.database_url.startswith("sqlite:///"):
        return cfg.database_url[len("sqlite:///"):]
    # The relational layer is SQLite-based; PostgreSQL URLs are documented but not yet wired.
    logger.warning("DATABASE_URL is not a sqlite:/// URL; using ./tmp/researchflow_dev.sqlite3")
    return "./tmp/researchflow_dev.sqlite3"


def create_app(
    settings: AppSettings | None = None,
    db_path: str | Path | None = None,
) -> FastAPI:
    cfg = settings if settings is not None else load_settings_from_env()
    cfg.validate()

    db = RelationalDatabase(db_path if db_path is not None else resolve_db_path(cfg))
    storage = PrivateStorageEngine(cfg.private_storage_dir, cfg.max_upload_size_bytes)
    rate_limiter = SlidingWindowRateLimiter()
    ctx = ApiContext(cfg, db, storage, rate_limiter)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        with db.transaction() as conn:
            live = {r["temp_key"] for r in conn.execute("SELECT temp_key FROM upload_sessions WHERE status = 'in_progress'")}
        storage.cleanup_abandoned_staging(live)
        yield

    # Disable interactive OpenAPI docs in production unless explicitly enabled
    docs_enabled = cfg.app_env in ("development", "testing")
    app = FastAPI(
        title=cfg.app_name,
        version=cfg.app_version,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )

    # Explicit CORS origins — never wildcard when credentials are enabled
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[cfg.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", cfg.csrf_header_name, "Accept"],
        expose_headers=["Content-Disposition", "X-Export-Missing", "X-Export-Warnings"],
    )

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled error on %s %s", request.method, request.url.path)
            # Never leak internal stack traces to clients
            response = JSONResponse(
                status_code=500,
                content={"detail": "An internal server error occurred."},
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if cfg.app_env in ("staging", "production") or cfg.session_cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        return response

    app.state.settings = cfg
    app.state.db = db
    app.state.storage = storage
    app.state.rate_limiter = rate_limiter

    app.include_router(build_v1_router(cfg, db, storage, rate_limiter, ctx))
    app.include_router(build_manuscripts_router(ctx))
    app.include_router(build_bibliography_router(ctx))
    app.include_router(build_workspace_router(ctx))

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        # The API has no page of its own; send anyone who opens it to the web app.
        return RedirectResponse(cfg.frontend_origin)
    return app


app = create_app()
