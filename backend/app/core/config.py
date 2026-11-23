import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

FORBIDDEN_PLACEHOLDER_PREFIXES = (
    "REPLACE_WITH_",
    "CHANGE_ME",
    "secret",
    "password",
    "123456",
)


class ConfigurationError(RuntimeError):
    """Raised when required environment variables are missing or insecure."""


@dataclass(frozen=True)
class AppSettings:
    app_env: str = "development"
    app_name: str = "ResearchFlow"
    app_version: str = "1.0.0"
    debug: bool = False
    frontend_origin: str = "http://localhost:5173"
    backend_origin: str = "http://localhost:8000"
    allowed_hosts: List[str] = field(default_factory=lambda: ["localhost", "127.0.0.1", "testserver"])
    database_url: str = "sqlite:///./tmp/researchflow_dev.sqlite3"
    db_ssl_required: bool = False
    session_secret_key: str = field(repr=False, default="dev-only-session-secret-key-at-least-32-bytes-long-0001")
    csrf_secret_key: str = field(repr=False, default="dev-only-csrf-secret-key-at-least-32-bytes-long-000001")
    token_hash_pepper: str = field(repr=False, default="dev-only-token-hash-pepper-32-bytes-01")
    session_cookie_name: str = "rf_session"
    session_cookie_secure: bool = False
    session_cookie_httponly: bool = True
    session_cookie_samesite: str = "lax"
    session_ttl_minutes: int = 720
    # "Remember me" sign-ins keep a persistent cookie this many days; others end with the browser.
    session_remember_days: int = 30
    csrf_protection_enabled: bool = True
    csrf_header_name: str = "X-CSRF-Token"
    rate_limit_enabled: bool = True
    rate_limit_auth_per_minute: int = 10
    rate_limit_api_per_minute: int = 120
    rate_limit_upload_per_minute: int = 15
    storage_backend: str = "local"
    private_storage_dir: Path = Path("./private_uploads")
    max_upload_size_bytes: int = 15 * 1024 * 1024  # 15 MB default
    project_storage_quota_bytes: int = 100 * 1024 * 1024  # 100 MB default
    database_path: str = ""
    # Profile pictures are small: they are decoded, cropped and re-encoded server-side.
    avatar_max_upload_bytes: int = 5 * 1024 * 1024
    # Empty allows any email domain; otherwise registration is limited to these domains.
    allowed_email_domains: List[str] = field(default_factory=list)
    max_archive_entries: int = 2000
    max_archive_uncompressed_bytes: int = 512 * 1024 * 1024
    doi_lookup_enabled: bool = False
    # Folder with the built web app (frontend/dist). When set, the API serves it too, so one
    # process is the whole site. Leave empty when a web server such as Caddy serves the files.
    frontend_dist_dir: str = ""
    # SQLite journal mode. WAL is fastest; hosts whose disks are network file systems need DELETE.
    sqlite_journal_mode: str = "WAL"
    # Outgoing email (verification and password-reset codes). "console" sends nothing.
    email_backend: str = "console"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = field(repr=False, default="")
    smtp_use_tls: bool = True
    email_from_address: str = "noreply@researchflow.local"

    def validate(self) -> None:
        """Validate configuration and fail safely if required settings are insecure."""
        if self.app_env not in ("development", "testing", "staging", "production"):
            raise ConfigurationError(f"Invalid APP_ENV: {self.app_env}")

        if self.session_cookie_samesite.lower() not in ("lax", "strict", "none"):
            raise ConfigurationError("SESSION_COOKIE_SAMESITE must be 'lax', 'strict', or 'none'.")

        if self.frontend_origin == "*":
            raise ConfigurationError("FRONTEND_ORIGIN cannot be wildcard '*' when credentials are used.")

        if self.sqlite_journal_mode not in ("WAL", "DELETE", "TRUNCATE"):
            raise ConfigurationError("SQLITE_JOURNAL_MODE must be WAL, DELETE or TRUNCATE.")
        if self.email_backend not in ("console", "smtp"):
            raise ConfigurationError("EMAIL_BACKEND must be 'console' or 'smtp'.")
        if self.email_backend == "smtp" and not self.smtp_host:
            raise ConfigurationError("EMAIL_BACKEND=smtp requires SMTP_HOST.")

        if len(self.session_secret_key) < 32:
            raise ConfigurationError("SESSION_SECRET_KEY must be at least 32 characters long.")
        if len(self.csrf_secret_key) < 32:
            raise ConfigurationError("CSRF_SECRET_KEY must be at least 32 characters long.")
        if len(self.token_hash_pepper) < 16:
            raise ConfigurationError("TOKEN_HASH_PEPPER must be at least 16 characters long.")

        if self.app_env in ("staging", "production"):
            if self.debug:
                raise ConfigurationError("DEBUG must be false in staging/production.")
            if not self.session_cookie_secure:
                raise ConfigurationError("SESSION_COOKIE_SECURE must be true in staging/production.")
            if not self.frontend_origin.startswith("https://"):
                raise ConfigurationError("FRONTEND_ORIGIN must use https:// in staging/production.")
            if not self.database_path:
                raise ConfigurationError("Set DATABASE_PATH to the SQLite file on persistent storage in staging/production.")
            if "://postgres:" in self.database_url or "://root:" in self.database_url:
                raise ConfigurationError("Do not use a database superuser ('postgres'/'root') in production.")
            for name, secret_val in (
                ("SESSION_SECRET_KEY", self.session_secret_key),
                ("CSRF_SECRET_KEY", self.csrf_secret_key),
                ("TOKEN_HASH_PEPPER", self.token_hash_pepper),
            ):
                if secret_val.startswith("dev-only-") or any(
                    secret_val.upper().startswith(p.upper()) for p in FORBIDDEN_PLACEHOLDER_PREFIXES
                ):
                    raise ConfigurationError(
                        f"{name} uses a placeholder or development default in {self.app_env} environment."
                    )


def load_env_file(path: Path) -> None:
    """Read KEY=VALUE lines into the environment. Variables that are already set win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def load_settings_from_env(env: dict[str, str] | None = None) -> AppSettings:
    src = env if env is not None else os.environ
    app_env = src.get("APP_ENV", "development").strip().lower()

    def parse_bool(key: str, default: bool) -> bool:
        val = src.get(key)
        if val is None:
            return default
        return val.strip().lower() in ("1", "true", "yes", "on")

    settings = AppSettings(
        app_env=app_env,
        app_name=src.get("APP_NAME", "ResearchFlow"),
        app_version=src.get("APP_VERSION", "1.0.0"),
        debug=parse_bool("DEBUG", False),
        frontend_origin=src.get("FRONTEND_ORIGIN", "http://localhost:5173").strip(),
        backend_origin=src.get("BACKEND_ORIGIN", "http://localhost:8000").strip(),
        allowed_hosts=[
            h.strip() for h in src.get("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if h.strip()
        ],
        database_url=src.get("DATABASE_URL", "sqlite:///./tmp/researchflow_dev.sqlite3").strip(),
        db_ssl_required=parse_bool("DB_SSL_REQUIRED", app_env in ("staging", "production")),
        session_secret_key=src.get(
            "SESSION_SECRET_KEY", "dev-only-session-secret-key-at-least-32-bytes-long-0001"
        ),
        csrf_secret_key=src.get(
            "CSRF_SECRET_KEY", "dev-only-csrf-secret-key-at-least-32-bytes-long-000001"
        ),
        token_hash_pepper=src.get("TOKEN_HASH_PEPPER", "dev-only-token-hash-pepper-32-bytes-01"),
        session_cookie_name=src.get("SESSION_COOKIE_NAME", "rf_session"),
        session_cookie_secure=parse_bool("SESSION_COOKIE_SECURE", app_env in ("staging", "production")),
        session_cookie_httponly=parse_bool("SESSION_COOKIE_HTTPONLY", True),
        session_cookie_samesite=src.get("SESSION_COOKIE_SAMESITE", "lax").strip().lower(),
        session_ttl_minutes=int(src.get("SESSION_TTL_MINUTES", "720")),
        session_remember_days=int(src.get("SESSION_REMEMBER_DAYS", "30")),
        csrf_protection_enabled=parse_bool("CSRF_PROTECTION_ENABLED", True),
        csrf_header_name=src.get("CSRF_HEADER_NAME", "X-CSRF-Token"),
        rate_limit_enabled=parse_bool("RATE_LIMIT_ENABLED", True),
        rate_limit_auth_per_minute=int(src.get("RATE_LIMIT_AUTH_PER_MINUTE", "10")),
        rate_limit_api_per_minute=int(src.get("RATE_LIMIT_API_PER_MINUTE", "120")),
        rate_limit_upload_per_minute=int(src.get("RATE_LIMIT_UPLOAD_PER_MINUTE", "15")),
        storage_backend=src.get("STORAGE_BACKEND", "local").strip().lower(),
        private_storage_dir=Path(src.get("PRIVATE_STORAGE_DIR", "./private_uploads")),
        max_upload_size_bytes=int(src.get("MAX_UPLOAD_SIZE_BYTES", str(15 * 1024 * 1024))),
        project_storage_quota_bytes=int(src.get("PROJECT_STORAGE_QUOTA_BYTES", str(100 * 1024 * 1024))),
        database_path=src.get("DATABASE_PATH", "").strip(),
        avatar_max_upload_bytes=int(src.get("AVATAR_MAX_UPLOAD_BYTES", str(5 * 1024 * 1024))),
        allowed_email_domains=[
            d.strip().lower().lstrip("@") for d in src.get("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()
        ],
        doi_lookup_enabled=parse_bool("DOI_LOOKUP_ENABLED", False),
        frontend_dist_dir=src.get("FRONTEND_DIST_DIR", "").strip(),
        sqlite_journal_mode=src.get("SQLITE_JOURNAL_MODE", "WAL").strip().upper(),
        email_backend=src.get("EMAIL_BACKEND", "console").strip().lower(),
        smtp_host=src.get("SMTP_HOST", "").strip(),
        smtp_port=int(src.get("SMTP_PORT", "587")),
        smtp_username=src.get("SMTP_USERNAME", "").strip(),
        smtp_password=src.get("SMTP_PASSWORD", ""),
        smtp_use_tls=parse_bool("SMTP_USE_TLS", True),
        email_from_address=src.get("EMAIL_FROM_ADDRESS", "noreply@researchflow.local").strip(),
    )
    settings.validate()
    return settings
