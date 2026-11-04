from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .time import utcnow

_hasher = PasswordHasher()
JWT_ALGORITHM = "HS256"


def hash_secret(secret: str) -> bytes:
    return _hasher.hash(secret).encode()


def verify_secret(secret_hash: bytes | None, secret: str) -> bool:
    if not secret_hash:
        return False
    try:
        return _hasher.verify(secret_hash.decode(), secret)
    except (VerifyMismatchError, VerificationError, InvalidHashError, UnicodeDecodeError):
        return False


def new_token(realm: str) -> tuple[str, str, str]:
    """Return (full token, prefix, secret) for an opaque bearer token."""
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    return f"agw_{realm}_{prefix}_{secret}", prefix, secret


def parse_token(token: str, realm: str) -> tuple[str, str] | None:
    parts = token.split("_", 3)
    if len(parts) != 4 or parts[0] != "agw" or parts[1] != realm:
        return None
    return parts[2], parts[3]


def new_opaque(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_opaque(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())


def create_session_token(
    user_id: Any,
    workspace_id: Any,
    secret: str,
    ttl_hours: int,
) -> str:
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "ws": str(workspace_id),
        "typ": "session",
        "iat": now,
        "exp": now + timedelta(hours=ttl_hours),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_session_token(token: str, secret: str) -> dict[str, Any]:
    return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
