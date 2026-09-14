import logging
import traceback
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from euro2core.catalog.ingest_ecb import ingest_ecb_entries
from euro2core.catalog.ingest_numista import ingest_numista_type
from euro2core.catalog.seed import ensure_reference_data
from euro2core.domain.enums import SyncStatus
from euro2core.domain.models import SyncRun
from euro2core.images.fetcher import ImageFetcher
from euro2core.sources.ecb.source import ECB_SOURCE_CODE, EcbSource
from euro2core.sources.http_cache import HttpCache
from euro2core.sources.numista.client import NumistaClient
from euro2core.sources.numista.parser import SEARCH_ISSUERS, parse_issue, parse_type

log = logging.getLogger(__name__)

Sessions = async_sessionmaker[AsyncSession]
JobBody = Callable[[Sessions, dict[str, Any], dict[str, Any]], Awaitable[None]]


async def _run_job(engine: AsyncEngine, job: str, body: JobBody, stats: dict[str, Any]) -> SyncRun:
    """Wrap a job in a sync_run row: seeds reference data, resumes cursor, always closes the run."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    run = SyncRun(job=job, status=SyncStatus.RUNNING)
    async with sessions() as session:
        await ensure_reference_data(session)
        cursor = await _last_cursor(session, job)
        run.cursor = cursor
        session.add(run)
        await session.commit()
    try:
        await body(sessions, stats, cursor)
        status, error = SyncStatus.SUCCEEDED, None
    except Exception as exc:  # the run record must always be closed
        status, error = SyncStatus.FAILED, f"{exc}\n{traceback.format_exc()}"
        log.exception("%s failed", job)
    async with sessions() as session:
        run = await session.merge(run)
        run.status = status
        run.error = error
        run.stats = stats
        # a finished run needs no cursor; a failed one keeps it so the next run resumes
        run.cursor = cursor if status == SyncStatus.FAILED else None
        run.finished_at = datetime.now(UTC)
        await session.commit()
    return run


async def _last_cursor(session: AsyncSession, job: str) -> dict[str, Any]:
    last = (
        await session.scalars(
            select(SyncRun)
            .where(SyncRun.job == job, SyncRun.finished_at.is_not(None))
            .order_by(SyncRun.finished_at.desc())
            .limit(1)
        )
    ).first()
    if last is not None and last.status == SyncStatus.FAILED and last.cursor:
        return dict(last.cursor)
    return {}


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
    stats: dict[str, Any] = {
        "years": [],
        "years_missing": [],
        "types_created": 0,
        "types_seen": 0,
        "claims_added": 0,
        "images_stored": 0,
        "images_failed": 0,
    }

    async def body(sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any]) -> None:
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

    return await _run_job(engine, "ecb_discover", body, stats)


async def run_numista_catalog(
    engine: AsyncEngine,
    *,
    data_dir: Path,
    api_key: str,
    user_agent: str,
    issuers: Sequence[str] | None = None,
    langs: Sequence[str] = ("en", "es"),
) -> SyncRun:
    client = NumistaClient(
        api_key=api_key, user_agent=user_agent, cache_dir=data_dir / "cache" / "numista"
    )
    fetcher = ImageFetcher(root=data_dir / "images", user_agent=user_agent)
    issuers = list(issuers) if issuers is not None else list(SEARCH_ISSUERS)
    primary, extra_langs = langs[0], list(langs[1:])
    stats: dict[str, Any] = {
        "issuers_done": [],
        "issuers_skipped": [],
        "types_seen": 0,
        "types_created": 0,
        "types_linked": 0,
        "types_skipped": 0,
        "issues_created": 0,
        "issues_skipped": 0,
    }

    async def body(sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any]) -> None:
        done = list(cursor.get("issuers_done", []))
        for issuer in issuers:
            if issuer in done:
                stats["issuers_skipped"].append(issuer)
                continue
            hits = await client.search_two_euro_types(issuer, lang=primary)
            log.info("Numista %s: %s two-euro types", issuer, len(hits))
            for hit in hits:
                ntype = parse_type(await client.get_type(hit["id"], lang=primary), lang=primary)
                translations = [
                    parse_type(await client.get_type(hit["id"], lang=lang), lang=lang)
                    for lang in extra_langs
                ]
                issues = [parse_issue(i) for i in await client.get_issues(hit["id"], lang=primary)]
                async with sessions() as session:
                    result = await ingest_numista_type(
                        session, ntype, issues, translations=translations, fetcher=fetcher
                    )
                    await session.commit()
                stats["types_seen"] += 1
                stats["types_created"] += int(result.created)
                stats["types_linked"] += int(result.linked_to_ecb)
                stats["types_skipped"] += int(result.skipped_reason is not None)
                stats["issues_created"] += result.issues_created
                stats["issues_skipped"] += result.issues_skipped
            done.append(issuer)
            cursor["issuers_done"] = list(done)
            stats["issuers_done"].append(issuer)

    return await _run_job(engine, "numista_catalog", body, stats)
