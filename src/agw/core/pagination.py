from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from agw.core.errors import ApiError


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def query_fingerprint(query: str | None, filters: dict[str, Any] | None = None) -> str:
    payload = json.dumps(
        {"q": query or "", "f": filters or {}}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def encode_cursor(payload: dict[str, Any], secret: str) -> str:
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{signature}"


def decode_cursor(cursor: str, secret: str) -> dict[str, Any]:
    try:
        body, signature = cursor.rsplit(".", 1)
    except ValueError as exc:
        raise ApiError(400, "invalid_cursor", "cursor is malformed") from exc
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(signature, expected):
        raise ApiError(400, "invalid_cursor", "cursor signature is invalid")
    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ApiError(400, "invalid_cursor", "cursor payload is invalid") from exc
    if payload.get("v") != 1:
        raise ApiError(400, "invalid_cursor", "unsupported cursor version")
    return payload
