import hashlib
import hmac
import secrets


def generate_opaque_token(nbytes: int = 32) -> str:
    """Generate a cryptographically random URL-safe token."""
    return secrets.token_urlsafe(nbytes)


def hash_token(raw_token: str, pepper: str) -> str:
    """Compute HMAC-SHA256 digest of a token so plaintext tokens are never stored in DB."""
    return hmac.new(
        pepper.encode("utf-8"),
        raw_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def generate_csrf_token(session_id: str, csrf_secret: str) -> str:
    """Generate a double-submit / session-bound HMAC CSRF token."""
    nonce = secrets.token_hex(16)
    mac = hmac.new(
        csrf_secret.encode("utf-8"),
        f"{session_id}:{nonce}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{nonce}.{mac}"


def verify_csrf_token(csrf_token: str, session_id: str, csrf_secret: str) -> bool:
    """Verify that the CSRF token matches the active session ID."""
    if not csrf_token or "." not in csrf_token or not session_id:
        return False
    nonce, provided_mac = csrf_token.split(".", 1)
    expected_mac = hmac.new(
        csrf_secret.encode("utf-8"),
        f"{session_id}:{nonce}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(provided_mac, expected_mac)
