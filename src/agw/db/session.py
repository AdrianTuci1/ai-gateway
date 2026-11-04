from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from agw.config import Settings
from agw.db.base import Base
from agw.db.models import *  # noqa: F401,F403  (register mappings)
from agw.core.roles import seed_builtin_roles


def _sqlite_engine(settings: Settings):
    kwargs: dict = {"connect_args": {"check_same_thread": False, "timeout": 30}}
    if ":memory:" in settings.database_url:
        kwargs["poolclass"] = StaticPool
    elif settings.db_pool_mode == "null":
        kwargs["poolclass"] = NullPool
    engine = create_async_engine(settings.database_url, **kwargs)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _record) -> None:
        # WAL lets readers run alongside a writer, so a long request does not
        # block tracing or another page load.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()

    return engine


def build_engine(settings: Settings):
    if settings.is_sqlite:
        return _sqlite_engine(settings)
    if settings.db_pool_mode == "null":
        return create_async_engine(settings.database_url, poolclass=NullPool)
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=0,
        pool_pre_ping=True,
    )


def build_sessionmaker(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine, *, seed: bool = True) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    if seed:
        from agw.store.sql import SqlStore

        async with build_sessionmaker(engine)() as session:
            await seed_builtin_roles(SqlStore(session))
