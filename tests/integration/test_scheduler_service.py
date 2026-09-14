from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from euro2core.config import Settings
from euro2core.domain.enums import SyncStatus
from euro2core.domain.models import SyncRun
from euro2core.scheduler.service import STARTUP_DELAY, build_scheduler

pytestmark = pytest.mark.integration


async def test_scheduler_registers_jobs_and_resumes_from_last_success(engine):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    recent = datetime.now(UTC) - timedelta(hours=2)
    async with sessions() as session:
        session.add(
            SyncRun(job="ecb_discover", status=SyncStatus.SUCCEEDED, finished_at=recent, stats={})
        )
        session.add(
            SyncRun(
                job="numista_catalog",
                status=SyncStatus.FAILED,
                finished_at=recent,
                stats={},
                error="x",
            )
        )
        await session.commit()

    scheduler = await build_scheduler(engine, Settings(_env_file=None))
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert set(jobs) >= {"ecb_discover", "numista_catalog"}

    ecb_next = jobs["ecb_discover"].next_run_time
    assert abs((ecb_next - (recent + timedelta(hours=24))).total_seconds()) < 60

    # a failed last run does not count as success: retry soon after boot
    numista_next = jobs["numista_catalog"].next_run_time
    assert numista_next <= datetime.now(UTC) + STARTUP_DELAY + timedelta(seconds=5)
