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
    # pgvector's SQLAlchemy VECTOR type serialises vectors itself; registering the asyncpg
    # codec as well would make the driver reject the already-serialised text.
    return create_async_engine(url or str(get_settings().database_url), pool_pre_ping=True)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_engine()
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine
