import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from euro2core.db import Base, create_engine
from euro2core.domain import models  # noqa: F401

# Integration tests TRUNCATE tables, so they must never point at the working catalog.
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://euro2:euro2@localhost:5432/euro2_test"
)

TABLES_IN_DELETE_ORDER = [
    "rating",
    "offer",
    "listing",
    "expert_vote",
    "expert_report",
    "news_item",
    "type_embedding",
    "notification",
    "price_alert",
    "user_achievement",
    "piece_event",
    "collection_item",
    "app_user",
    "image_embedding",
    "identification",
    "rarity_score",
    "price_estimate",
    "market_observation",
    "coin_image",
    "coin_issue",
    "coin_type",
    "text_translation",
    "fact_claim",
    "domain_event",
    "sync_run",
    "series",
    "source",
    "country",
]


def _db_reachable() -> bool:
    async def probe() -> bool:
        engine = create_engine(TEST_DB_URL)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("select 1"))
            return True
        except Exception:
            return False
        finally:
            await engine.dispose()

    return asyncio.run(probe())


def pytest_collection_modifyitems(config, items):
    if _db_reachable():
        return
    skip = pytest.mark.skip(reason="PostgreSQL not reachable; run `docker compose up -d`")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
async def engine():
    engine = create_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        missing = [t for t in Base.metadata.sorted_tables if not await _table_exists(conn, t.name)]
        if missing:
            pytest.skip(
                "test database not migrated: "
                f"DATABASE_URL={TEST_DB_URL} uv run alembic upgrade head"
            )
        await conn.execute(text("TRUNCATE " + ", ".join(TABLES_IN_DELETE_ORDER) + " CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine) -> AsyncSession:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s


async def _table_exists(conn, name: str) -> bool:
    return bool((await conn.execute(text("select to_regclass(:n)"), {"n": name})).scalar())
