"""
backend/app/core/security.py
----------------------------
Cryptographic security utilities for SeatLock.

Responsibilities:
  1. Password hashing & verification using bcrypt.
     - Never stores plain-text passwords.
     - Automatically generates unique salts per hash.
  2. JSON Web Token (JWT) creation & decoding using PyJWT.
     - Signs tokens with HMAC-SHA256 (HS256) and a secret key.
     - Enforces expiration time (exp) and issued-at time (iat).
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings


# ---------------------------------------------------------------------------
# 1. Password Hashing & Verification
# ---------------------------------------------------------------------------

def hash_password(plain_password: str) -> str:
    """
    Hash a plain-text password using bcrypt with a freshly generated salt.

    Returns the hashed password as a UTF-8 string ready for database storage.
    Plaintext passwords are never returned or logged.
    """
    password_bytes = plain_password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a candidate plain-text password against a stored bcrypt hash.

    Returns True if the password matches, False otherwise.
    Never raises an unhandled exception on malformed hashes — returns False safely.
    """
    try:
        password_bytes = plain_password.encode("utf-8")
        hashed_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# 2. JWT Generation & Verification
# ---------------------------------------------------------------------------

def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a signed JWT access token.

    Parameters:
      data: Claims dictionary (e.g. sub=user_id, role=user_role, username=user_name).
      expires_delta: Optional custom duration. Defaults to settings.ACCESS_TOKEN_EXPIRE_MINUTES.

    Returns:
      A signed JWT string.
    """
    to_encode = data.copy()

    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({
        "exp": expire,
        "iat": now,
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a signed JWT access token.

    Validates:
      - HMAC signature against settings.JWT_SECRET_KEY.
      - Token expiration time (exp).

    Raises:
      jwt.ExpiredSignatureError: If the token has expired.
      jwt.InvalidTokenError: If the signature or structure is invalid.
    """
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
