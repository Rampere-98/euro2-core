import logging
import traceback
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from euro2core.catalog.ingest_ecb import ingest_ecb_entries
from euro2core.catalog.seed import ensure_reference_data
from euro2core.domain.enums import SyncStatus
from euro2core.domain.models import SyncRun
from euro2core.images.fetcher import ImageFetcher
from euro2core.sources.ecb.source import ECB_SOURCE_CODE, EcbSource
from euro2core.sources.http_cache import HttpCache

log = logging.getLogger(__name__)


async def run_ecb_discover(
    engine: AsyncEngine,
    *,
    data_dir: Path,
    user_agent: str,
    years: Sequence[int] | None = None,
) -> SyncRun:
    source = EcbSource(cache=HttpCache(data_dir / "cache" / ECB_SOURCE_CODE), user_agent=user_agent)
    fetcher = ImageFetcher(root=data_dir / "images", user_agent=user_agent)
    years = list(years) if years is not None else list(EcbSource.years())
    stats = {
        "years": [],
        "years_missing": [],
        "types_created": 0,
        "types_seen": 0,
        "claims_added": 0,
        "images_stored": 0,
        "images_failed": 0,
    }
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    run = SyncRun(job="ecb_discover", status=SyncStatus.RUNNING)
    async with sessions() as session:
        session.add(run)
        await ensure_reference_data(session)
        await session.commit()
    try:
        for year in years:
            try:
                entries = await source.fetch_year(year)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    stats["years_missing"].append(year)
                    log.info("ECB page for %s not published yet", year)
                    continue
                raise
            async with sessions() as session:
                year_stats = await ingest_ecb_entries(session, entries, fetcher)
                await session.commit()
            stats["years"].append(year)
            for key in (
                "types_created",
                "types_seen",
                "claims_added",
                "images_stored",
                "images_failed",
            ):
                stats[key] += getattr(year_stats, key)
            log.info(
                "ECB %s: %s entries, %s new types", year, len(entries), year_stats.types_created
            )
        status, error = SyncStatus.SUCCEEDED, None
    except Exception as exc:  # the run record must always be closed
        status, error = SyncStatus.FAILED, f"{exc}\n{traceback.format_exc()}"
        log.exception("ecb_discover failed")
    async with sessions() as session:
        run = await session.merge(run)
        run.status = status
        run.error = error
        run.stats = stats
        run.finished_at = datetime.now(UTC)
        await session.commit()
    return run
