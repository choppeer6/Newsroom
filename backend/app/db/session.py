from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import Base
from app.models import ExecutionEventRecord, TaskRecord  # noqa: F401

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(
    database_url: str, *, echo: bool = False
) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()

    _engine = create_async_engine(database_url, echo=echo, pool_pre_ping=True)
    async with _engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_factory


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("database is not initialized")
    return _session_factory


async def dispose_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
