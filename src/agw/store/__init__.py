from __future__ import annotations

from agw.config import Settings
from agw.store.base import Store, StoreProvider


def build_store_provider(settings: Settings) -> StoreProvider:
    if settings.uses_dynamodb:
        from agw.store.dynamo import DynamoStoreProvider

        return DynamoStoreProvider(settings)

    from agw.store.sql import SqlStoreProvider

    return SqlStoreProvider(settings)


__all__ = ["Store", "StoreProvider", "build_store_provider"]
