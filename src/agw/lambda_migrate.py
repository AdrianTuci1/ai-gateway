from __future__ import annotations

import asyncio
from typing import Any

from agw.lambda_secrets import load_runtime_secrets

load_runtime_secrets()

from agw.cli import _run_migrations  # noqa: E402
from agw.config import Settings  # noqa: E402
from agw.store import build_store_provider  # noqa: E402


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    settings = Settings()
    if not settings.uses_dynamodb:
        _run_migrations(settings)

    async def _seed() -> None:
        provider = build_store_provider(settings)
        try:
            await provider.startup()
        finally:
            await provider.shutdown()

    asyncio.run(_seed())
    return {"ok": True, "storage": settings.db_backend, "ready": True}
