import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


async def test_connects_and_has_pgvector(engine):
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        version = (
            await conn.execute(text("select extversion from pg_extension where extname='vector'"))
        ).scalar()
    assert version is not None
