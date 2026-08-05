"""Password hashing and JSON Web Token issuing/verification.

Deliberately small: two password functions and two token functions, with no
framework types leaking in, so the module is trivial to unit-test in isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.config import settings

# bcrypt hashes at most the first 72 *bytes* of input and (depending on the
# version) either truncates silently or raises. We reject longer passwords at
# the schema layer and assert it here so the two can never drift apart.
BCRYPT_MAX_PASSWORD_BYTES = 72

TOKEN_TYPE = "bearer"


class TokenError(Exception):
    """Raised when a token is malformed, expired or signed with a wrong key."""


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt (per-password random salt)."""
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError("Password exceeds the 72-byte bcrypt limit")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time check of a plaintext password against a stored hash."""
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, hashed.encode("utf-8"))
    except ValueError:
        # Stored value is not a valid bcrypt hash (corrupt row, legacy format).
        return False


def create_access_token(
    subject: str | int,
    expires_delta: timedelta | None = None,
) -> tuple[str, int]:
    """Return ``(encoded_jwt, expires_in_seconds)`` for the given subject.

    The subject is the user id. Nothing else is embedded: putting the email or
    role in the token would let stale data outlive a profile change.
    """
    lifetime = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str) -> int:
    """Validate a token and return the user id it refers to.

    Raises ``TokenError`` for anything that is not a currently-valid token
    signed by this service.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:  # expired, bad signature, malformed, ...
        raise TokenError(str(exc)) from exc

    subject = payload.get("sub")
    if subject is None:
        raise TokenError("Token is missing the 'sub' claim")
    try:
        return int(subject)
    except (TypeError, ValueError) as exc:
        raise TokenError("Token subject is not a user id") from exc
