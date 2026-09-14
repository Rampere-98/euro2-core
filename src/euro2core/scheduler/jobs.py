import logging
import traceback
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from euro2core.catalog.ingest_ebay import ingest_listings
from euro2core.catalog.ingest_ecb import ingest_ecb_entries
from euro2core.catalog.ingest_numista import ingest_numista_type
from euro2core.catalog.seed import ensure_reference_data
from euro2core.domain.enums import ObservationKind, SyncStatus
from euro2core.domain.models import CoinIssue, CoinType, MarketObservation, SyncRun
from euro2core.images.fetcher import ImageFetcher
from euro2core.pricing.recompute import issues_with_observations, recompute_issue_prices, summarize
from euro2core.rarity.recompute import recompute_all_rarity
from euro2core.sources.ebay.client import EbayClient
from euro2core.sources.ebay.parser import (
    MARKETPLACES,
    closed_auction_from_item,
    listing_from_summary,
)
from euro2core.sources.ebay.queries import search_query
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


async def run_recompute_prices(engine: AsyncEngine) -> SyncRun:
    stats: dict[str, Any] = {"issues_with_observations": 0, "issues_estimated": 0, "by_basis": {}}

    async def body(sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any]) -> None:
        async with sessions() as session:
            issue_ids = await issues_with_observations(session)
        stats["issues_with_observations"] = len(issue_ids)
        for issue_id in issue_ids:
            async with sessions() as session:
                estimates = await recompute_issue_prices(session, issue_id)
                await session.commit()
            if estimates:
                stats["issues_estimated"] += 1
                for basis, n in summarize(estimates).items():
                    stats["by_basis"][basis] = stats["by_basis"].get(basis, 0) + n

    return await _run_job(engine, "recompute_prices", body, stats)


async def run_recompute_rarity(engine: AsyncEngine) -> SyncRun:
    stats: dict[str, Any] = {}

    async def body(sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any]) -> None:
        async with sessions() as session:
            stats.update(await recompute_all_rarity(session))
            await session.commit()

    return await _run_job(engine, "recompute_rarity", body, stats)


async def run_ebay_market(
    engine: AsyncEngine,
    *,
    client_id: str,
    client_secret: str,
    user_agent: str,
    marketplaces: Sequence[str] | None = None,
    daily_budget: int | None = None,
    hot_days: int | None = None,
) -> SyncRun:
    """Search every (country, year) on every marketplace and store matched listings.

    With hot_days set, only country/years that had an observation recently are refreshed.
    """
    client = EbayClient(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
        **({"daily_budget": daily_budget} if daily_budget is not None else {}),
    )
    markets = list(marketplaces) if marketplaces is not None else list(MARKETPLACES)
    stats: dict[str, Any] = {
        "queries": 0,
        "listings_seen": 0,
        "listings_stored": 0,
        "listings_updated": 0,
        "listings_discarded": 0,
    }

    async def body(sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any]) -> None:
        async with sessions() as session:
            targets = await _market_targets(session, hot_days)
        done = list(cursor.get("done", []))
        for country, year in targets:
            for marketplace in markets:
                key = f"{country}/{year}/{marketplace}"
                if key in done:
                    continue
                summaries = await client.search(
                    search_query(country, year, marketplace), marketplace=marketplace
                )
                stats["queries"] += 1
                listings = [
                    listing
                    for s in summaries
                    if (listing := listing_from_summary(s, marketplace)) is not None
                ]
                stats["listings_seen"] += len(summaries)
                async with sessions() as session:
                    result = await ingest_listings(session, listings)
                    await session.commit()
                stats["listings_stored"] += result.stored
                stats["listings_updated"] += result.updated
                stats["listings_discarded"] += result.discarded
                done.append(key)
                cursor["done"] = list(done)

    job = "ebay_hot" if hot_days else "ebay_market"
    return await _run_job(engine, job, body, stats)


async def _market_targets(session: AsyncSession, hot_days: int | None) -> list[tuple[str, int]]:
    """Distinct (country, year) pairs that have issues; hot mode keeps only recently active ones."""
    stmt = (
        select(CoinType.country_code, CoinIssue.year)
        .join(CoinIssue, CoinIssue.type_id == CoinType.id)
        .distinct()
        .order_by(CoinIssue.year.desc(), CoinType.country_code)
    )
    if hot_days:
        recent = (
            select(CoinIssue.type_id)
            .join(MarketObservation, MarketObservation.issue_id == CoinIssue.id)
            .where(MarketObservation.observed_at >= datetime.now(UTC) - timedelta(days=hot_days))
        )
        stmt = stmt.where(CoinType.id.in_(recent))
    return [(c, y) for c, y in (await session.execute(stmt)).all()]


async def run_auction_close_check(
    engine: AsyncEngine, *, client_id: str, client_secret: str, user_agent: str
) -> SyncRun:
    client = EbayClient(client_id=client_id, client_secret=client_secret, user_agent=user_agent)
    stats: dict[str, Any] = {"checked": 0, "sold": 0, "unsold": 0, "still_open": 0}

    async def body(sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any]) -> None:
        async with sessions() as session:
            ended = (
                await session.scalars(
                    select(MarketObservation).where(
                        MarketObservation.observation_kind == ObservationKind.AUCTION_OPEN,
                        MarketObservation.ends_at <= datetime.now(UTC),
                    )
                )
            ).all()
            ids = [(o.id, o.listing_id, o.marketplace) for o in ended]
        for obs_id, listing_id, marketplace in ids:
            item = await client.get_item(listing_id, marketplace=marketplace)
            stats["checked"] += 1
            sale = closed_auction_from_item(item, marketplace)
            async with sessions() as session:
                if sale is not None:
                    await ingest_listings(session, [sale])
                    stats["sold"] += 1
                else:
                    stats["unsold"] += 1
                open_row = await session.get(MarketObservation, obs_id)
                if open_row is not None:
                    await session.delete(open_row)  # a bid on a live auction is not a price signal
                await session.commit()

    return await _run_job(engine, "auction_close_check", body, stats)


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
