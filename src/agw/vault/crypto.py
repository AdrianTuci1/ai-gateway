from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet

from agw.config import Settings


class SecretBox:
    """Symmetric envelope for upstream credentials stored in Postgres."""

    def __init__(self, settings: Settings) -> None:
        key = hashlib.sha256(settings.session_secret.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(key))

    def encrypt_json(self, value: dict[str, Any]) -> bytes:
        return self._fernet.encrypt(json.dumps(value).encode())

    def decrypt_json(self, value: bytes | None) -> dict[str, Any]:
        if not value:
            return {}
        return json.loads(self._fernet.decrypt(value))
