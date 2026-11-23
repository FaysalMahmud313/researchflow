import difflib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.responses import Response as RawResponse

from app.api.v1.bibliography import entry_from_row
from app.api.v1.context import ApiContext, utc_now_iso
from app.core.config import AppSettings
from app.core.demo import DEMO_EMAIL, DEMO_PASSWORD, DEMO_USERNAME, demo_account_exists
from app.core.mailer import Mailer
from app.latex.bibtex import make_cite_key, serialize_entry
from app.latex.export import content_disposition
from app.models.database import RelationalDatabase
from app.permissions.rbac import Permission, ProjectRole, can_assign_invitation_role
from app.schemas.api_schemas import (
    AccountUpdateRequest,
    ArtifactCreateRequest,
    CodeComparisonRequest,
    CollaborationSignalCreateRequest,
    CollaborationSignalUpdateRequest,
    CommentCreateRequest,
    DocumentCreateRequest,
    DocumentUpdateRequest,
    ExperimentCreateRequest,
    ExperimentUpdateRequest,
    FileMetadataUpdateRequest,
    ForgotPasswordRequest,
    InvitationCreateRequest,
    InvitationRespondRequest,
    LoginRequest,
    MemberRoleUpdateRequest,
    OwnershipTransferRequest,
    PasswordChangeRequest,
    PreferencesUpdateRequest,
    ProfileUpdateRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    PublicationStatusUpdateRequest,
    ReferenceCreateRequest,
    ReferenceUpdateRequest,
    RegisterEmailCheckRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TaskCreateRequest,
    TaskUpdateRequest,
    UploadInitRequest,
    VerifyEmailRequest,
    clean_email,
    clean_username,
)
from app.security.passwords import (
    hash_password,
    password_policy,
    validate_password_strength,
    verify_password,
)
from app.security.rate_limit import SlidingWindowRateLimiter
from app.security.sanitizer import sanitize_rich_text
from app.security.tokens import (
    generate_csrf_token,
    generate_opaque_token,
    hash_token,
)
from app.storage.avatars import AvatarError, process_avatar, store_avatar
from app.storage.private_storage import PrivateStorageEngine, StorageSecurityError

DUMMY_PASSWORD_HASH = hash_password("DummyPasswordForTimingProtection123!")


def build_v1_router(
    settings: AppSettings,
    db: RelationalDatabase,
    storage: PrivateStorageEngine,
    rate_limiter: SlidingWindowRateLimiter,
    ctx: Optional[ApiContext] = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    ctx = ctx if ctx is not None else ApiContext(settings, db, storage, rate_limiter)
    mailer = Mailer(settings)

    # Shared helpers live in ApiContext so every router enforces identical auth/RBAC rules.
    log_audit = ctx.log_audit
    log_activity = ctx.log_activity
    enforce_rate_limit = ctx.enforce_rate_limit
    get_current_session_and_user = ctx.get_current_session_and_user
    require_project_permission = ctx.require_project_permission

    def check_email_domain(email: str) -> None:
        allowed = settings.allowed_email_domains
        if allowed and email.rpartition("@")[2] not in allowed:
            raise HTTPException(
                status_code=403,
                detail="Registration is limited to addresses at " + ", ".join(f"@{d}" for d in allowed) + ".",
            )

    def avatar_version(conn: Any, user_id: str) -> str:
        row = conn.execute("SELECT avatar_version FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
        return str(row["avatar_version"]) if row else ""

    # -------------------------------------------------------------------------
    # Health Check
    # -------------------------------------------------------------------------
    @router.get("/health")
    def health_check() -> Dict[str, str]:
        return {"status": "ok", "service": settings.app_name, "environment": settings.app_env}

    # -------------------------------------------------------------------------
    # Authentication & Account Recovery
    # -------------------------------------------------------------------------
    @router.get("/auth/password-policy")
    def get_password_policy() -> Dict[str, Any]:
        return password_policy()

    @router.post("/auth/register/check-email")
    def check_registration_email(payload: RegisterEmailCheckRequest, request: Request) -> Dict[str, Any]:
        # Step 1 of sign-up. Nothing is created or reserved; rate limited like sign-in.
        enforce_rate_limit(request, "auth_check_email", settings.rate_limit_auth_per_minute)
        try:
            email = clean_email(payload.email)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        check_email_domain(email)
        with db.transaction() as conn:
            taken = conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
        if taken:
            raise HTTPException(
                status_code=409,
                detail="An account with this email already exists. Sign in, or use Forgot password to recover it.",
            )
        return {"email": email, "available": True}

    @router.get("/auth/username-available")
    def username_available(request: Request, username: str = Query(..., max_length=64)) -> Dict[str, Any]:
        enforce_rate_limit(request, "auth_username", 60)
        try:
            cleaned = clean_username(username)
        except ValueError as exc:
            return {"username": username, "available": False, "reason": str(exc)}
        with db.transaction() as conn:
            taken = conn.execute("SELECT 1 FROM users WHERE username = ?", (cleaned,)).fetchone()
        return {
            "username": cleaned,
            "available": not taken,
            "reason": "That username is taken. Try another one." if taken else "",
        }

    @router.get("/auth/dev-demo")
    def dev_demo_account() -> Dict[str, str]:
        # Login-page hint for local development only; this route answers 404 everywhere else.
        if settings.app_env != "development":
            raise HTTPException(status_code=404, detail="Not Found")
        with db.transaction() as conn:
            if not demo_account_exists(conn):
                raise HTTPException(status_code=404, detail="Not Found")
        return {"username": DEMO_USERNAME, "email": DEMO_EMAIL, "password": DEMO_PASSWORD}

    @router.post("/auth/register", status_code=201)
    def register(payload: RegisterRequest, request: Request) -> Dict[str, Any]:
        enforce_rate_limit(request, "auth_register", settings.rate_limit_auth_per_minute)
        valid_pw, pw_msg = validate_password_strength(payload.password)
        if not valid_pw:
            raise HTTPException(status_code=422, detail=pw_msg)
        check_email_domain(payload.email)

        now = utc_now_iso()
        user_id = f"usr_{uuid.uuid4().hex[:16]}"
        raw_verify_token = generate_opaque_token(24)
        verify_token_hash = hash_token(raw_verify_token, settings.token_hash_pepper)
        verify_expires = (datetime.now(UTC) + timedelta(hours=24)).isoformat()

        with db.transaction() as conn:
            if conn.execute("SELECT 1 FROM users WHERE email = ?", (payload.email,)).fetchone():
                raise HTTPException(
                    status_code=409,
                    detail="An account with this email already exists. Sign in, or use Forgot password to recover it.",
                )
            if conn.execute("SELECT 1 FROM users WHERE username = ?", (payload.username,)).fetchone():
                raise HTTPException(status_code=409, detail="That username is taken. Try another one.")

            pw_hash = hash_password(payload.password)
            conn.execute(
                "INSERT INTO users (id, username, email, full_name, password_hash, email_verified, is_active, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 0, 1, ?, ?)",
                (user_id, payload.username, payload.email, payload.full_name.strip(), pw_hash, now, now),
            )
            conn.execute(
                "INSERT INTO user_profiles (user_id, updated_at) VALUES (?, ?)",
                (user_id, now),
            )
            conn.execute(
                "INSERT INTO email_verification_tokens (id, user_id, token_hash, expires_at, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, user_id, verify_token_hash, verify_expires, now),
            )
            log_audit(conn, "USER_REGISTERED", f"Registered user @{payload.username}", actor_id=user_id)

        resp: Dict[str, Any] = {
            "user": {
                "id": user_id,
                "username": payload.username,
                "email": payload.email,
                "full_name": payload.full_name.strip(),
                "email_verified": False,
            },
            "message": "Account created. Please verify your email address.",
        }
        resp["verification_email_sent"] = mailer.send_code(payload.email, "verify", raw_verify_token)
        if settings.app_env in ("development", "testing"):
            resp["dev_verification_token"] = raw_verify_token
        return resp

    @router.post("/auth/verify-email")
    def verify_email(payload: VerifyEmailRequest, request: Request) -> Dict[str, Any]:
        enforce_rate_limit(request, "auth_verify", settings.rate_limit_auth_per_minute)
        token_digest = hash_token(payload.token, settings.token_hash_pepper)
        now = utc_now_iso()
        with db.transaction() as conn:
            row = conn.execute(
                "SELECT id, user_id, expires_at, used_at FROM email_verification_tokens WHERE token_hash = ?",
                (token_digest,),
            ).fetchone()
            if not row or row["used_at"] is not None:
                raise HTTPException(status_code=400, detail="Invalid or already-used verification token.")
            if datetime.fromisoformat(row["expires_at"]) < datetime.now(UTC):
                raise HTTPException(status_code=400, detail="Verification token has expired.")

            conn.execute("UPDATE email_verification_tokens SET used_at = ? WHERE id = ?", (now, row["id"]))
            conn.execute("UPDATE users SET email_verified = 1, updated_at = ? WHERE id = ?", (now, row["user_id"]))
            log_audit(conn, "EMAIL_VERIFIED", "User verified email address", actor_id=row["user_id"])
        return {"message": "Email verified successfully."}

    @router.post("/auth/resend-verification")
    def resend_verification(payload: ForgotPasswordRequest, request: Request) -> Dict[str, Any]:
        # Same answer whether or not the address has an account, so it reveals nothing.
        enforce_rate_limit(request, "auth_resend", settings.rate_limit_auth_per_minute)
        email = payload.email.strip().lower()
        resp: Dict[str, Any] = {
            "message": "If that address has an unverified account, a new code is on its way.",
            "email_delivery": mailer.enabled,
        }
        raw = ""
        now = utc_now_iso()
        with db.transaction() as conn:
            user = conn.execute("SELECT id FROM users WHERE email = ? AND email_verified = 0", (email,)).fetchone()
            if user:
                raw = generate_opaque_token(24)
                # Only the newest code works.
                conn.execute(
                    "UPDATE email_verification_tokens SET used_at = ? WHERE user_id = ? AND used_at IS NULL",
                    (now, user["id"]),
                )
                conn.execute(
                    "INSERT INTO email_verification_tokens (id, user_id, token_hash, expires_at, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex, user["id"], hash_token(raw, settings.token_hash_pepper),
                     (datetime.now(UTC) + timedelta(hours=24)).isoformat(), now),
                )
                if settings.app_env in ("development", "testing"):
                    resp["dev_verification_token"] = raw
        if raw:
            mailer.send_code(email, "verify", raw)
        return resp

    @router.post("/auth/login")
    def login(payload: LoginRequest, request: Request, response: Response) -> Dict[str, Any]:
        enforce_rate_limit(request, "auth_login", settings.rate_limit_auth_per_minute)
        identifier = payload.identifier.strip().lower()
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()

        with db.transaction() as conn:
            user = conn.execute(
                "SELECT id, username, email, full_name, password_hash, email_verified, is_active "
                "FROM users WHERE username = ? OR email = ?",
                (identifier, identifier),
            ).fetchone()

            if not user:
                verify_password(payload.password, DUMMY_PASSWORD_HASH)
                log_audit(conn, "LOGIN_FAILED", "Failed login attempt for unknown identifier")
                raise HTTPException(status_code=401, detail="Invalid username/email or password.")

            if not user["is_active"] or not verify_password(payload.password, user["password_hash"]):
                log_audit(conn, "LOGIN_FAILED", "Failed login password verification", actor_id=user["id"])
                raise HTTPException(status_code=401, detail="Invalid username/email or password.")

            raw_session_token = generate_opaque_token(32)
            session_token_hash = hash_token(raw_session_token, settings.token_hash_pepper)
            session_id = f"ses_{uuid.uuid4().hex[:16]}"
            csrf_secret = generate_opaque_token(24)
            lifetime = (
                timedelta(days=settings.session_remember_days)
                if payload.remember_me
                else timedelta(minutes=settings.session_ttl_minutes)
            )
            expires_at = (now_dt + lifetime).isoformat()

            conn.execute(
                "INSERT INTO sessions (id, user_id, token_hash, csrf_secret, expires_at, revoked, created_at) "
                "VALUES (?, ?, ?, ?, ?, 0, ?)",
                (session_id, user["id"], session_token_hash, csrf_secret, expires_at, now),
            )
            log_audit(conn, "LOGIN_SUCCESS", "Session created", actor_id=user["id"])

            csrf_token = generate_csrf_token(session_id, csrf_secret)
            response.set_cookie(
                key=settings.session_cookie_name,
                value=raw_session_token,
                httponly=settings.session_cookie_httponly,
                secure=settings.session_cookie_secure,
                samesite=settings.session_cookie_samesite,  # type: ignore[arg-type]
                # Without "remember me" the cookie ends with the browser session.
                max_age=int(lifetime.total_seconds()) if payload.remember_me else None,
                path="/",
            )
            return {
                "user": {
                    "id": user["id"],
                    "username": user["username"],
                    "email": user["email"],
                    "full_name": user["full_name"],
                    "email_verified": bool(user["email_verified"]),
                    "avatar_version": avatar_version(conn, user["id"]),
                },
                "csrf_token": csrf_token,
                "expires_at": expires_at,
            }

    @router.post("/auth/logout")
    def logout(
        response: Response,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        with db.transaction() as conn:
            conn.execute("UPDATE sessions SET revoked = 1 WHERE id = ?", (session["session_id"],))
            log_audit(conn, "LOGOUT", "User logged out and invalidated session", actor_id=session["user_id"])
        response.delete_cookie(settings.session_cookie_name, path="/")
        return {"message": "Logged out."}

    @router.get("/auth/me")
    def get_me(session: Dict[str, Any] = Depends(get_current_session_and_user)) -> Dict[str, Any]:
        csrf_token = generate_csrf_token(session["session_id"], session["csrf_secret"])
        with db.transaction() as conn:
            version = avatar_version(conn, session["user_id"])
        return {
            "user": {
                "id": session["user_id"],
                "username": session["username"],
                "email": session["email"],
                "full_name": session["full_name"],
                "email_verified": bool(session["email_verified"]),
                "avatar_version": version,
            },
            "csrf_token": csrf_token,
        }

    @router.post("/auth/forgot-password")
    def forgot_password(payload: ForgotPasswordRequest, request: Request) -> Dict[str, Any]:
        enforce_rate_limit(request, "auth_forgot", settings.rate_limit_auth_per_minute)
        email = payload.email.strip().lower()
        generic_msg = "If that email address is registered, password reset instructions have been sent."
        resp: Dict[str, Any] = {"message": generic_msg, "email_delivery": mailer.enabled}
        raw_reset = ""

        with db.transaction() as conn:
            user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if user:
                raw_reset = generate_opaque_token(24)
                reset_hash = hash_token(raw_reset, settings.token_hash_pepper)
                expires = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
                conn.execute(
                    "INSERT INTO password_reset_tokens (id, user_id, token_hash, expires_at, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex, user["id"], reset_hash, expires, utc_now_iso()),
                )
                log_audit(conn, "PASSWORD_RESET_REQUESTED", "Password reset token issued", actor_id=user["id"])
                if settings.app_env in ("development", "testing"):
                    resp["dev_reset_token"] = raw_reset
        if raw_reset:
            mailer.send_code(email, "reset", raw_reset)
        return resp

    @router.post("/auth/reset-password")
    def reset_password(payload: ResetPasswordRequest, request: Request) -> Dict[str, str]:
        enforce_rate_limit(request, "auth_reset", settings.rate_limit_auth_per_minute)
        valid_pw, pw_msg = validate_password_strength(payload.new_password)
        if not valid_pw:
            raise HTTPException(status_code=422, detail=pw_msg)

        token_digest = hash_token(payload.token, settings.token_hash_pepper)
        now = utc_now_iso()
        with db.transaction() as conn:
            row = conn.execute(
                "SELECT id, user_id, expires_at, used_at FROM password_reset_tokens WHERE token_hash = ?",
                (token_digest,),
            ).fetchone()
            if not row or row["used_at"] is not None:
                raise HTTPException(status_code=400, detail="Invalid or expired password reset token.")
            if datetime.fromisoformat(row["expires_at"]) < datetime.now(UTC):
                raise HTTPException(status_code=400, detail="Invalid or expired password reset token.")

            new_hash = hash_password(payload.new_password)
            conn.execute("UPDATE password_reset_tokens SET used_at = ? WHERE id = ?", (now, row["id"]))
            conn.execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?", (new_hash, now, row["user_id"]))
            # Revoke all existing sessions upon password reset
            conn.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (row["user_id"],))
            log_audit(conn, "PASSWORD_RESET_COMPLETED", "Password reset and all sessions revoked", actor_id=row["user_id"])
        return {"message": "Password has been reset. Please log in with your new password."}

    # -------------------------------------------------------------------------
    # Users & Profile Management
    # -------------------------------------------------------------------------
    @router.get("/users/me")
    def get_user_profile(session: Dict[str, Any] = Depends(get_current_session_and_user)) -> Dict[str, Any]:
        with db.transaction() as conn:
            u_row = conn.execute("SELECT created_at FROM users WHERE id = ?", (session["user_id"],)).fetchone()
            prof = conn.execute(
                "SELECT professional_title, avatar_color, avatar_version, theme_mode, accent_color, ui_density, "
                "reduced_motion, institution, department, bio, orcid_id, research_interests, notification_preferences "
                "FROM user_profiles WHERE user_id = ?",
                (session["user_id"],),
            ).fetchone()
            return {
                "id": session["user_id"],
                "username": session["username"],
                "email": session["email"],
                "full_name": session["full_name"],
                "email_verified": bool(session["email_verified"]),
                "created_at": u_row["created_at"] if u_row else "",
                "profile": {
                    "professional_title": prof["professional_title"] if prof else "",
                    "avatar_color": prof["avatar_color"] if prof else "indigo",
                    "avatar_version": prof["avatar_version"] if prof else "",
                    "theme_mode": prof["theme_mode"] if prof else "light",
                    "accent_color": prof["accent_color"] if prof else "indigo",
                    "ui_density": prof["ui_density"] if prof else "compact",
                    "reduced_motion": bool(prof["reduced_motion"]) if prof else False,
                    "institution": prof["institution"] if prof else "",
                    "department": prof["department"] if prof else "",
                    "bio": prof["bio"] if prof else "",
                    "orcid_id": prof["orcid_id"] if prof else "",
                    "research_interests": json.loads(prof["research_interests"]) if prof else [],
                    "notification_preferences": json.loads(prof["notification_preferences"]) if prof else {},
                },
            }

    @router.patch("/users/me")
    def update_user_profile(
        payload: ProfileUpdateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        now = utc_now_iso()
        uid = session["user_id"]
        with db.transaction() as conn:
            if payload.full_name is not None:
                conn.execute("UPDATE users SET full_name = ?, updated_at = ? WHERE id = ?", (payload.full_name.strip(), now, uid))
            if payload.professional_title is not None:
                conn.execute("UPDATE user_profiles SET professional_title = ?, updated_at = ? WHERE user_id = ?", (payload.professional_title.strip(), now, uid))
            if payload.avatar_color is not None:
                conn.execute("UPDATE user_profiles SET avatar_color = ?, updated_at = ? WHERE user_id = ?", (payload.avatar_color, now, uid))
            if payload.institution is not None:
                conn.execute("UPDATE user_profiles SET institution = ?, updated_at = ? WHERE user_id = ?", (payload.institution.strip(), now, uid))
            if payload.department is not None:
                conn.execute("UPDATE user_profiles SET department = ?, updated_at = ? WHERE user_id = ?", (payload.department.strip(), now, uid))
            if payload.bio is not None:
                conn.execute("UPDATE user_profiles SET bio = ?, updated_at = ? WHERE user_id = ?", (payload.bio.strip(), now, uid))
            if payload.orcid_id is not None:
                conn.execute("UPDATE user_profiles SET orcid_id = ?, updated_at = ? WHERE user_id = ?", (payload.orcid_id.strip(), now, uid))
            if payload.research_interests is not None:
                conn.execute(
                    "UPDATE user_profiles SET research_interests = ?, updated_at = ? WHERE user_id = ?",
                    (json.dumps(payload.research_interests), now, uid),
                )
            log_audit(conn, "PROFILE_UPDATED", "Updated researcher profile details", actor_id=uid)
        return {"message": "Profile updated."}

    @router.put("/users/me/avatar")
    async def upload_avatar(
        request: Request,
        file: UploadFile = File(...),
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        enforce_rate_limit(request, "avatar_upload", settings.rate_limit_upload_per_minute)
        uid = session["user_id"]
        data = await file.read(settings.avatar_max_upload_bytes + 1)
        try:
            webp = process_avatar(data, settings.avatar_max_upload_bytes)
        except AvatarError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        new_key = store_avatar(storage, uid, webp)
        version = uuid.uuid4().hex[:12]
        with db.transaction() as conn:
            old = conn.execute("SELECT avatar_key FROM user_profiles WHERE user_id = ?", (uid,)).fetchone()
            conn.execute(
                "UPDATE user_profiles SET avatar_key = ?, avatar_version = ?, updated_at = ? WHERE user_id = ?",
                (new_key, version, utc_now_iso(), uid),
            )
            log_audit(conn, "AVATAR_UPDATED", "Updated profile picture", actor_id=uid)
        if old and old["avatar_key"]:
            storage.delete_key(old["avatar_key"])
        return {"message": "Profile picture updated.", "avatar_version": version}

    @router.delete("/users/me/avatar")
    def remove_avatar(session: Dict[str, Any] = Depends(get_current_session_and_user)) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            old = conn.execute("SELECT avatar_key FROM user_profiles WHERE user_id = ?", (uid,)).fetchone()
            conn.execute(
                "UPDATE user_profiles SET avatar_key = '', avatar_version = '', updated_at = ? WHERE user_id = ?",
                (utc_now_iso(), uid),
            )
            log_audit(conn, "AVATAR_REMOVED", "Removed profile picture", actor_id=uid)
        if old and old["avatar_key"]:
            storage.delete_key(old["avatar_key"])
        return {"message": "Profile picture removed.", "avatar_version": ""}

    @router.get("/users/avatars")
    def avatar_versions(
        ids: str = Query(..., max_length=4000),
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        # Batch lookup so lists of people need one request. Like names and usernames,
        # profile pictures are visible to signed-in users.
        wanted = [i for i in dict.fromkeys(ids.split(",")) if re.fullmatch(r"usr_[0-9a-f]{16}", i)][:200]
        if not wanted:
            return {"avatars": {}}
        marks = ",".join("?" for _ in wanted)
        with db.transaction() as conn:
            rows = conn.execute(
                f"SELECT user_id, avatar_version FROM user_profiles WHERE avatar_version != '' AND user_id IN ({marks})",  # noqa: S608 - only ? placeholders are interpolated
                wanted,
            ).fetchall()
        return {"avatars": {r["user_id"]: r["avatar_version"] for r in rows}}

    @router.get("/users/{user_id}/avatar")
    def get_avatar(
        user_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> RawResponse:
        if not re.fullmatch(r"usr_[0-9a-f]{16}", user_id):
            raise HTTPException(status_code=404, detail="No profile picture.")
        with db.transaction() as conn:
            row = conn.execute("SELECT avatar_key FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
        if not row or not row["avatar_key"]:
            raise HTTPException(status_code=404, detail="No profile picture.")
        try:
            data = storage.read_bytes(row["avatar_key"])
        except (FileNotFoundError, StorageSecurityError) as exc:
            raise HTTPException(status_code=404, detail="No profile picture.") from exc
        return RawResponse(
            content=data,
            media_type="image/webp",
            headers={
                # URLs carry ?v=<version>, so a cached copy is never stale.
                "Cache-Control": "private, max-age=31536000, immutable",
                "Content-Security-Policy": "default-src 'none'; sandbox",
            },
        )

    @router.patch("/users/me/preferences")
    def update_user_preferences(
        payload: PreferencesUpdateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        now = utc_now_iso()
        uid = session["user_id"]
        with db.transaction() as conn:
            if payload.theme_mode is not None:
                conn.execute("UPDATE user_profiles SET theme_mode = ?, updated_at = ? WHERE user_id = ?", (payload.theme_mode, now, uid))
            if payload.accent_color is not None:
                conn.execute("UPDATE user_profiles SET accent_color = ?, updated_at = ? WHERE user_id = ?", (payload.accent_color, now, uid))
            if payload.ui_density is not None:
                conn.execute("UPDATE user_profiles SET ui_density = ?, updated_at = ? WHERE user_id = ?", (payload.ui_density, now, uid))
            if payload.reduced_motion is not None:
                conn.execute("UPDATE user_profiles SET reduced_motion = ?, updated_at = ? WHERE user_id = ?", (int(payload.reduced_motion), now, uid))
            if payload.notification_preferences is not None:
                conn.execute(
                    "UPDATE user_profiles SET notification_preferences = ?, updated_at = ? WHERE user_id = ?",
                    (json.dumps(payload.notification_preferences), now, uid),
                )
            prof = conn.execute(
                "SELECT theme_mode, accent_color, ui_density, reduced_motion, notification_preferences "
                "FROM user_profiles WHERE user_id = ?",
                (uid,),
            ).fetchone()
            return {
                "message": "Preferences saved.",
                "preferences": {
                    "theme_mode": prof["theme_mode"],
                    "accent_color": prof["accent_color"],
                    "ui_density": prof["ui_density"],
                    "reduced_motion": bool(prof["reduced_motion"]),
                    "notification_preferences": json.loads(prof["notification_preferences"]),
                },
            }

    @router.patch("/users/me/account")
    def update_user_account(
        payload: AccountUpdateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        now = utc_now_iso()
        uid = session["user_id"]
        resp: Dict[str, Any] = {"message": "Account settings updated."}
        with db.transaction() as conn:
            if payload.username is not None and payload.username != session["username"]:
                conflict = conn.execute("SELECT id FROM users WHERE username = ? AND id != ?", (payload.username, uid)).fetchone()
                if conflict:
                    raise HTTPException(status_code=409, detail="Username is already taken.")
                conn.execute("UPDATE users SET username = ?, updated_at = ? WHERE id = ?", (payload.username, now, uid))
                log_audit(conn, "USERNAME_CHANGED", f"Changed username to @{payload.username}", actor_id=uid)
                resp["username"] = payload.username
            if payload.new_email is not None and payload.new_email != session["email"]:
                conflict = conn.execute("SELECT id FROM users WHERE email = ? AND id != ?", (payload.new_email, uid)).fetchone()
                if conflict:
                    raise HTTPException(status_code=409, detail="Email is already registered to another account.")
                raw_verify = generate_opaque_token(24)
                verify_hash = hash_token(raw_verify, settings.token_hash_pepper)
                expires = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
                conn.execute(
                    "UPDATE users SET email = ?, email_verified = 0, updated_at = ? WHERE id = ?",
                    (payload.new_email, now, uid),
                )
                conn.execute(
                    "INSERT INTO email_verification_tokens (id, user_id, token_hash, expires_at, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex, uid, verify_hash, expires, now),
                )
                log_audit(conn, "EMAIL_CHANGE_INITIATED", f"Updated email to {payload.new_email} pending verification", actor_id=uid)
                resp["new_email"] = payload.new_email
                resp["verify_code"] = raw_verify
                if settings.app_env in ("development", "testing"):
                    resp["dev_verification_token"] = raw_verify
        code = resp.pop("verify_code", None)
        if code:
            resp["verification_email_sent"] = mailer.send_code(resp["new_email"], "verify", code)
        return resp

    @router.get("/users/me/sessions")
    def list_active_sessions(session: Dict[str, Any] = Depends(get_current_session_and_user)) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            rows = conn.execute(
                "SELECT id, user_agent, ip_address, created_at, expires_at FROM sessions "
                "WHERE user_id = ? AND revoked = 0 ORDER BY created_at DESC",
                (uid,),
            ).fetchall()
            sessions_list = []
            for r in rows:
                d = dict(r)
                d["is_current"] = d["id"] == session["session_id"]
                sessions_list.append(d)
            return {"sessions": sessions_list}

    @router.delete("/users/me/sessions")
    def revoke_other_sessions(session: Dict[str, Any] = Depends(get_current_session_and_user)) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            cur = conn.execute(
                "UPDATE sessions SET revoked = 1 WHERE user_id = ? AND id != ? AND revoked = 0",
                (uid, session["session_id"]),
            )
            log_audit(conn, "OTHER_SESSIONS_REVOKED", f"Revoked {cur.rowcount} other session(s)", actor_id=uid)
            return {"message": "Other sessions revoked.", "revoked_count": cur.rowcount}

    @router.patch("/users/me/password")
    def change_password(
        payload: PasswordChangeRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        valid_pw, pw_msg = validate_password_strength(payload.new_password)
        if not valid_pw:
            raise HTTPException(status_code=422, detail=pw_msg)

        uid = session["user_id"]
        now = utc_now_iso()
        with db.transaction() as conn:
            user = conn.execute("SELECT password_hash FROM users WHERE id = ?", (uid,)).fetchone()
            if not user or not verify_password(payload.current_password, user["password_hash"]):
                log_audit(conn, "PASSWORD_CHANGE_FAILED", "Invalid current password supplied", actor_id=uid)
                raise HTTPException(status_code=401, detail="Current password is incorrect.")
            new_hash = hash_password(payload.new_password)
            conn.execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?", (new_hash, now, uid))
            # Revoke all other sessions except current session
            conn.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ? AND id != ?", (uid, session["session_id"]))
            log_audit(conn, "PASSWORD_CHANGED", "Password updated and other sessions revoked", actor_id=uid)
        return {"message": "Password updated."}

    @router.get("/users/search")
    def search_users(
        request: Request,
        q: str = Query(..., min_length=2, max_length=64),
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        enforce_rate_limit(request, "user_search", 30)
        pattern = f"%{q.strip().lower()}%"
        with db.transaction() as conn:
            rows = conn.execute(
                "SELECT id, username, full_name FROM users "
                "WHERE is_active = 1 AND (LOWER(username) LIKE ? OR LOWER(email) LIKE ? OR LOWER(full_name) LIKE ?) "
                "LIMIT 10",
                (pattern, pattern, pattern),
            ).fetchall()
            return {"users": [dict(r) for r in rows]}

    # -------------------------------------------------------------------------
    # Projects & Collaborative Membership
    # -------------------------------------------------------------------------
    @router.get("/projects")
    def list_projects(
        publication_status: Optional[str] = Query(default=None),
        status: Optional[str] = Query(default=None),
        domain: Optional[str] = Query(default=None),
        role: Optional[str] = Query(default=None),
        member: Optional[str] = Query(default=None),
        q: Optional[str] = Query(default=None),
        include_archived: bool = Query(default=True),
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            rows = conn.execute(
                "SELECT p.*, m.role AS my_role, "
                "(SELECT COUNT(*) FROM project_memberships pm WHERE pm.project_id = p.id) AS member_count "
                "FROM projects p JOIN project_memberships m ON m.project_id = p.id "
                "WHERE m.user_id = ? ORDER BY p.updated_at DESC",
                (uid,),
            ).fetchall()
            projects = []
            for r in rows:
                d = dict(r)
                if not include_archived and (d["status"] == "archived" or d.get("publication_status") == "Archived"):
                    continue
                if publication_status and d.get("publication_status") != publication_status:
                    continue
                if status and d["status"] != status:
                    continue
                if domain and d["research_domain"].lower() != domain.lower():
                    continue
                if role and d["my_role"] != role:
                    continue
                mem_rows = conn.execute(
                    "SELECT u.id AS user_id, u.username, u.full_name, pm.role FROM project_memberships pm "
                    "JOIN users u ON u.id = pm.user_id WHERE pm.project_id = ?",
                    (d["id"],),
                ).fetchall()
                d["members"] = [dict(m) for m in mem_rows]
                if member:
                    m_pat = member.strip().lower()
                    if not any(m_pat in m["username"].lower() or m_pat in m["full_name"].lower() for m in d["members"]):
                        continue
                if q:
                    q_pat = q.strip().lower()
                    match_title = q_pat in d["title"].lower() or q_pat in d["description"].lower()
                    match_mem = any(q_pat in m["username"].lower() or q_pat in m["full_name"].lower() for m in d["members"])
                    if not (match_title or match_mem):
                        continue
                d["research_questions"] = json.loads(d["research_questions"])
                d["objectives"] = json.loads(d["objectives"])
                d["keywords"] = json.loads(d["keywords"])
                projects.append(d)
            return {"projects": projects}

    @router.post("/projects", status_code=201)
    def create_project(
        payload: ProjectCreateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        proj_id = f"prj_{uuid.uuid4().hex[:14]}"
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO projects (id, title, description, research_domain, research_questions, objectives, "
                "hypothesis, keywords, start_date, target_completion_date, status, visibility, icon, owner_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    proj_id,
                    payload.title.strip(),
                    payload.description.strip(),
                    payload.research_domain.strip(),
                    json.dumps(payload.research_questions),
                    json.dumps(payload.objectives),
                    payload.hypothesis.strip(),
                    json.dumps(payload.keywords),
                    payload.start_date,
                    payload.target_completion_date,
                    payload.status,
                    payload.visibility,
                    payload.icon,
                    uid,
                    now,
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO project_memberships (id, project_id, user_id, role, joined_at) VALUES (?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, proj_id, uid, ProjectRole.OWNER.value, now),
            )
            log_activity(conn, proj_id, uid, "project.created", "project", proj_id, f"Created project '{payload.title.strip()}'")
            log_audit(conn, "PROJECT_CREATED", f"Created project {proj_id}", actor_id=uid, project_id=proj_id)
        return {"id": proj_id, "title": payload.title.strip(), "my_role": ProjectRole.OWNER.value}

    @router.get("/projects/{project_id}")
    def get_project(
        project_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            my_role = require_project_permission(conn, project_id, uid, Permission.PROJECT_VIEW)
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            d = dict(row)
            d["research_questions"] = json.loads(d["research_questions"])
            d["objectives"] = json.loads(d["objectives"])
            d["keywords"] = json.loads(d["keywords"])
            d["my_role"] = my_role
            d["storage_quota_bytes"] = settings.project_storage_quota_bytes
            return d

    @router.patch("/projects/{project_id}")
    def update_project(
        project_id: str,
        payload: ProjectUpdateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.PROJECT_EDIT)
            if payload.title is not None:
                conn.execute("UPDATE projects SET title = ?, updated_at = ? WHERE id = ?", (payload.title.strip(), now, project_id))
            if payload.description is not None:
                conn.execute("UPDATE projects SET description = ?, updated_at = ? WHERE id = ?", (payload.description.strip(), now, project_id))
            if payload.status is not None:
                require_project_permission(conn, project_id, uid, Permission.PROJECT_ADMIN)
                conn.execute("UPDATE projects SET status = ?, updated_at = ? WHERE id = ?", (payload.status, now, project_id))
            if payload.visibility is not None:
                require_project_permission(conn, project_id, uid, Permission.PROJECT_ADMIN)
                conn.execute("UPDATE projects SET visibility = ?, updated_at = ? WHERE id = ?", (payload.visibility, now, project_id))
            log_activity(conn, project_id, uid, "project.updated", "project", project_id, "Updated project metadata")
        return {"message": "Project updated."}

    @router.delete("/projects/{project_id}")
    def delete_project(
        project_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        uid = session["user_id"]
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.PROJECT_DELETE)
            files = conn.execute("SELECT storage_key FROM datasets_files WHERE project_id = ?", (project_id,)).fetchall()
            for f in files:
                storage.delete_key(f["storage_key"])
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            log_audit(conn, "PROJECT_DELETED", f"Deleted project {project_id}", actor_id=uid, project_id=project_id)
        return {"message": "Project deleted."}

    # -------------------------------------------------------------------------
    # Memberships, Invitations & Role Enforcement
    # -------------------------------------------------------------------------
    @router.get("/projects/{project_id}/members")
    def list_members(
        project_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.PROJECT_VIEW)
            members = conn.execute(
                "SELECT m.user_id, m.role, m.joined_at, u.username, u.full_name, u.email "
                "FROM project_memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.project_id = ? ORDER BY m.joined_at ASC",
                (project_id,),
            ).fetchall()
            invitations = conn.execute(
                "SELECT i.id, i.invited_user_id, i.role, i.status, i.message, i.created_at, "
                "u.username AS invited_username, u.full_name AS invited_full_name "
                "FROM project_invitations i JOIN users u ON u.id = i.invited_user_id "
                "WHERE i.project_id = ? AND i.status = 'pending' ORDER BY i.created_at DESC",
                (project_id,),
            ).fetchall()
            return {
                "members": [dict(m) for m in members],
                "pending_invitations": [dict(i) for i in invitations],
            }

    @router.post("/projects/{project_id}/invitations", status_code=201)
    def create_invitation(
        project_id: str,
        payload: InvitationCreateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        ident = payload.identifier.strip().lower()
        now = utc_now_iso()
        with db.transaction() as conn:
            inviter_role = require_project_permission(conn, project_id, uid, Permission.MEMBER_INVITE)
            if not can_assign_invitation_role(inviter_role, payload.role):
                log_audit(
                    conn,
                    "ROLE_ESCALATION_BLOCKED",
                    f"User {uid} with role '{inviter_role}' attempted to invite with higher role '{payload.role}'",
                    actor_id=uid,
                    project_id=project_id,
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Role '{inviter_role}' cannot assign a higher role ('{payload.role}').",
                )
            target = conn.execute(
                "SELECT id, username, full_name FROM users WHERE username = ? OR email = ?",
                (ident, ident),
            ).fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="Target user not found.")

            already_member = conn.execute(
                "SELECT id FROM project_memberships WHERE project_id = ? AND user_id = ?",
                (project_id, target["id"]),
            ).fetchone()
            if already_member:
                raise HTTPException(status_code=409, detail="User is already a member of this project.")

            pending = conn.execute(
                "SELECT id FROM project_invitations WHERE project_id = ? AND invited_user_id = ? AND status = 'pending'",
                (project_id, target["id"]),
            ).fetchone()
            if pending:
                raise HTTPException(status_code=409, detail="A pending invitation already exists for this user.")

            inv_id = f"inv_{uuid.uuid4().hex[:14]}"
            conn.execute(
                "INSERT INTO project_invitations (id, project_id, invited_user_id, invited_by_id, role, status, message, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                (inv_id, project_id, target["id"], uid, payload.role, payload.message.strip(), now),
            )
            ctx.notify(conn, target["id"], project_id, "invitation", "New Project Invitation",
                       f"@{session['username']} invited you to join as {payload.role}.")
            log_activity(
                conn,
                project_id,
                uid,
                "member.invited",
                "invitation",
                inv_id,
                f"Invited @{target['username']} as {payload.role}",
            )
            log_audit(
                conn,
                "INVITATION_SENT",
                f"Invited {target['id']} to {project_id} with role {payload.role}",
                actor_id=uid,
                project_id=project_id,
            )
            return {
                "id": inv_id,
                "project_id": project_id,
                "invited_user_id": target["id"],
                "invited_username": target["username"],
                "role": payload.role,
                "status": "pending",
            }

    @router.get("/invitations")
    def list_my_invitations(session: Dict[str, Any] = Depends(get_current_session_and_user)) -> Dict[str, Any]:
        """Pending invitations addressed to the caller (only the project title and inviter are revealed)."""
        with db.transaction() as conn:
            rows = conn.execute(
                "SELECT i.id, i.project_id, i.role, i.message, i.created_at, p.title AS project_title, "
                "u.full_name AS invited_by_name FROM project_invitations i JOIN projects p ON p.id = i.project_id "
                "JOIN users u ON u.id = i.invited_by_id WHERE i.invited_user_id = ? AND i.status = 'pending' "
                "ORDER BY i.created_at DESC",
                (session["user_id"],),
            ).fetchall()
            return {"invitations": [dict(r) for r in rows]}

    @router.patch("/invitations/{invitation_id}")
    def respond_invitation(
        invitation_id: str,
        payload: InvitationRespondRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        uid = session["user_id"]
        now = utc_now_iso()
        with db.transaction() as conn:
            inv = conn.execute("SELECT * FROM project_invitations WHERE id = ?", (invitation_id,)).fetchone()
            if not inv or inv["status"] != "pending":
                raise HTTPException(status_code=404, detail="Pending invitation not found.")

            if payload.action == "cancel":
                require_project_permission(conn, inv["project_id"], uid, Permission.MEMBER_INVITE)
                conn.execute(
                    "UPDATE project_invitations SET status = 'cancelled', responded_at = ? WHERE id = ?",
                    (now, invitation_id),
                )
                return {"message": "Invitation cancelled."}

            if inv["invited_user_id"] != uid:
                raise HTTPException(status_code=403, detail="Only the invited user can accept or reject this invitation.")

            if payload.action == "accept":
                conn.execute(
                    "UPDATE project_invitations SET status = 'accepted', responded_at = ? WHERE id = ?",
                    (now, invitation_id),
                )
                conn.execute(
                    "INSERT INTO project_memberships (id, project_id, user_id, role, joined_at) VALUES (?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex, inv["project_id"], uid, inv["role"], now),
                )
                log_activity(
                    conn,
                    inv["project_id"],
                    uid,
                    "member.joined",
                    "membership",
                    uid,
                    f"@{session['username']} joined project as {inv['role']}",
                )
                log_audit(
                    conn,
                    "INVITATION_ACCEPTED",
                    f"User {uid} accepted invitation {invitation_id} with role {inv['role']}",
                    actor_id=uid,
                    project_id=inv["project_id"],
                )
                return {"message": "Invitation accepted."}
            else:
                conn.execute(
                    "UPDATE project_invitations SET status = 'rejected', responded_at = ? WHERE id = ?",
                    (now, invitation_id),
                )
                return {"message": "Invitation rejected."}

    @router.patch("/projects/{project_id}/members/{member_user_id}")
    def change_member_role(
        project_id: str,
        member_user_id: str,
        payload: MemberRoleUpdateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        uid = session["user_id"]
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.MEMBER_MANAGE)
            target = conn.execute(
                "SELECT role FROM project_memberships WHERE project_id = ? AND user_id = ?",
                (project_id, member_user_id),
            ).fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="Member not found.")
            if target["role"] == ProjectRole.OWNER.value:
                raise HTTPException(status_code=400, detail="Use ownership transfer to change the project owner.")
            conn.execute(
                "UPDATE project_memberships SET role = ? WHERE project_id = ? AND user_id = ?",
                (payload.role, project_id, member_user_id),
            )
            log_audit(
                conn,
                "MEMBER_ROLE_CHANGED",
                f"Changed role of {member_user_id} to {payload.role}",
                actor_id=uid,
                project_id=project_id,
            )
        return {"message": "Member role updated."}

    @router.delete("/projects/{project_id}/members/{member_user_id}")
    def remove_member(
        project_id: str,
        member_user_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        uid = session["user_id"]
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.MEMBER_REMOVE)
            target = conn.execute(
                "SELECT role FROM project_memberships WHERE project_id = ? AND user_id = ?",
                (project_id, member_user_id),
            ).fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="Member not found.")
            if target["role"] == ProjectRole.OWNER.value:
                raise HTTPException(status_code=400, detail="Cannot remove the project owner.")
            conn.execute(
                "DELETE FROM project_memberships WHERE project_id = ? AND user_id = ?",
                (project_id, member_user_id),
            )
            log_audit(
                conn,
                "MEMBER_REMOVED",
                f"Removed member {member_user_id} from project",
                actor_id=uid,
                project_id=project_id,
            )
        return {"message": "Member removed."}

    @router.post("/projects/{project_id}/transfer-ownership")
    def transfer_ownership(
        project_id: str,
        payload: OwnershipTransferRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        uid = session["user_id"]
        now = utc_now_iso()
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.PROJECT_ADMIN)
            target = conn.execute(
                "SELECT role FROM project_memberships WHERE project_id = ? AND user_id = ?",
                (project_id, payload.new_owner_user_id),
            ).fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="New owner must be an existing project member.")
            conn.execute(
                "UPDATE project_memberships SET role = 'editor' WHERE project_id = ? AND user_id = ?",
                (project_id, uid),
            )
            conn.execute(
                "UPDATE project_memberships SET role = 'owner' WHERE project_id = ? AND user_id = ?",
                (project_id, payload.new_owner_user_id),
            )
            conn.execute(
                "UPDATE projects SET owner_id = ?, updated_at = ? WHERE id = ?",
                (payload.new_owner_user_id, now, project_id),
            )
            log_audit(
                conn,
                "OWNERSHIP_TRANSFERRED",
                f"Transferred ownership from {uid} to {payload.new_owner_user_id}",
                actor_id=uid,
                project_id=project_id,
            )
        return {"message": "Ownership transferred."}

    # -------------------------------------------------------------------------
    # Tasks & Milestones
    # -------------------------------------------------------------------------
    @router.get("/projects/{project_id}/tasks")
    def list_tasks(
        project_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.PROJECT_VIEW)
            rows = conn.execute(
                "SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
            tasks = []
            for r in rows:
                d = dict(r)
                d["checklist"] = json.loads(d.pop("checklist_json"))
                d["dependencies"] = json.loads(d.pop("dependencies_json"))
                assignees = conn.execute(
                    "SELECT user_id FROM task_assignees WHERE task_id = ?",
                    (d["id"],),
                ).fetchall()
                d["assignee_ids"] = [a["user_id"] for a in assignees]
                tasks.append(d)
            return {"tasks": tasks}

    @router.post("/projects/{project_id}/tasks", status_code=201)
    def create_task(
        project_id: str,
        payload: TaskCreateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        task_id = f"tsk_{uuid.uuid4().hex[:14]}"
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.TASK_WRITE)
            conn.execute(
                "INSERT INTO tasks (id, project_id, milestone_id, title, description, status, priority, due_date, "
                "checklist_json, dependencies_json, created_by_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?)",
                (
                    task_id,
                    project_id,
                    payload.milestone_id,
                    payload.title.strip(),
                    payload.description.strip(),
                    payload.status,
                    payload.priority,
                    payload.due_date,
                    json.dumps(payload.checklist),
                    uid,
                    now,
                    now,
                ),
            )
            for assignee_id in payload.assignee_ids:
                # Verify assignee is a project member
                is_mem = conn.execute(
                    "SELECT 1 FROM project_memberships WHERE project_id = ? AND user_id = ?",
                    (project_id, assignee_id),
                ).fetchone()
                if is_mem:
                    conn.execute(
                        "INSERT OR IGNORE INTO task_assignees (task_id, user_id) VALUES (?, ?)",
                        (task_id, assignee_id),
                    )
            log_activity(conn, project_id, uid, "task.created", "task", task_id, f"Created task '{payload.title.strip()}'")
        return {"id": task_id, "title": payload.title.strip(), "status": payload.status}

    @router.patch("/tasks/{task_id}")
    def update_task(
        task_id: str,
        payload: TaskUpdateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        uid = session["user_id"]
        now = utc_now_iso()
        with db.transaction() as conn:
            tsk = conn.execute("SELECT project_id, title FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not tsk:
                raise HTTPException(status_code=404, detail="Task not found.")
            require_project_permission(conn, tsk["project_id"], uid, Permission.TASK_WRITE)
            if payload.title is not None:
                conn.execute("UPDATE tasks SET title = ?, updated_at = ? WHERE id = ?", (payload.title.strip(), now, task_id))
            if payload.description is not None:
                conn.execute("UPDATE tasks SET description = ?, updated_at = ? WHERE id = ?", (payload.description.strip(), now, task_id))
            if payload.status is not None:
                conn.execute("UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?", (payload.status, now, task_id))
            if payload.priority is not None:
                conn.execute("UPDATE tasks SET priority = ?, updated_at = ? WHERE id = ?", (payload.priority, now, task_id))
            if payload.due_date is not None:
                conn.execute("UPDATE tasks SET due_date = ?, updated_at = ? WHERE id = ?", (payload.due_date, now, task_id))
            if payload.checklist is not None:
                conn.execute("UPDATE tasks SET checklist_json = ?, updated_at = ? WHERE id = ?", (json.dumps(payload.checklist), now, task_id))
            log_activity(conn, tsk["project_id"], uid, "task.updated", "task", task_id, f"Updated task '{tsk['title']}'")
        return {"message": "Task updated."}

    @router.delete("/tasks/{task_id}")
    def delete_task(
        task_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        uid = session["user_id"]
        with db.transaction() as conn:
            tsk = conn.execute("SELECT project_id, title FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not tsk:
                raise HTTPException(status_code=404, detail="Task not found.")
            require_project_permission(conn, tsk["project_id"], uid, Permission.TASK_WRITE)
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return {"message": "Task deleted."}

    # -------------------------------------------------------------------------
    # Research Documents, Version History & Optimistic Conflict Detection
    # -------------------------------------------------------------------------
    @router.get("/projects/{project_id}/documents")
    def list_documents(
        project_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.PROJECT_VIEW)
            rows = conn.execute(
                "SELECT d.*, u.full_name AS updated_by_name "
                "FROM documents d JOIN users u ON u.id = d.updated_by_id "
                "WHERE d.project_id = ? ORDER BY d.is_pinned DESC, d.updated_at DESC",
                (project_id,),
            ).fetchall()
            return {"documents": [dict(r) for r in rows]}

    @router.post("/projects/{project_id}/documents", status_code=201)
    def create_document(
        project_id: str,
        payload: DocumentCreateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        doc_id = f"doc_{uuid.uuid4().hex[:14]}"
        safe_html = sanitize_rich_text(payload.content_html)
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.DOC_WRITE)
            conn.execute(
                "INSERT INTO documents (id, project_id, title, content_html, current_version, is_pinned, review_status, "
                "created_by_id, updated_by_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 1, ?, 'draft', ?, ?, ?, ?)",
                (doc_id, project_id, payload.title.strip(), safe_html, int(payload.is_pinned), uid, uid, now, now),
            )
            conn.execute(
                "INSERT INTO document_versions (id, document_id, version_number, title, content_html, change_summary, author_id, created_at) "
                "VALUES (?, ?, 1, ?, ?, 'Initial version', ?, ?)",
                (uuid.uuid4().hex, doc_id, payload.title.strip(), safe_html, uid, now),
            )
            log_activity(conn, project_id, uid, "document.created", "document", doc_id, f"Created document '{payload.title.strip()}'")
        return {"id": doc_id, "title": payload.title.strip(), "current_version": 1, "content_html": safe_html}

    @router.get("/documents/{document_id}")
    def get_document(
        document_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            doc = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found.")
            require_project_permission(conn, doc["project_id"], uid, Permission.PROJECT_VIEW)
            return dict(doc)

    @router.patch("/documents/{document_id}")
    def update_document(
        document_id: str,
        payload: DocumentUpdateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        with db.transaction() as conn:
            doc = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found.")

            # If only review_status is being changed by a Reviewer, check DOC_REVIEW; otherwise require DOC_WRITE
            if payload.review_status is not None and payload.content_html == doc["content_html"]:
                require_project_permission(conn, doc["project_id"], uid, Permission.DOC_REVIEW)
            else:
                require_project_permission(conn, doc["project_id"], uid, Permission.DOC_WRITE)

            if payload.base_version != doc["current_version"]:
                raise HTTPException(
                    status_code=409,
                    detail=f"Version conflict: document is at v{doc['current_version']}, but edit was based on v{payload.base_version}.",
                )

            new_version = int(doc["current_version"]) + 1
            new_title = payload.title.strip() if payload.title else doc["title"]
            safe_html = sanitize_rich_text(payload.content_html)
            new_pinned = int(payload.is_pinned) if payload.is_pinned is not None else doc["is_pinned"]
            new_review = payload.review_status if payload.review_status is not None else doc["review_status"]

            conn.execute(
                "UPDATE documents SET title = ?, content_html = ?, current_version = ?, is_pinned = ?, "
                "review_status = ?, updated_by_id = ?, updated_at = ? WHERE id = ?",
                (new_title, safe_html, new_version, new_pinned, new_review, uid, now, document_id),
            )
            conn.execute(
                "INSERT INTO document_versions (id, document_id, version_number, title, content_html, change_summary, author_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, document_id, new_version, new_title, safe_html, payload.change_summary.strip(), uid, now),
            )
            log_activity(
                conn,
                doc["project_id"],
                uid,
                "document.updated",
                "document",
                document_id,
                f"Saved v{new_version} of '{new_title}'",
            )
            return {"id": document_id, "current_version": new_version, "content_html": safe_html, "review_status": new_review}

    @router.get("/documents/{document_id}/versions")
    def list_document_versions(
        document_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            doc = conn.execute("SELECT project_id FROM documents WHERE id = ?", (document_id,)).fetchone()
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found.")
            require_project_permission(conn, doc["project_id"], uid, Permission.PROJECT_VIEW)
            rows = conn.execute(
                "SELECT v.*, u.full_name AS author_name "
                "FROM document_versions v JOIN users u ON u.id = v.author_id "
                "WHERE v.document_id = ? ORDER BY v.version_number DESC",
                (document_id,),
            ).fetchall()
            return {"versions": [dict(r) for r in rows]}

    # -------------------------------------------------------------------------
    # Research Library & Citation Export
    # -------------------------------------------------------------------------
    @router.get("/projects/{project_id}/references")
    def list_references(
        project_id: str,
        q: Optional[str] = Query(default=None, max_length=200),
        year: Optional[int] = Query(default=None, ge=1000, le=2100),
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.PROJECT_VIEW)
            sql = "SELECT * FROM literature_references WHERE project_id = ?"
            params: list[Any] = [project_id]
            if q and q.strip():
                term = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                pat = f"%{term}%"
                sql += (" AND (LOWER(title) LIKE ? ESCAPE '\\' OR LOWER(authors) LIKE ? ESCAPE '\\' "
                        "OR LOWER(doi) LIKE ? ESCAPE '\\' OR LOWER(cite_key) LIKE ? ESCAPE '\\')")
                params += [pat, pat, pat, pat]
            if year is not None:
                sql += " AND year = ?"
                params.append(year)
            rows = conn.execute(sql + " ORDER BY year DESC, created_at DESC", params).fetchall()
            refs = []
            for r in rows:
                d = dict(r)
                d["keywords"] = json.loads(d["keywords"])
                d["tags"] = json.loads(d["tags"])
                d["fields"] = json.loads(d.pop("fields_json") or "{}")
                refs.append(d)
            return {"references": refs}

    @router.post("/projects/{project_id}/references", status_code=201)
    def create_reference(
        project_id: str,
        payload: ReferenceCreateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        ref_id = f"ref_{uuid.uuid4().hex[:14]}"
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.LIBRARY_WRITE)
            taken = {r["cite_key"] for r in conn.execute("SELECT cite_key FROM literature_references WHERE project_id = ?", (project_id,))}
            cite_key = make_cite_key(payload.authors, payload.year, payload.title, taken)
            bib_fields = {k: v for k, v in {
                "title": payload.title.strip(), "author": payload.authors.strip(), "year": str(payload.year),
                "doi": payload.doi.strip(), "journal": payload.journal_or_conference.strip(), "abstract": payload.abstract.strip(),
            }.items() if v}
            conn.execute(
                "INSERT INTO literature_references (id, project_id, title, authors, year, doi, journal_or_conference, "
                "abstract, keywords, tags, notes, created_by_id, created_at, cite_key, entry_type, fields_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'article', ?, ?)",
                (
                    ref_id,
                    project_id,
                    payload.title.strip(),
                    payload.authors.strip(),
                    payload.year,
                    payload.doi.strip(),
                    payload.journal_or_conference.strip(),
                    payload.abstract.strip(),
                    json.dumps(payload.keywords),
                    json.dumps(payload.tags),
                    payload.notes.strip(),
                    uid,
                    now,
                    cite_key,
                    json.dumps(bib_fields),
                    now,
                ),
            )
            log_activity(conn, project_id, uid, "reference.added", "reference", ref_id, f"Added paper '{payload.title.strip()}'")
        return {"id": ref_id, "title": payload.title.strip(), "cite_key": cite_key}

    @router.get("/projects/{project_id}/references/export", response_class=PlainTextResponse)
    def export_references(
        project_id: str,
        format: str = Query("bibtex", pattern="^(bibtex|ris)$"),
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> str:
        uid = session["user_id"]
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.PROJECT_VIEW)
            rows = conn.execute(
                "SELECT * FROM literature_references WHERE project_id = ? ORDER BY year DESC",
                (project_id,),
            ).fetchall()
            if format == "bibtex":
                entries = [serialize_entry(*entry_from_row(r)) for r in rows]
                return "\n\n".join(entries)
            else:
                entries = []
                for r in rows:
                    entries.append(
                        f"TY  - JOUR\nTI  - {r['title']}\nAU  - {r['authors']}\nPY  - {r['year']}\n"
                        f"JO  - {r['journal_or_conference']}\nDO  - {r['doi']}\nER  - "
                    )
                return "\n\n".join(entries)

    # -------------------------------------------------------------------------
    # Private Files & Datasets Upload / Download
    # -------------------------------------------------------------------------
    @router.post("/projects/{project_id}/files", status_code=201)
    async def upload_project_file(
        project_id: str,
        request: Request,
        file: UploadFile = File(...),
        folder: str = Form("/"),
        description: str = Form(""),
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        enforce_rate_limit(request, "file_upload", settings.rate_limit_upload_per_minute)
        uid = session["user_id"]
        content = await file.read()
        filename = file.filename or "unnamed"

        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.FILE_UPLOAD)
            proj = conn.execute("SELECT storage_used_bytes FROM projects WHERE id = ?", (project_id,)).fetchone()
            current_used = int(proj["storage_used_bytes"])
            if current_used + len(content) > settings.project_storage_quota_bytes:
                raise HTTPException(status_code=413, detail="Project storage quota exceeded.")

            try:
                stored = storage.store_bytes(project_id, filename, content)
            except StorageSecurityError as exc:
                log_audit(conn, "UPLOAD_REJECTED", str(exc), actor_id=uid, project_id=project_id)
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            now = utc_now_iso()
            existing = conn.execute(
                "SELECT id, current_version FROM datasets_files WHERE project_id = ? AND folder = ? AND original_name = ?",
                (project_id, folder, stored["original_name"]),
            ).fetchone()

            if existing:
                file_id = existing["id"]
                new_ver = int(existing["current_version"]) + 1
                conn.execute(
                    "UPDATE datasets_files SET storage_key = ?, size_bytes = ?, media_type = ?, "
                    "checksum_sha256 = ?, current_version = ?, uploaded_by_id = ?, updated_at = ? WHERE id = ?",
                    (
                        stored["storage_key"],
                        stored["size_bytes"],
                        stored["media_type"],
                        stored["checksum_sha256"],
                        new_ver,
                        uid,
                        now,
                        file_id,
                    ),
                )
            else:
                file_id = f"fil_{uuid.uuid4().hex[:14]}"
                new_ver = 1
                conn.execute(
                    "INSERT INTO datasets_files (id, project_id, folder, original_name, storage_key, size_bytes, "
                    "media_type, checksum_sha256, description, current_version, uploaded_by_id, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                    (
                        file_id,
                        project_id,
                        folder,
                        stored["original_name"],
                        stored["storage_key"],
                        stored["size_bytes"],
                        stored["media_type"],
                        stored["checksum_sha256"],
                        description.strip(),
                        uid,
                        now,
                        now,
                    ),
                )

            conn.execute(
                "INSERT INTO file_versions (id, file_id, version_number, storage_key, size_bytes, checksum_sha256, uploaded_by_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex,
                    file_id,
                    new_ver,
                    stored["storage_key"],
                    stored["size_bytes"],
                    stored["checksum_sha256"],
                    uid,
                    now,
                ),
            )
            conn.execute(
                "UPDATE projects SET storage_used_bytes = storage_used_bytes + ?, updated_at = ? WHERE id = ?",
                (stored["size_bytes"], now, project_id),
            )
            log_activity(
                conn,
                project_id,
                uid,
                "file.uploaded",
                "file",
                file_id,
                f"Uploaded '{stored['original_name']}' (v{new_ver})",
            )
            return {
                "id": file_id,
                "original_name": stored["original_name"],
                "size_bytes": stored["size_bytes"],
                "media_type": stored["media_type"],
                "checksum_sha256": stored["checksum_sha256"],
                "current_version": new_ver,
            }

    @router.get("/projects/{project_id}/files")
    def list_project_files(
        project_id: str,
        trash: bool = Query(default=False),
        limit: int = Query(default=500, ge=1, le=2000),
        offset: int = Query(default=0, ge=0),
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.PROJECT_VIEW)
            rows = conn.execute(
                "SELECT f.id, f.project_id, f.folder, f.original_name, f.size_bytes, f.media_type, f.checksum_sha256, "
                "f.description, f.current_version, f.uploaded_by_id, f.created_at, f.updated_at, f.artifact_type, f.tags, "
                "f.is_deleted, f.deleted_at, f.linked_entity_type, f.linked_entity_id, u.full_name AS owner_name "
                "FROM datasets_files f JOIN users u ON u.id = f.uploaded_by_id "
                "WHERE f.project_id = ? AND f.is_deleted = ? ORDER BY f.updated_at DESC LIMIT ? OFFSET ?",
                (project_id, int(trash), limit, offset),
            ).fetchall()
            files = []
            for r in rows:
                d = dict(r)
                d["tags"] = json.loads(d["tags"] or "[]")
                files.append(d)
            return {"files": files}

    @router.get("/files/{file_id}/versions")
    def list_project_file_versions(
        file_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            row = conn.execute("SELECT project_id FROM datasets_files WHERE id = ?", (file_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="File not found.")
            require_project_permission(conn, row["project_id"], uid, Permission.PROJECT_VIEW)
            rows = conn.execute(
                "SELECT v.id, v.version_number, v.size_bytes, v.checksum_sha256, v.created_at, u.full_name AS author_name "
                "FROM file_versions v JOIN users u ON u.id = v.uploaded_by_id WHERE v.file_id = ? ORDER BY v.version_number DESC",
                (file_id,),
            ).fetchall()
            return {"versions": [dict(r) for r in rows]}

    @router.get("/files/{file_id}/versions/{version_number}/content")
    def download_project_file_version(
        file_id: str,
        version_number: int,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> RawResponse:
        uid = session["user_id"]
        with db.transaction() as conn:
            row = conn.execute("SELECT project_id, original_name, media_type FROM datasets_files WHERE id = ?", (file_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="File not found.")
            require_project_permission(conn, row["project_id"], uid, Permission.PROJECT_VIEW)
            ver = conn.execute(
                "SELECT storage_key FROM file_versions WHERE file_id = ? AND version_number = ?", (file_id, version_number)
            ).fetchone()
            if not ver or not storage.exists(ver["storage_key"]):
                raise HTTPException(status_code=404, detail="Version not found.")
        return FileResponse(
            storage.path_for(ver["storage_key"]),
            media_type=row["media_type"],
            headers={"Content-Disposition": content_disposition(row["original_name"]), "X-Content-Type-Options": "nosniff"},
        )

    @router.post("/files/{file_id}/download")
    def download_project_file(
        file_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> RawResponse:
        uid = session["user_id"]
        with db.transaction() as conn:
            row = conn.execute("SELECT * FROM datasets_files WHERE id = ?", (file_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="File not found.")
            require_project_permission(conn, row["project_id"], uid, Permission.PROJECT_VIEW)
            log_audit(
                conn,
                "FILE_DOWNLOADED",
                f"Downloaded {row['original_name']} ({file_id})",
                actor_id=uid,
                project_id=row["project_id"],
            )
        try:
            blob_path = storage.path_for(row["storage_key"])
        except (FileNotFoundError, StorageSecurityError) as exc:
            raise HTTPException(status_code=404, detail="Stored file is missing.") from exc
        return FileResponse(
            blob_path,
            media_type=row["media_type"],
            headers={"Content-Disposition": content_disposition(row["original_name"]), "X-Content-Type-Options": "nosniff"},
        )

    @router.patch("/files/{file_id}")
    def update_project_file_metadata(
        file_id: str,
        payload: FileMetadataUpdateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        with db.transaction() as conn:
            row = conn.execute("SELECT * FROM datasets_files WHERE id = ?", (file_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="File not found.")
            require_project_permission(conn, row["project_id"], uid, Permission.FILE_UPLOAD)
            if payload.original_name is not None:
                conn.execute(
                    "UPDATE datasets_files SET original_name = ?, last_editor_name = ?, updated_at = ? WHERE id = ?",
                    (payload.original_name.strip(), session["full_name"], now, file_id),
                )
            if payload.folder is not None:
                conn.execute(
                    "UPDATE datasets_files SET folder = ?, last_editor_name = ?, updated_at = ? WHERE id = ?",
                    (payload.folder.strip(), session["full_name"], now, file_id),
                )
            if payload.tags is not None:
                conn.execute(
                    "UPDATE datasets_files SET tags = ?, last_editor_name = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(payload.tags), session["full_name"], now, file_id),
                )
            if payload.linked_entity_type is not None:
                conn.execute(
                    "UPDATE datasets_files SET linked_entity_type = ?, updated_at = ? WHERE id = ?",
                    (payload.linked_entity_type.strip(), now, file_id),
                )
            if payload.linked_entity_id is not None:
                conn.execute(
                    "UPDATE datasets_files SET linked_entity_id = ?, updated_at = ? WHERE id = ?",
                    (payload.linked_entity_id.strip(), now, file_id),
                )
            log_activity(conn, row["project_id"], uid, "file.updated", "file", file_id, f"Updated file metadata for '{row['original_name']}'")
        return {"message": "File updated."}

    @router.delete("/files/{file_id}")
    def delete_project_file(
        file_id: str,
        permanent: bool = Query(default=False),
        force: bool = Query(default=False),
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        with db.transaction() as conn:
            row = conn.execute("SELECT * FROM datasets_files WHERE id = ?", (file_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="File not found.")
            require_project_permission(conn, row["project_id"], uid, Permission.FILE_DELETE)

            if row["linked_entity_id"] and not force:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"File '{row['original_name']}' is linked to {row['linked_entity_type'] or 'record'} "
                        f"({row['linked_entity_id']}). Pass force=true to confirm deletion."
                    ),
                )

            if not permanent and not row["is_deleted"]:
                conn.execute(
                    "UPDATE datasets_files SET is_deleted = 1, deleted_at = ?, last_editor_name = ?, updated_at = ? WHERE id = ?",
                    (now, session["full_name"], now, file_id),
                )
                log_activity(conn, row["project_id"], uid, "file.trashed", "file", file_id, f"Moved '{row['original_name']}' to Trash")
                return {"message": "File moved to Trash.", "status": "trashed"}

            storage.delete_key(row["storage_key"])
            conn.execute("DELETE FROM datasets_files WHERE id = ?", (file_id,))
            conn.execute(
                "UPDATE projects SET storage_used_bytes = MAX(0, storage_used_bytes - ?) WHERE id = ?",
                (row["size_bytes"], row["project_id"]),
            )
            log_activity(conn, row["project_id"], uid, "file.deleted", "file", file_id, f"Permanently deleted '{row['original_name']}'")
            log_audit(conn, "FILE_DELETED", f"Deleted file {file_id}", actor_id=uid, project_id=row["project_id"])
        return {"message": "File permanently deleted.", "status": "deleted"}

    @router.post("/files/{file_id}/restore")
    def restore_project_file(
        file_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        uid = session["user_id"]
        now = utc_now_iso()
        with db.transaction() as conn:
            row = conn.execute("SELECT * FROM datasets_files WHERE id = ?", (file_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="File not found.")
            require_project_permission(conn, row["project_id"], uid, Permission.FILE_DELETE)
            conn.execute(
                "UPDATE datasets_files SET is_deleted = 0, deleted_at = NULL, last_editor_name = ?, updated_at = ? WHERE id = ?",
                (session["full_name"], now, file_id),
            )
            log_activity(conn, row["project_id"], uid, "file.restored", "file", file_id, f"Restored '{row['original_name']}' from Trash")
        return {"message": "File restored from Trash."}

    # -------------------------------------------------------------------------
    # Experiment Tracker
    # -------------------------------------------------------------------------
    @router.get("/projects/{project_id}/experiments")
    def list_experiments(
        project_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.PROJECT_VIEW)
            rows = conn.execute(
                "SELECT * FROM experiment_runs WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
            experiments = []
            for r in rows:
                d = dict(r)
                d["parameters"] = json.loads(d.pop("parameters_json"))
                metrics_rows = conn.execute(
                    "SELECT metric_name, metric_value FROM experiment_metrics WHERE experiment_id = ?",
                    (d["id"],),
                ).fetchall()
                d["metrics"] = {m["metric_name"]: m["metric_value"] for m in metrics_rows}
                experiments.append(d)
            return {"experiments": experiments}

    @router.post("/projects/{project_id}/experiments", status_code=201)
    def create_experiment(
        project_id: str,
        payload: ExperimentCreateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        exp_id = f"exp_{uuid.uuid4().hex[:14]}"
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.EXPERIMENT_WRITE)
            conn.execute(
                "INSERT INTO experiment_runs (id, project_id, name, objective, dataset_ref, dataset_version, "
                "method_or_model, parameters_json, repo_url, commit_sha, environment_details, results_summary, status, created_by_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    exp_id,
                    project_id,
                    payload.name.strip(),
                    payload.objective.strip(),
                    payload.dataset_ref.strip(),
                    payload.dataset_version.strip(),
                    payload.method_or_model.strip(),
                    json.dumps(payload.parameters),
                    payload.repo_url.strip(),
                    payload.commit_sha.strip(),
                    payload.environment_details.strip(),
                    payload.results_summary.strip(),
                    payload.status,
                    uid,
                    now,
                ),
            )
            for m_name, m_val in payload.metrics.items():
                conn.execute(
                    "INSERT INTO experiment_metrics (id, experiment_id, metric_name, metric_value, step) "
                    "VALUES (?, ?, ?, ?, 1)",
                    (uuid.uuid4().hex, exp_id, m_name, float(m_val)),
                )
            log_activity(conn, project_id, uid, "experiment.logged", "experiment", exp_id, f"Logged experiment '{payload.name.strip()}'")
        return {"id": exp_id, "name": payload.name.strip(), "metrics": payload.metrics}

    # -------------------------------------------------------------------------
    # Discussions, Comments, Activity & Global Search
    # -------------------------------------------------------------------------
    @router.post("/projects/{project_id}/comments", status_code=201)
    def create_comment(
        project_id: str,
        payload: CommentCreateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        comment_id = f"cmt_{uuid.uuid4().hex[:14]}"
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.COMMENT_WRITE)
            conn.execute(
                "INSERT INTO comments (id, project_id, target_type, target_id, body, author_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (comment_id, project_id, payload.target_type, payload.target_id, payload.body.strip(), uid, now),
            )
            log_activity(conn, project_id, uid, "comment.posted", payload.target_type, payload.target_id, "Added review comment")
        return {"id": comment_id, "body": payload.body.strip()}

    @router.get("/projects/{project_id}/activity")
    def list_project_activity(
        project_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.PROJECT_VIEW)
            rows = conn.execute(
                "SELECT a.*, u.username AS actor_username, u.full_name AS actor_name "
                "FROM activity_events a JOIN users u ON u.id = a.actor_id "
                "WHERE a.project_id = ? ORDER BY a.created_at DESC LIMIT 50",
                (project_id,),
            ).fetchall()
            return {"activity": [dict(r) for r in rows]}

    @router.get("/notifications")
    def list_notifications(session: Dict[str, Any] = Depends(get_current_session_and_user)) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
                (uid,),
            ).fetchall()
            return {"notifications": [dict(r) for r in rows]}

    @router.patch("/notifications/{notification_id}")
    def mark_notification_read(
        notification_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        uid = session["user_id"]
        with db.transaction() as conn:
            row = conn.execute("SELECT user_id FROM notifications WHERE id = ?", (notification_id,)).fetchone()
            if not row or row["user_id"] != uid:
                raise HTTPException(status_code=404, detail="Notification not found.")
            conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))
        return {"message": "Notification marked as read."}

    @router.patch("/references/{reference_id}")
    def update_reference(
        reference_id: str,
        payload: ReferenceUpdateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        uid = session["user_id"]
        with db.transaction() as conn:
            ref = conn.execute("SELECT project_id, title FROM literature_references WHERE id = ?", (reference_id,)).fetchone()
            if not ref:
                raise HTTPException(status_code=404, detail="Reference not found.")
            require_project_permission(conn, ref["project_id"], uid, Permission.LIBRARY_WRITE)
            if payload.title is not None:
                conn.execute("UPDATE literature_references SET title = ? WHERE id = ?", (payload.title.strip(), reference_id))
            if payload.authors is not None:
                conn.execute("UPDATE literature_references SET authors = ? WHERE id = ?", (payload.authors.strip(), reference_id))
            if payload.year is not None:
                conn.execute("UPDATE literature_references SET year = ? WHERE id = ?", (payload.year, reference_id))
            if payload.doi is not None:
                conn.execute("UPDATE literature_references SET doi = ? WHERE id = ?", (payload.doi.strip(), reference_id))
            if payload.notes is not None:
                conn.execute("UPDATE literature_references SET notes = ? WHERE id = ?", (payload.notes.strip(), reference_id))
            if payload.journal_or_conference is not None:
                conn.execute("UPDATE literature_references SET journal_or_conference = ? WHERE id = ?",
                             (payload.journal_or_conference.strip(), reference_id))
            if payload.abstract is not None:
                conn.execute("UPDATE literature_references SET abstract = ? WHERE id = ?", (payload.abstract.strip(), reference_id))
            # Keep the BibTeX field map (the export source of truth) consistent with the edited columns.
            fields_row = conn.execute("SELECT fields_json FROM literature_references WHERE id = ?", (reference_id,)).fetchone()
            fields = json.loads(fields_row["fields_json"] or "{}")
            for field_name, value in (("title", payload.title), ("author", payload.authors), ("year", payload.year),
                                      ("doi", payload.doi), ("abstract", payload.abstract)):
                if value is not None:
                    fields[field_name] = str(value).strip()
            if payload.journal_or_conference is not None:
                fields["booktitle" if "booktitle" in fields else "journal"] = payload.journal_or_conference.strip()
            conn.execute("UPDATE literature_references SET fields_json = ?, updated_at = ? WHERE id = ?",
                         (json.dumps(fields), utc_now_iso(), reference_id))
        return {"message": "Reference updated."}

    @router.delete("/references/{reference_id}")
    def delete_reference(
        reference_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        uid = session["user_id"]
        with db.transaction() as conn:
            ref = conn.execute("SELECT project_id FROM literature_references WHERE id = ?", (reference_id,)).fetchone()
            if not ref:
                raise HTTPException(status_code=404, detail="Reference not found.")
            require_project_permission(conn, ref["project_id"], uid, Permission.LIBRARY_WRITE)
            conn.execute("DELETE FROM literature_references WHERE id = ?", (reference_id,))
        return {"message": "Reference deleted."}

    @router.patch("/experiments/{experiment_id}")
    def update_experiment(
        experiment_id: str,
        payload: ExperimentUpdateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        uid = session["user_id"]
        with db.transaction() as conn:
            exp = conn.execute("SELECT project_id FROM experiment_runs WHERE id = ?", (experiment_id,)).fetchone()
            if not exp:
                raise HTTPException(status_code=404, detail="Experiment not found.")
            require_project_permission(conn, exp["project_id"], uid, Permission.EXPERIMENT_WRITE)
            if payload.name is not None:
                conn.execute("UPDATE experiment_runs SET name = ? WHERE id = ?", (payload.name.strip(), experiment_id))
            if payload.objective is not None:
                conn.execute("UPDATE experiment_runs SET objective = ? WHERE id = ?", (payload.objective.strip(), experiment_id))
            if payload.results_summary is not None:
                conn.execute("UPDATE experiment_runs SET results_summary = ? WHERE id = ?", (payload.results_summary.strip(), experiment_id))
            if payload.status is not None:
                conn.execute("UPDATE experiment_runs SET status = ? WHERE id = ?", (payload.status, experiment_id))
        return {"message": "Experiment updated."}

    @router.get("/search")
    def global_search(
        request: Request,
        q: str = Query(..., min_length=1, max_length=100),
        category: Optional[str] = Query(default=None, pattern="^(projects|manuscripts|source_files|files|tasks|references|experiments|artifacts|members)$"),
        limit: int = Query(default=6, ge=1, le=50),
        offset: int = Query(default=0, ge=0, le=5000),
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        """Search only within projects the caller belongs to. Membership is enforced in every query via JOIN."""
        enforce_rate_limit(request, "global_search", 60)
        uid = session["user_id"]
        escaped = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pat = f"%{escaped}%"
        esc = " ESCAPE '\\'"
        member_join = "JOIN project_memberships m ON m.project_id = {alias}.project_id AND m.user_id = ? "
        queries: dict[str, tuple[str, int]] = {
            "projects": (
                "SELECT p.id, p.id AS project_id, p.title, p.research_domain, p.status, p.publication_status, p.updated_at FROM projects p "  # noqa: S608 - fixed SQL text; every user value is a bound ? parameter
                "JOIN project_memberships m ON m.project_id = p.id AND m.user_id = ? "
                f"WHERE (LOWER(p.title) LIKE ?{esc} OR LOWER(p.description) LIKE ?{esc} OR LOWER(p.research_domain) LIKE ?{esc} "
                f"OR EXISTS (SELECT 1 FROM project_memberships pm2 JOIN users u2 ON u2.id = pm2.user_id WHERE pm2.project_id = p.id "
                f"AND (LOWER(u2.full_name) LIKE ?{esc} OR LOWER(u2.username) LIKE ?{esc}))) ORDER BY p.updated_at DESC",
                5,
            ),
            "manuscripts": (
                "SELECT d.id, d.project_id, d.title, d.publication_status AS status, d.doc_kind, d.updated_at, p.title AS project_title "
                "FROM documents d JOIN projects p ON p.id = d.project_id " + member_join.format(alias="d") +
                f"WHERE d.is_deleted = 0 AND LOWER(d.title) LIKE ?{esc} ORDER BY d.updated_at DESC",
                1,
            ),
            "source_files": (
                "SELECT f.id, f.project_id, f.document_id, f.path AS title, d.title AS manuscript_title, f.updated_at "
                "FROM manuscript_files f JOIN documents d ON d.id = f.document_id " + member_join.format(alias="f") +
                f"WHERE f.is_deleted = 0 AND d.is_deleted = 0 AND f.file_kind != 'folder' "
                f"AND (LOWER(f.path) LIKE ?{esc} OR LOWER(f.text_content) LIKE ?{esc}) ORDER BY f.updated_at DESC",
                2,
            ),
            "files": (
                "SELECT f.id, f.project_id, f.original_name AS title, f.folder, f.media_type, f.artifact_type, f.updated_at FROM datasets_files f "  # noqa: S608 - fixed SQL text; every user value is a bound ? parameter
                + member_join.format(alias="f") +
                f"WHERE f.is_deleted = 0 AND (LOWER(f.original_name) LIKE ?{esc} OR LOWER(f.description) LIKE ?{esc} OR LOWER(f.tags) LIKE ?{esc}) "
                "ORDER BY f.updated_at DESC",
                3,
            ),
            "tasks": (
                "SELECT t.id, t.project_id, t.title, t.status, t.priority, t.updated_at FROM tasks t " + member_join.format(alias="t") +  # noqa: S608 - fixed SQL text; every user value is a bound ? parameter
                f"WHERE LOWER(t.title) LIKE ?{esc} OR LOWER(t.description) LIKE ?{esc} ORDER BY t.updated_at DESC",
                2,
            ),
            "references": (
                "SELECT r.id, r.project_id, r.title, r.authors, r.year, r.doi, r.cite_key FROM literature_references r " + member_join.format(alias="r") +  # noqa: S608 - fixed SQL text; every user value is a bound ? parameter
                f"WHERE LOWER(r.title) LIKE ?{esc} OR LOWER(r.authors) LIKE ?{esc} OR LOWER(r.doi) LIKE ?{esc} OR LOWER(r.cite_key) LIKE ?{esc} "
                "ORDER BY r.year DESC",
                4,
            ),
            "experiments": (
                "SELECT e.id, e.project_id, e.name AS title, e.method_or_model, e.status, e.created_at FROM experiment_runs e "  # noqa: S608 - fixed SQL text; every user value is a bound ? parameter
                + member_join.format(alias="e") +
                f"WHERE LOWER(e.name) LIKE ?{esc} OR LOWER(e.method_or_model) LIKE ?{esc} OR LOWER(e.objective) LIKE ?{esc} ORDER BY e.created_at DESC",
                3,
            ),
            "artifacts": (
                "SELECT a.id, a.project_id, a.name AS title, a.artifact_type, a.language, a.updated_at FROM research_artifacts a "  # noqa: S608 - fixed SQL text; every user value is a bound ? parameter
                + member_join.format(alias="a") +
                f"WHERE LOWER(a.name) LIKE ?{esc} OR LOWER(a.notes) LIKE ?{esc} ORDER BY a.updated_at DESC",
                2,
            ),
            "members": (
                "SELECT DISTINCT u.id, u.username, u.full_name AS title, pm.role, pm.project_id, p.title AS project_title "  # noqa: S608 - fixed SQL text; every user value is a bound ? parameter
                "FROM project_memberships pm JOIN project_memberships my_m ON my_m.project_id = pm.project_id AND my_m.user_id = ? "
                "JOIN users u ON u.id = pm.user_id JOIN projects p ON p.id = pm.project_id "
                f"WHERE LOWER(u.username) LIKE ?{esc} OR LOWER(u.full_name) LIKE ?{esc} ORDER BY u.full_name",
                2,
            ),
        }
        wanted = [category] if category else list(queries)
        results: Dict[str, Any] = {}
        with db.transaction() as conn:
            for name in wanted:
                sql, n_patterns = queries[name]
                rows = conn.execute(
                    sql + " LIMIT ? OFFSET ?", (uid, *([pat] * n_patterns), limit + 1, offset)
                ).fetchall()
                items = [dict(r) for r in rows[:limit]]
                results[name] = items
                results.setdefault("has_more", {})[name] = len(rows) > limit
        # Backwards-compatible keys used by the earlier client.
        results.setdefault("documents", results.get("manuscripts", []))
        return results


    # -------------------------------------------------------------------------
    # Authoritative Project Publication Status (Owner Only)
    # -------------------------------------------------------------------------
    @router.patch("/projects/{project_id}/publication-status")
    def update_project_publication_status(
        project_id: str,
        payload: PublicationStatusUpdateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.PUBLICATION_STATUS_MANAGE)
            conn.execute(
                "UPDATE projects SET publication_status = ?, last_editor_id = ?, last_editor_name = ?, "
                "last_edited_at = ?, updated_at = ? WHERE id = ?",
                (payload.publication_status, uid, session["full_name"], now, now, project_id),
            )
            # Notify other project members
            members = conn.execute(
                "SELECT user_id FROM project_memberships WHERE project_id = ? AND user_id != ?",
                (project_id, uid),
            ).fetchall()
            for m in members:
                ctx.notify(conn, m["user_id"], project_id, "publication_status", "Publication Status Updated",
                           f"{session['full_name']} updated publication status to '{payload.publication_status}'.")
            log_activity(
                conn,
                project_id,
                uid,
                "publication_status.updated",
                "project",
                project_id,
                f"Updated publication status to '{payload.publication_status}'",
            )
            log_audit(
                conn,
                "PUBLICATION_STATUS_UPDATED",
                f"Set publication_status={payload.publication_status}",
                actor_id=uid,
                project_id=project_id,
            )
            return {
                "project_id": project_id,
                "publication_status": payload.publication_status,
                "last_editor_name": session["full_name"],
                "last_edited_at": now,
            }

    # -------------------------------------------------------------------------
    # Chunked / Resumable Large File Uploads (No Arbitrary Low App Cap)
    # -------------------------------------------------------------------------
    @router.post("/projects/{project_id}/uploads/init", status_code=201)
    def init_chunked_upload(
        project_id: str,
        payload: UploadInitRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        upload_id = f"upl_{uuid.uuid4().hex[:16]}"
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.FILE_UPLOAD)
            try:
                temp_key = storage.init_staging_file(upload_id)
            except StorageSecurityError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            conn.execute(
                "INSERT INTO upload_sessions (id, project_id, user_id, filename, folder, artifact_type, "
                "total_size_bytes, total_chunks, uploaded_chunks, bytes_received, status, temp_key, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 'in_progress', ?, ?, ?)",
                (
                    upload_id,
                    project_id,
                    uid,
                    payload.filename.strip(),
                    payload.folder.strip(),
                    payload.artifact_type.strip(),
                    payload.total_size_bytes,
                    payload.total_chunks,
                    temp_key,
                    now,
                    now,
                ),
            )
            return {
                "upload_id": upload_id,
                "status": "in_progress",
                "total_chunks": payload.total_chunks,
                "total_size_bytes": payload.total_size_bytes,
            }

    @router.put("/uploads/{upload_id}/chunks/{chunk_index}")
    async def upload_chunk_part(
        upload_id: str,
        chunk_index: int,
        request: Request,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        chunk_bytes = await request.body()
        if not chunk_bytes:
            raise HTTPException(status_code=400, detail="Chunk body cannot be empty.")
        now = utc_now_iso()
        with db.transaction() as conn:
            upl = conn.execute("SELECT * FROM upload_sessions WHERE id = ?", (upload_id,)).fetchone()
            if not upl or upl["user_id"] != uid:
                raise HTTPException(status_code=404, detail="Upload session not found.")
            if upl["status"] != "in_progress":
                raise HTTPException(status_code=400, detail=f"Upload session is '{upl['status']}'.")
            expected = int(upl["uploaded_chunks"])
            if chunk_index < expected:
                # Retried chunk that was already stored: acknowledge without appending twice.
                return {"upload_id": upload_id, "chunk_index": chunk_index, "uploaded_chunks": expected,
                        "bytes_received": int(upl["bytes_received"]), "duplicate": True}
            if chunk_index > expected:
                raise HTTPException(status_code=409, detail={"message": "Chunks must be sent in order.", "expected_chunk": expected})
            if int(upl["bytes_received"]) + len(chunk_bytes) > int(upl["total_size_bytes"]):
                raise HTTPException(status_code=400, detail="Chunk exceeds the declared file size.")
            total_received = storage.append_staging_chunk(upl["temp_key"], chunk_bytes)
            uploaded_chunks = expected + 1
            conn.execute(
                "UPDATE upload_sessions SET uploaded_chunks = ?, bytes_received = ?, updated_at = ? WHERE id = ?",
                (uploaded_chunks, total_received, now, upload_id),
            )
            return {
                "upload_id": upload_id,
                "chunk_index": chunk_index,
                "uploaded_chunks": uploaded_chunks,
                "bytes_received": total_received,
            }

    @router.post("/uploads/{upload_id}/complete")
    def complete_chunked_upload(
        upload_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        with db.transaction() as conn:
            upl = conn.execute("SELECT * FROM upload_sessions WHERE id = ?", (upload_id,)).fetchone()
            if not upl or upl["user_id"] != uid:
                raise HTTPException(status_code=404, detail="Upload session not found.")
            if upl["status"] != "in_progress":
                raise HTTPException(status_code=400, detail="Upload session is not active.")
            require_project_permission(conn, upl["project_id"], uid, Permission.FILE_UPLOAD)
            received = storage.staging_size(upl["temp_key"])
            if received != int(upl["total_size_bytes"]):
                raise HTTPException(
                    status_code=409,
                    detail={"message": "Upload is incomplete.", "bytes_received": received, "expected_chunk": int(upl["uploaded_chunks"])},
                )
            proj_row = conn.execute("SELECT storage_used_bytes FROM projects WHERE id = ?", (upl["project_id"],)).fetchone()
            if int(proj_row["storage_used_bytes"]) + received > settings.project_storage_quota_bytes:
                raise HTTPException(status_code=413, detail="Project storage quota exceeded.")
            try:
                stored = storage.finalize_staging_upload(upl["project_id"], upl["filename"], upl["temp_key"])
            except StorageSecurityError as exc:
                conn.execute("UPDATE upload_sessions SET status = 'failed', updated_at = ? WHERE id = ?", (now, upload_id))
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            # Same name in the same folder becomes a new version, matching direct uploads.
            existing = conn.execute(
                "SELECT id, current_version FROM datasets_files WHERE project_id = ? AND folder = ? AND original_name = ? AND is_deleted = 0",
                (upl["project_id"], upl["folder"], stored["original_name"]),
            ).fetchone()
            if existing:
                file_id = existing["id"]
                new_ver = int(existing["current_version"]) + 1
                conn.execute(
                    "UPDATE datasets_files SET storage_key = ?, size_bytes = ?, media_type = ?, checksum_sha256 = ?, current_version = ?, "
                    "last_editor_name = ?, uploaded_by_id = ?, updated_at = ? WHERE id = ?",
                    (stored["storage_key"], stored["size_bytes"], stored["media_type"], stored["checksum_sha256"], new_ver,
                     session["full_name"], uid, now, file_id),
                )
            else:
                file_id = f"fil_{uuid.uuid4().hex[:14]}"
                new_ver = 1
                conn.execute(
                    "INSERT INTO datasets_files (id, project_id, folder, original_name, storage_key, size_bytes, "
                    "media_type, checksum_sha256, artifact_type, description, current_version, last_editor_name, uploaded_by_id, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', 1, ?, ?, ?, ?)",
                    (
                        file_id,
                        upl["project_id"],
                        upl["folder"],
                        stored["original_name"],
                        stored["storage_key"],
                        stored["size_bytes"],
                        stored["media_type"],
                        stored["checksum_sha256"],
                        upl["artifact_type"],
                        session["full_name"],
                        uid,
                        now,
                        now,
                    ),
                )
            conn.execute(
                "INSERT INTO file_versions (id, file_id, version_number, storage_key, size_bytes, checksum_sha256, uploaded_by_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, file_id, new_ver, stored["storage_key"], stored["size_bytes"], stored["checksum_sha256"], uid, now),
            )
            conn.execute("UPDATE upload_sessions SET status = 'completed', updated_at = ? WHERE id = ?", (now, upload_id))
            conn.execute(
                "UPDATE projects SET storage_used_bytes = storage_used_bytes + ?, updated_at = ? WHERE id = ?",
                (stored["size_bytes"], now, upl["project_id"]),
            )
            log_activity(
                conn,
                upl["project_id"],
                uid,
                "file.chunked_upload",
                "file",
                file_id,
                f"Completed chunked upload of '{stored['original_name']}' ({stored['size_bytes']} bytes)",
            )
            return {
                "file_id": file_id,
                "original_name": stored["original_name"],
                "size_bytes": stored["size_bytes"],
                "checksum_sha256": stored["checksum_sha256"],
                "status": "completed",
            }

    @router.get("/uploads/{upload_id}")
    def get_chunked_upload(
        upload_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        """Resume support: report how many chunks the server already holds."""
        with db.transaction() as conn:
            upl = conn.execute("SELECT * FROM upload_sessions WHERE id = ?", (upload_id,)).fetchone()
            if not upl or upl["user_id"] != session["user_id"]:
                raise HTTPException(status_code=404, detail="Upload session not found.")
            return {k: upl[k] for k in ("id", "filename", "status", "total_chunks", "uploaded_chunks", "bytes_received", "total_size_bytes")}

    @router.delete("/uploads/{upload_id}")
    def cancel_chunked_upload(
        upload_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        uid = session["user_id"]
        now = utc_now_iso()
        with db.transaction() as conn:
            upl = conn.execute("SELECT * FROM upload_sessions WHERE id = ?", (upload_id,)).fetchone()
            if not upl or upl["user_id"] != uid:
                raise HTTPException(status_code=404, detail="Upload session not found.")
            storage.remove_staging_file(upl["temp_key"])
            conn.execute("UPDATE upload_sessions SET status = 'cancelled', updated_at = ? WHERE id = ?", (now, upload_id))
            return {"message": "Upload session cancelled and staging data cleaned up."}

    # -------------------------------------------------------------------------
    # LaTeX Paper & Individual Section Generator + Validator
    # -------------------------------------------------------------------------
    @router.get("/documents/{document_id}/latex")
    def generate_document_latex(
        document_id: str,
        template: str = Query(default="article", pattern="^(article|ieee|acm|custom)$"),
        section: str = Query(default="all"),
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            doc = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found.")
            require_project_permission(conn, doc["project_id"], uid, Permission.PROJECT_VIEW)
            proj = conn.execute("SELECT * FROM projects WHERE id = ?", (doc["project_id"],)).fetchone()
            members = conn.execute(
                "SELECT u.full_name, u.email FROM project_memberships pm JOIN users u ON u.id = pm.user_id "
                "WHERE pm.project_id = ? ORDER BY pm.joined_at ASC",
                (doc["project_id"],),
            ).fetchall()
            refs = conn.execute(
                "SELECT * FROM literature_references WHERE project_id = ? ORDER BY year DESC",
                (doc["project_id"],),
            ).fetchall()

            raw_html = doc["content_html"] or ""
            # Extract headings and paragraphs from HTML without inventing missing content
            sec_matches = re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>(.*?)(?=<h[1-3]|$)", raw_html, flags=re.DOTALL | re.IGNORECASE)
            parsed_sections: list[tuple[str, str]] = []
            for h_title, body_part in sec_matches:
                clean_h = re.sub(r"<[^>]+>", "", h_title).strip()
                clean_b = re.sub(r"<[^>]+>", " ", body_part).strip()
                if clean_h or clean_b:
                    parsed_sections.append((clean_h or "Section", clean_b))
            if not parsed_sections:
                plain_body = re.sub(r"<[^>]+>", " ", raw_html).strip()
                if plain_body:
                    parsed_sections.append((doc["title"], plain_body))

            # Filter to requested section if not 'all'
            if section.lower() != "all":
                target_sec = [
                    (h, b) for (h, b) in parsed_sections if section.lower() in h.lower()
                ]
                if not target_sec and parsed_sections:
                    target_sec = [parsed_sections[0]]
                section_tex = "\n\n".join(f"\\section{{{h}}}\n{b}" for h, b in target_sec)
                return {
                    "document_id": document_id,
                    "template": template,
                    "section": section,
                    "latex_source": section_tex,
                    "bibtex_source": "",
                    "validation": {
                        "valid": True,
                        "warnings": [],
                        "missing_references": [],
                        "missing_figures": [],
                    },
                }

            doc_class = {
                "article": "\\documentclass[11pt,a4paper]{article}",
                "ieee": "\\documentclass[conference]{IEEEtran}",
                "acm": "\\documentclass[sigconf]{acmart}",
                "custom": "\\documentclass[12pt]{article}",
            }[template]

            authors_tex = " \\and ".join(m["full_name"] for m in members) if members else "ResearchFlow Collaborative Team"
            keywords_list = json.loads(proj["keywords"]) if proj and proj["keywords"] else []

            body_tex_parts = []
            for h, b in parsed_sections:
                body_tex_parts.append(f"\\section{{{h}}}\n{b}")

            bib_entries = []
            cite_keys = []
            for r in refs:
                first_author = r["authors"].split(",")[0].strip().split()[0].lower()
                ck = f"{first_author}{r['year']}"
                cite_keys.append(ck)
                bib_entries.append(
                    f"@article{{{ck},\n  title = {{{r['title']}}},\n  author = {{{r['authors']}}},\n"
                    f"  year = {{{r['year']}}},\n  journal = {{{r['journal_or_conference']}}},\n  doi = {{{r['doi']}}}\n}}"
                )

            if cite_keys:
                body_tex_parts.append(f"\\nocite{{{', '.join(cite_keys)}}}")

            full_tex = (
                f"{doc_class}\n"
                "\\usepackage{amsmath,amssymb,graphicx,hyperref,booktabs}\n\n"
                f"\\title{{{doc['title']}}}\n"
                f"\\author{{{authors_tex}}}\n"
                f"\\date{{{utc_now_iso()[:10]}}}\n\n"
                "\\begin{document}\n"
                "\\maketitle\n\n"
                + (f"\\begin{{abstract}}\n{proj['description']}\n\\end{{abstract}}\n\n" if proj and proj["description"] else "")
                + (f"\\textbf{{Keywords:}} {', '.join(keywords_list)}\n\n" if keywords_list else "")
                + "\n\n".join(body_tex_parts)
                + "\n\n\\bibliographystyle{plain}\n\\bibliography{references}\n"
                "\\end{document}\n"
            )

            warnings: list[str] = []
            if not refs:
                warnings.append("No bibliography references linked in project Research Library.")

            return {
                "document_id": document_id,
                "template": template,
                "section": "all",
                "latex_source": full_tex,
                "bibtex_source": "\n\n".join(bib_entries),
                "validation": {
                    "valid": True,
                    "warnings": warnings,
                    "missing_references": [],
                    "missing_figures": [],
                },
            }

    # -------------------------------------------------------------------------
    # Unified Research Artifacts, Side-by-Side Code Diff & Result Comparison
    # -------------------------------------------------------------------------
    @router.get("/projects/{project_id}/artifacts")
    def list_research_artifacts(
        project_id: str,
        artifact_type: Optional[str] = Query(default=None),
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.PROJECT_VIEW)
            rows = conn.execute(
                "SELECT * FROM research_artifacts WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
            items = []
            for r in rows:
                d = dict(r)
                if artifact_type and d["artifact_type"] != artifact_type:
                    continue
                d["metrics"] = json.loads(d.pop("metrics_json"))
                d["parameters"] = json.loads(d.pop("parameters_json"))
                d["tags"] = json.loads(d.pop("tags_json"))
                items.append(d)
            return {"artifacts": items}

    @router.post("/projects/{project_id}/artifacts", status_code=201)
    def create_research_artifact(
        project_id: str,
        payload: ArtifactCreateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        art_id = f"art_{uuid.uuid4().hex[:14]}"
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.EXPERIMENT_WRITE)
            conn.execute(
                "INSERT INTO research_artifacts (id, project_id, name, artifact_type, language, content_text, "
                "metrics_json, parameters_json, unit_system, linked_experiment_id, linked_dataset_version, "
                "linked_code_version, linked_paper_section, version_number, tags_json, notes, creator_id, last_editor_name, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
                (
                    art_id,
                    project_id,
                    payload.name.strip(),
                    payload.artifact_type,
                    payload.language.strip(),
                    payload.content_text,
                    json.dumps(payload.metrics),
                    json.dumps(payload.parameters),
                    payload.unit_system.strip(),
                    payload.linked_experiment_id.strip(),
                    payload.linked_dataset_version.strip(),
                    payload.linked_code_version.strip(),
                    payload.linked_paper_section.strip(),
                    json.dumps(payload.tags),
                    payload.notes.strip(),
                    uid,
                    session["full_name"],
                    now,
                    now,
                ),
            )
            log_activity(conn, project_id, uid, "artifact.created", "artifact", art_id, f"Added {payload.artifact_type} '{payload.name.strip()}'")
            return {"id": art_id, "name": payload.name.strip(), "artifact_type": payload.artifact_type}

    @router.post("/projects/{project_id}/compare/code")
    def compare_code_versions(
        project_id: str,
        payload: CodeComparisonRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.PROJECT_VIEW)
            left_lines = payload.left_code.splitlines()
            right_lines = payload.right_code.splitlines()
            matcher = difflib.SequenceMatcher(None, left_lines, right_lines)
            diff_rows: list[Dict[str, Any]] = []
            added = 0
            removed = 0
            modified = 0

            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag == "equal":
                    for offset in range(i2 - i1):
                        diff_rows.append({
                            "type": "unchanged",
                            "left_line_no": i1 + offset + 1,
                            "right_line_no": j1 + offset + 1,
                            "left_text": left_lines[i1 + offset],
                            "right_text": right_lines[j1 + offset],
                        })
                elif tag == "replace":
                    max_len = max(i2 - i1, j2 - j1)
                    for offset in range(max_len):
                        l_idx = i1 + offset if offset < (i2 - i1) else None
                        r_idx = j1 + offset if offset < (j2 - j1) else None
                        modified += 1
                        diff_rows.append({
                            "type": "modified",
                            "left_line_no": (l_idx + 1) if l_idx is not None else None,
                            "right_line_no": (r_idx + 1) if r_idx is not None else None,
                            "left_text": left_lines[l_idx] if l_idx is not None else "",
                            "right_text": right_lines[r_idx] if r_idx is not None else "",
                        })
                elif tag == "delete":
                    for l_idx in range(i1, i2):
                        removed += 1
                        diff_rows.append({
                            "type": "removed",
                            "left_line_no": l_idx + 1,
                            "right_line_no": None,
                            "left_text": left_lines[l_idx],
                            "right_text": "",
                        })
                elif tag == "insert":
                    for r_idx in range(j1, j2):
                        added += 1
                        diff_rows.append({
                            "type": "added",
                            "left_line_no": None,
                            "right_line_no": r_idx + 1,
                            "left_text": "",
                            "right_text": right_lines[r_idx],
                        })

            unified = "\n".join(
                difflib.unified_diff(
                    left_lines,
                    right_lines,
                    fromfile=payload.left_title,
                    tofile=payload.right_title,
                    lineterm="",
                )
            )
            return {
                "left_title": payload.left_title,
                "right_title": payload.right_title,
                "stats": {"added": added, "removed": removed, "modified": modified},
                "rows": diff_rows,
                "unified_diff": unified,
            }

    # -------------------------------------------------------------------------
    # Unique Research Collaboration Signal ("Raise a Research Hand")
    # -------------------------------------------------------------------------
    @router.get("/projects/{project_id}/collaboration-signals")
    def list_collaboration_signals(
        project_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        with db.transaction() as conn:
            require_project_permission(conn, project_id, uid, Permission.PROJECT_VIEW)
            rows = conn.execute(
                "SELECT * FROM collaboration_signals WHERE project_id = ? AND status != 'Withdrawn' ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
            return {
                "count": len(rows),
                "signals": [dict(r) for r in rows],
            }

    @router.post("/projects/{project_id}/collaboration-signals", status_code=201)
    def raise_research_hand(
        project_id: str,
        payload: CollaborationSignalCreateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, Any]:
        uid = session["user_id"]
        now = utc_now_iso()
        with db.transaction() as conn:
            proj = conn.execute("SELECT id, title, owner_id FROM projects WHERE id = ?", (project_id,)).fetchone()
            if not proj:
                raise HTTPException(status_code=404, detail="Project not found.")
            existing = conn.execute(
                "SELECT id FROM collaboration_signals WHERE project_id = ? AND user_id = ? AND status IN ('Pending', 'Acknowledged')",
                (project_id, uid),
            ).fetchone()
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail="You already have an active collaboration signal for this project.",
                )
            sig_id = f"sig_{uuid.uuid4().hex[:14]}"
            conn.execute(
                "INSERT INTO collaboration_signals (id, project_id, user_id, username, full_name, message, proposed_contribution, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?)",
                (
                    sig_id,
                    project_id,
                    uid,
                    session["username"],
                    session["full_name"],
                    payload.message.strip(),
                    payload.proposed_contribution.strip(),
                    now,
                    now,
                ),
            )
            ctx.notify(conn, proj["owner_id"], project_id, "collaboration_signal", "Research Hand Raised",
                       f"{session['full_name']} (@{session['username']}) raised a research hand on '{proj['title']}'.")
            return {
                "id": sig_id,
                "project_id": project_id,
                "user_id": uid,
                "username": session["username"],
                "full_name": session["full_name"],
                "status": "Pending",
            }

    @router.delete("/projects/{project_id}/collaboration-signals/me")
    def withdraw_research_hand(
        project_id: str,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        uid = session["user_id"]
        now = utc_now_iso()
        with db.transaction() as conn:
            cur = conn.execute(
                "UPDATE collaboration_signals SET status = 'Withdrawn', updated_at = ? "
                "WHERE project_id = ? AND user_id = ? AND status IN ('Pending', 'Acknowledged')",
                (now, project_id, uid),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="No active collaboration signal found to withdraw.")
            return {"message": "Collaboration signal withdrawn."}

    @router.patch("/collaboration-signals/{signal_id}")
    def update_collaboration_signal_status(
        signal_id: str,
        payload: CollaborationSignalUpdateRequest,
        session: Dict[str, Any] = Depends(get_current_session_and_user),
    ) -> Dict[str, str]:
        uid = session["user_id"]
        now = utc_now_iso()
        with db.transaction() as conn:
            sig = conn.execute("SELECT * FROM collaboration_signals WHERE id = ?", (signal_id,)).fetchone()
            if not sig:
                raise HTTPException(status_code=404, detail="Collaboration signal not found.")
            require_project_permission(conn, sig["project_id"], uid, Permission.PROJECT_ADMIN)
            conn.execute(
                "UPDATE collaboration_signals SET status = ?, updated_at = ? WHERE id = ?",
                (payload.status, now, signal_id),
            )
            return {"message": f"Signal status updated to {payload.status}."}

    return router
