"""In-process scheduler: runs source syncs on their cadence and resumes after downtime."""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from euro2core.config import Settings
from euro2core.domain.enums import SyncStatus
from euro2core.domain.models import SyncRun
from euro2core.scheduler import jobs

log = logging.getLogger(__name__)

STARTUP_DELAY = timedelta(seconds=30)
RETRY_DELAY = timedelta(hours=1)  # quota errors (429) usually clear within the hour

JobFactory = Callable[[AsyncEngine, Settings], Awaitable[SyncRun]]


async def _ecb(engine: AsyncEngine, settings: Settings) -> SyncRun:
    return await jobs.run_ecb_discover(
        engine, data_dir=settings.data_dir, user_agent=settings.user_agent
    )


async def _numista(engine: AsyncEngine, settings: Settings) -> SyncRun:
    if not settings.numista_api_key:
        log.warning("numista_catalog skipped: NUMISTA_API_KEY not set")
        return SyncRun(job="numista_catalog", status=SyncStatus.FAILED, error="no api key")
    return await jobs.run_numista_catalog(
        engine,
        data_dir=settings.data_dir,
        api_key=settings.numista_api_key,
        user_agent=settings.user_agent,
    )


async def _prices(engine: AsyncEngine, settings: Settings) -> SyncRun:
    return await jobs.run_recompute_prices(engine)


async def _rarity(engine: AsyncEngine, settings: Settings) -> SyncRun:
    return await jobs.run_recompute_rarity(engine)


async def _embed(engine: AsyncEngine, settings: Settings) -> SyncRun:
    return await jobs.run_embed_images(engine)


async def _news(engine: AsyncEngine, settings: Settings) -> SyncRun:
    return await jobs.run_publish_news(engine)


async def _embed_types(engine: AsyncEngine, settings: Settings) -> SyncRun:
    return await jobs.run_embed_types(engine)


def _ebay_credentials(settings: Settings, job: str) -> dict[str, str] | None:
    if not settings.ebay_client_id or not settings.ebay_client_secret:
        log.warning("%s skipped: EBAY_CLIENT_ID/EBAY_CLIENT_SECRET not set", job)
        return None
    return {
        "client_id": settings.ebay_client_id,
        "client_secret": settings.ebay_client_secret,
        "user_agent": settings.user_agent,
    }


async def _ebay_market(engine: AsyncEngine, settings: Settings) -> SyncRun:
    creds = _ebay_credentials(settings, "ebay_market")
    if creds is None:
        return SyncRun(job="ebay_market", status=SyncStatus.FAILED, error="no ebay keys")
    return await jobs.run_ebay_market(engine, **creds)


async def _ebay_hot(engine: AsyncEngine, settings: Settings) -> SyncRun:
    creds = _ebay_credentials(settings, "ebay_hot")
    if creds is None:
        return SyncRun(job="ebay_hot", status=SyncStatus.FAILED, error="no ebay keys")
    return await jobs.run_ebay_market(engine, hot_days=30, **creds)


async def _auctions(engine: AsyncEngine, settings: Settings) -> SyncRun:
    creds = _ebay_credentials(settings, "auction_close_check")
    if creds is None:
        return SyncRun(job="auction_close_check", status=SyncStatus.FAILED, error="no ebay keys")
    return await jobs.run_auction_close_check(engine, **creds)


# (job id, interval, runner)
JOB_SPECS: tuple[tuple[str, timedelta, JobFactory], ...] = (
    ("ecb_discover", timedelta(hours=24), _ecb),
    ("numista_catalog", timedelta(days=7), _numista),
    ("ebay_market", timedelta(hours=72), _ebay_market),
    ("ebay_hot", timedelta(hours=6), _ebay_hot),
    ("auction_close_check", timedelta(hours=1), _auctions),
    ("recompute_prices", timedelta(hours=24), _prices),
    ("recompute_rarity", timedelta(hours=24), _rarity),
    ("embed_images", timedelta(hours=24), _embed),
    ("publish_news", timedelta(hours=1), _news),
    ("embed_types", timedelta(hours=24), _embed_types),
)


def plan_next_run(last_success: datetime | None, interval: timedelta, now: datetime) -> datetime:
    """Keep the cadence across restarts; anything due or never run starts shortly after boot."""
    if last_success is None:
        return now + STARTUP_DELAY
    due = last_success + interval
    return due if due > now + STARTUP_DELAY else now + STARTUP_DELAY


def plan_after_result(status: SyncStatus, interval: timedelta, now: datetime) -> datetime:
    """A failed run resumes from its cursor soon; a successful one waits its full cadence."""
    return now + (RETRY_DELAY if status != SyncStatus.SUCCEEDED else interval)


async def last_success(engine: AsyncEngine, job: str) -> datetime | None:
    async with async_sessionmaker(engine)() as session:
        return await session.scalar(
            select(SyncRun.finished_at)
            .where(SyncRun.job == job, SyncRun.status == SyncStatus.SUCCEEDED)
            .order_by(SyncRun.finished_at.desc())
            .limit(1)
        )


async def build_scheduler(engine: AsyncEngine, settings: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=UTC)
    now = datetime.now(UTC)
    for job_id, interval, runner in JOB_SPECS:
        next_run = plan_next_run(await last_success(engine, job_id), interval, now)

        async def run(runner=runner, job_id=job_id, interval=interval) -> None:
            log.info("scheduled job %s starting", job_id)
            result = await runner(engine, settings)
            log.info("scheduled job %s finished: %s", job_id, result.status)
            next_run = plan_after_result(result.status, interval, datetime.now(UTC))
            scheduler.modify_job(job_id, next_run_time=next_run)

        scheduler.add_job(
            run,
            "interval",
            seconds=int(interval.total_seconds()),
            id=job_id,
            next_run_time=next_run,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=int(timedelta(hours=6).total_seconds()),
        )
        log.info("job %s scheduled every %s, next run %s", job_id, interval, next_run.isoformat())
    return scheduler
