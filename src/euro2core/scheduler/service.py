"""In-process scheduler: runs source syncs on their cadence and resumes after downtime."""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from euro2core.config import Settings
from euro2core.domain.enums import SyncStatus
from euro2core.domain.models import JobConfig, SyncRun
from euro2core.platform.credentials import Credentials, credentials
from euro2core.scheduler import jobs

log = logging.getLogger(__name__)

STARTUP_DELAY = timedelta(seconds=30)
RETRY_DELAY = timedelta(hours=1)  # quota errors (429) usually clear within the hour
STAGGER = timedelta(seconds=45)  # gap between jobs that are all due at boot

JobFactory = Callable[[AsyncEngine, Settings], Awaitable[SyncRun]]


def _skipped(job: str, reason: str) -> SyncRun:
    log.info("%s skipped: %s", job, reason)
    return SyncRun(job=job, status=SyncStatus.SKIPPED, error=reason)


async def _creds(engine: AsyncEngine, settings: Settings) -> Credentials:
    async with async_sessionmaker(engine)() as session:
        return await credentials(session, settings)


async def _ecb(engine: AsyncEngine, settings: Settings) -> SyncRun:
    creds = await _creds(engine, settings)
    return await jobs.run_ecb_discover(
        engine, data_dir=settings.data_dir, user_agent=creds.user_agent
    )


async def _numista(engine: AsyncEngine, settings: Settings) -> SyncRun:
    creds = await _creds(engine, settings)
    if not creds.has_numista:
        return _skipped("numista_catalog", "no Numista API key (Ajustes → Administración)")
    return await jobs.run_numista_catalog(
        engine,
        data_dir=settings.data_dir,
        api_key=creds.numista_api_key,
        user_agent=creds.user_agent,
    )


async def _numista_prices(engine: AsyncEngine, settings: Settings) -> SyncRun:
    creds = await _creds(engine, settings)
    if not creds.has_numista:
        return _skipped("numista_prices", "no Numista API key (Ajustes → Administración)")
    return await jobs.run_numista_prices(
        engine,
        data_dir=settings.data_dir,
        api_key=creds.numista_api_key,
        user_agent=creds.user_agent,
    )


async def _prices(engine: AsyncEngine, settings: Settings) -> SyncRun:
    return await jobs.run_recompute_prices(engine)


async def _rarity(engine: AsyncEngine, settings: Settings) -> SyncRun:
    return await jobs.run_recompute_rarity(engine)


async def _embed(engine: AsyncEngine, settings: Settings) -> SyncRun:
    return await jobs.run_embed_images(engine)


async def _news(engine: AsyncEngine, settings: Settings) -> SyncRun:
    return await jobs.run_publish_news(engine)


async def _bulletin(engine: AsyncEngine, settings: Settings) -> SyncRun:
    return await jobs.run_market_bulletin(engine)


async def _web(engine: AsyncEngine, settings: Settings) -> SyncRun:
    creds = await _creds(engine, settings)
    return await jobs.run_web_listings(engine, user_agent=creds.user_agent)


async def _embed_types(engine: AsyncEngine, settings: Settings) -> SyncRun:
    return await jobs.run_embed_types(engine)


async def _ebay_credentials(engine: AsyncEngine, settings: Settings) -> dict[str, str] | None:
    creds = await _creds(engine, settings)
    if not creds.has_ebay:
        return None
    return {
        "client_id": creds.ebay_client_id,
        "client_secret": creds.ebay_client_secret,
        "user_agent": creds.user_agent,
    }


async def _ebay_market(engine: AsyncEngine, settings: Settings) -> SyncRun:
    creds = await _ebay_credentials(engine, settings)
    if creds is None:
        return _skipped("ebay_market", "no eBay keys (Ajustes → Administración)")
    return await jobs.run_ebay_market(engine, **creds)


async def _ebay_hot(engine: AsyncEngine, settings: Settings) -> SyncRun:
    creds = await _ebay_credentials(engine, settings)
    if creds is None:
        return _skipped("ebay_hot", "no eBay keys (Ajustes → Administración)")
    return await jobs.run_ebay_market(engine, hot_days=30, **creds)


async def _auctions(engine: AsyncEngine, settings: Settings) -> SyncRun:
    creds = await _ebay_credentials(engine, settings)
    if creds is None:
        return _skipped("auction_close_check", "no eBay keys (Ajustes → Administración)")
    return await jobs.run_auction_close_check(engine, **creds)


# (job id, interval, runner)
JOB_SPECS: tuple[tuple[str, timedelta, JobFactory], ...] = (
    ("ecb_discover", timedelta(hours=24), _ecb),
    ("numista_catalog", timedelta(days=7), _numista),
    ("numista_prices", timedelta(hours=24), _numista_prices),
    ("ebay_market", timedelta(hours=72), _ebay_market),
    ("ebay_hot", timedelta(hours=6), _ebay_hot),
    ("auction_close_check", timedelta(hours=1), _auctions),
    ("recompute_prices", timedelta(hours=24), _prices),
    ("recompute_rarity", timedelta(hours=24), _rarity),
    ("embed_images", timedelta(hours=24), _embed),
    ("publish_news", timedelta(hours=1), _news),
    ("embed_types", timedelta(hours=24), _embed_types),
    ("web_listings", timedelta(hours=24), _web),
    ("market_bulletin", timedelta(hours=24), _bulletin),
)


NUMISTA_JOBS = frozenset({"numista_catalog", "numista_prices"})
EBAY_JOBS = frozenset({"ebay_market", "ebay_hot", "auction_close_check"})
JOB_LABELS_ES = {
    "ecb_discover": "BCE: conmemorativas y caras nacionales",
    "numista_catalog": "Numista: variantes, tiradas, traducciones",
    "numista_prices": "Numista: valores de catálogo",
    "ebay_market": "eBay: anuncios y subastas (todo el catálogo)",
    "ebay_hot": "eBay: monedas con actividad reciente",
    "auction_close_check": "eBay: subastas cerradas → ventas reales",
    "recompute_prices": "Precios: estimaciones, modelo por tirada, alertas",
    "recompute_rarity": "Índice de rareza",
    "embed_images": "Índice de visión (fotos)",
    "publish_news": "Noticias",
    "embed_types": "Índice semántico (búsqueda por significado)",
    "web_listings": "Web abierta: tiendas y anuncios (sin clave)",
    "market_bulletin": "Boletín diario del mercado",
}
JOB_NEEDS = {job: "numista" for job in NUMISTA_JOBS} | {job: "ebay" for job in EBAY_JOBS}


async def job_configs(engine: AsyncEngine) -> dict[str, JobConfig]:
    async with async_sessionmaker(engine)() as session:
        return {c.job: c for c in (await session.scalars(select(JobConfig))).all()}


async def enabled_job_specs(
    engine: AsyncEngine, settings: Settings
) -> list[tuple[str, timedelta, JobFactory]]:
    """Every job is registered; the admin panel (job_config) switches them off or changes
    the cadence, and jobs whose source has no key skip themselves with one log line."""
    configs = await job_configs(engine)
    out = []
    for job_id, interval, runner in JOB_SPECS:
        cfg = configs.get(job_id)
        if cfg is not None and not cfg.enabled:
            log.info("job %s disabled in Ajustes → Administración", job_id)
            continue
        if cfg is not None:
            interval = timedelta(hours=cfg.interval_hours)
        out.append((job_id, interval, runner))
    return out


def plan_next_run(
    last_success: datetime | None,
    interval: timedelta,
    now: datetime,
    *,
    last_failure: datetime | None = None,
    slot: int = 0,
) -> datetime:
    """Keep the cadence across restarts. Anything due or never run starts shortly after boot,
    one job per `STAGGER` so the sources are not all hit at once; a failure more recent than
    the last success (a paused source, a quota) keeps its retry delay through the restart."""
    boot = now + STARTUP_DELAY + STAGGER * slot
    if last_failure is not None and (last_success is None or last_failure > last_success):
        return max(boot, last_failure + RETRY_DELAY)
    if last_success is None:
        return boot
    due = last_success + interval
    return due if due > boot else boot


def plan_after_result(status: SyncStatus, interval: timedelta, now: datetime) -> datetime:
    """A failed run resumes from its cursor soon; success and skips wait the full cadence."""
    return now + (RETRY_DELAY if status == SyncStatus.FAILED else interval)


async def last_success(engine: AsyncEngine, job: str) -> datetime | None:
    return await _last_finished(engine, job, SyncStatus.SUCCEEDED)


async def last_failure(engine: AsyncEngine, job: str) -> datetime | None:
    return await _last_finished(engine, job, SyncStatus.FAILED)


async def _last_finished(engine: AsyncEngine, job: str, status: SyncStatus) -> datetime | None:
    async with async_sessionmaker(engine)() as session:
        return await session.scalar(
            select(SyncRun.finished_at)
            .where(SyncRun.job == job, SyncRun.status == status)
            .order_by(SyncRun.finished_at.desc())
            .limit(1)
        )


async def build_scheduler(engine: AsyncEngine, settings: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=UTC)
    now = datetime.now(UTC)
    for slot, (job_id, interval, runner) in enumerate(await enabled_job_specs(engine, settings)):
        next_run = plan_next_run(
            await last_success(engine, job_id),
            interval,
            now,
            last_failure=await last_failure(engine, job_id),
            slot=slot,
        )

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
