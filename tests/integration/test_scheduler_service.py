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

    # a key is required for the Numista jobs to be scheduled; nothing here calls the API
    scheduler = await build_scheduler(engine, Settings(_env_file=None, numista_api_key="test"))
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert set(jobs) >= {"ecb_discover", "numista_catalog"}

    ecb_next = jobs["ecb_discover"].next_run_time
    assert abs((ecb_next - (recent + timedelta(hours=24))).total_seconds()) < 60

    # a failed last run does not count as success: retry soon after boot
    numista_next = jobs["numista_catalog"].next_run_time
    assert numista_next <= datetime.now(UTC) + STARTUP_DELAY + timedelta(seconds=5)


async def test_job_config_switches_jobs_off_and_changes_cadence(engine):
    from datetime import timedelta

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from euro2core.domain.models import JobConfig
    from euro2core.scheduler.service import enabled_job_specs

    async with async_sessionmaker(engine)() as session:
        session.add(JobConfig(job="ebay_hot", enabled=False, interval_hours=6))
        session.add(JobConfig(job="publish_news", enabled=True, interval_hours=0.5))
        await session.commit()
    specs = {
        job: interval
        for job, interval, _ in await enabled_job_specs(engine, Settings(_env_file=None))
    }
    assert "ebay_hot" not in specs
    assert specs["publish_news"] == timedelta(minutes=30)
    assert "numista_catalog" in specs  # registered even without a key: it skips itself


async def test_jobs_without_credentials_skip_without_a_sync_run(engine):
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from euro2core.domain.enums import SyncStatus
    from euro2core.domain.models import SyncRun
    from euro2core.scheduler.service import _ebay_hot, _numista

    settings = Settings(
        _env_file=None, numista_api_key="", ebay_client_id="", ebay_client_secret=""
    )
    assert (await _numista(engine, settings)).status == SyncStatus.SKIPPED
    assert (await _ebay_hot(engine, settings)).status == SyncStatus.SKIPPED
    async with async_sessionmaker(engine)() as session:
        assert await session.scalar(select(func.count()).select_from(SyncRun)) == 0
