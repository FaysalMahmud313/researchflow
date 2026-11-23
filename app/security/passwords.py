import base64
import hashlib
import hmac
import re
import secrets

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    _ARGON2_HASHER = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)
except ImportError:  # pragma: no cover
    _ARGON2_HASHER = None  # type: ignore[assignment]
    VerifyMismatchError = Exception  # type: ignore[misc,assignment]


PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128
# (id, label shown to users, check, error message). Served by GET /auth/password-policy so
# the sign-up form shows exactly the rules enforced here.
PASSWORD_RULES: list[tuple[str, str, re.Pattern[str], str]] = [
    ("upper", "An uppercase letter", re.compile(r"[A-Z]"), "Password must contain at least one uppercase letter."),
    ("lower", "A lowercase letter", re.compile(r"[a-z]"), "Password must contain at least one lowercase letter."),
    ("digit", "A number", re.compile(r"[0-9]"), "Password must contain at least one number."),
]


def password_policy() -> dict[str, object]:
    return {
        "min_length": PASSWORD_MIN_LENGTH,
        "max_length": PASSWORD_MAX_LENGTH,
        "rules": [{"id": rid, "label": label} for rid, label, _, _ in PASSWORD_RULES],
    }


def validate_password_strength(password: str) -> tuple[bool, str]:
    """Enforce minimum password policy without arbitrary truncation."""
    if len(password) < PASSWORD_MIN_LENGTH:
        return False, f"Password must be at least {PASSWORD_MIN_LENGTH} characters long."
    if len(password) > PASSWORD_MAX_LENGTH:
        return False, f"Password must not exceed {PASSWORD_MAX_LENGTH} characters."
    for _, _, pattern, message in PASSWORD_RULES:
        if not pattern.search(password):
            return False, message
    return True, ""


def hash_password(password: str) -> str:
    """Hash a password using Argon2id when installed, or memory-hard scrypt (N=16384, r=8, p=1)."""
    if _ARGON2_HASHER is not None:
        return str(_ARGON2_HASHER.hash(password))
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=64,
    )
    salt_b64 = base64.b64encode(salt).decode("ascii")
    dk_b64 = base64.b64encode(derived).decode("ascii")
    return f"scrypt$16384$8$1${salt_b64}${dk_b64}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time password verification against Argon2id or scrypt hash."""
    if not stored_hash:
        return False
    if stored_hash.startswith("$argon2") and _ARGON2_HASHER is not None:
        try:
            return bool(_ARGON2_HASHER.verify(stored_hash, password))
        except Exception:
            return False
    if stored_hash.startswith("scrypt$"):
        try:
            _, n_s, r_s, p_s, salt_b64, dk_b64 = stored_hash.split("$")
            salt = base64.b64decode(salt_b64.encode("ascii"))
            expected = base64.b64decode(dk_b64.encode("ascii"))
            candidate = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt,
                n=int(n_s),
                r=int(r_s),
                p=int(p_s),
                dklen=len(expected),
            )
            return hmac.compare_digest(candidate, expected)
        except Exception:
            return False
    return False
