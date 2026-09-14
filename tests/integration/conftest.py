import asyncio
import os

import pytest
from sqlalchemy import text

from euro2core.db import create_engine

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://euro2:euro2@localhost:5432/euro2"
)


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
    yield engine
    await engine.dispose()
