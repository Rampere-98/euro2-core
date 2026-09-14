from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pgvector.asyncpg import register_vector
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from euro2core.config import get_settings


class Base(DeclarativeBase):
    pass


def create_engine(url: str | None = None) -> AsyncEngine:
    engine = create_async_engine(url or str(get_settings().database_url), pool_pre_ping=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _register_vector(dbapi_connection, _record) -> None:
        # asyncpg needs the vector codec on every new connection
        dbapi_connection.run_async(register_vector)

    return engine


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_engine()
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
