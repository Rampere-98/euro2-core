import asyncio
import logging
import traceback
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from euro2core.catalog.editions import link_editions_to_base
from euro2core.catalog.ingest_ebay import close_auction, ingest_listings
from euro2core.catalog.ingest_ecb import ingest_ecb_entries
from euro2core.catalog.ingest_national import ingest_national_sides
from euro2core.catalog.ingest_numista import ingest_numista_type
from euro2core.catalog.reconcile import link_by_elimination
from euro2core.catalog.seed import ensure_reference_data
from euro2core.domain.enums import ObservationKind, SyncStatus
from euro2core.domain.eurozone import EURO_COUNTRIES
from euro2core.domain.models import (
    CoinIssue,
    CoinType,
    MarketObservation,
    PriceEstimate,
    SyncRun,
    WatchItem,
)
from euro2core.images.fetcher import ImageFetcher
from euro2core.platform.alerts import check_alerts
from euro2core.platform.market_assistant import notify_watchers
from euro2core.platform.news import publish_pending
from euro2core.platform.semantic import embed_types, get_text_embedder
from euro2core.pricing.recompute import (
    issues_with_observations,
    recompute_issue_prices,
    recompute_model_estimates,
    summarize,
)
from euro2core.rarity.recompute import recompute_all_rarity
from euro2core.sources.ebay.client import EbayClient
from euro2core.sources.ebay.parser import (
    MARKETPLACES,
    closed_auction_from_item,
    listing_from_summary,
)
from euro2core.sources.ebay.queries import search_query
from euro2core.sources.ecb.source import ECB_SOURCE_CODE, EcbSource
from euro2core.sources.errors import SourcePaused
from euro2core.sources.http_cache import HttpCache
from euro2core.sources.numista.client import NumistaClient
from euro2core.sources.numista.parser import SEARCH_ISSUERS, parse_issue, parse_type
from euro2core.sources.numista.prices import parse_prices
from euro2core.vision.embedder import get_embedder
from euro2core.vision.index import embed_missing_images

log = logging.getLogger(__name__)

Sessions = async_sessionmaker[AsyncSession]
Checkpoint = Callable[[], Awaitable[None]]
JobBody = Callable[[Sessions, dict[str, Any], dict[str, Any], Checkpoint], Awaitable[None]]

# One lock per job name: the scheduler and POST /sync/{job} live in the same process, and two
# copies of the same job would race on unique keys and duplicate claims and events.
_locks: dict[str, asyncio.Lock] = {}


class JobAlreadyRunning(RuntimeError):
    pass


def is_running(job: str) -> bool:
    lock = _locks.get(job)
    return lock is not None and lock.locked()


def _lock_for(job: str) -> asyncio.Lock:
    return _locks.setdefault(job, asyncio.Lock())


async def _run_job(engine: AsyncEngine, job: str, body: JobBody, stats: dict[str, Any]) -> SyncRun:
    """Wrap a job in a sync_run row: serialises same-name jobs, seeds reference data, resumes the
    cursor of a failed or orphaned run, checkpoints it as the job advances, always closes the run.
    """
    async with _lock_for(job):
        return await _run_job_locked(engine, job, body, stats)


async def _run_job_locked(
    engine: AsyncEngine, job: str, body: JobBody, stats: dict[str, Any]
) -> SyncRun:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    run = SyncRun(job=job, status=SyncStatus.RUNNING)
    async with sessions() as session:
        await ensure_reference_data(session)
        cursor = await _last_cursor(session, job)
        run.cursor = dict(cursor)
        session.add(run)
        await session.commit()
        run_id = run.id

    async def checkpoint() -> None:
        async with sessions() as session:
            row = await session.get(SyncRun, run_id)
            if row is not None:
                row.cursor = dict(cursor)
                await session.commit()

    try:
        await body(sessions, stats, cursor, checkpoint)
        status, error = SyncStatus.SUCCEEDED, None
    except SourcePaused as exc:  # expected: keep the cursor, retry later, no traceback
        status, error = SyncStatus.FAILED, str(exc)
        log.warning("%s paused: %s", job, exc)
    except Exception as exc:  # the run record must always be closed
        status, error = SyncStatus.FAILED, f"{exc}\n{traceback.format_exc()}"
        log.exception("%s failed", job)
    async with sessions() as session:
        run = await session.merge(run)
        run.status = status
        run.error = error
        run.stats = stats
        # a finished run needs no cursor; a failed one keeps it so the next run resumes
        run.cursor = dict(cursor) if status == SyncStatus.FAILED else None
        run.finished_at = datetime.now(UTC)
        await session.commit()
    return run


async def _last_cursor(session: AsyncSession, job: str) -> dict[str, Any]:
    """Cursor to resume from. A run still marked RUNNING cannot be alive (we hold the job lock):
    the process died mid-job, so it is closed as failed and its checkpointed cursor reused."""
    last = (
        await session.scalars(
            select(SyncRun).where(SyncRun.job == job).order_by(SyncRun.started_at.desc()).limit(1)
        )
    ).first()
    if last is None:
        return {}
    if last.status == SyncStatus.RUNNING:
        last.status = SyncStatus.FAILED
        last.error = "process ended before the run finished"
        last.finished_at = datetime.now(UTC)
        await session.flush()
        return dict(last.cursor or {})
    if last.status == SyncStatus.FAILED and last.cursor:
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
        "years_empty": [],
        "types_created": 0,
        "types_seen": 0,
        "claims_added": 0,
        "images_stored": 0,
        "images_failed": 0,
        "national_images_stored": 0,
    }

    async def body(
        sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any], checkpoint: Checkpoint
    ) -> None:
        for year in years:
            try:
                entries = await source.fetch_year(year)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    stats["years_missing"].append(year)
                    log.info("ECB page for %s not published yet", year)
                    continue
                raise
            if not entries:
                # a published year with zero coins means the page layout changed, not the catalog
                stats["years_empty"].append(year)
                log.warning("ECB %s parsed to zero entries; parser may need updating", year)
                continue
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
        # circulation designs live on the per-country pages, not on the yearly ones
        for country in EURO_COUNTRIES:
            try:
                images = await source.fetch_national_sides(country.code)
            except httpx.HTTPError as exc:
                log.warning("ECB national page for %s unavailable: %s", country.code, exc)
                continue
            async with sessions() as session:
                stats["national_images_stored"] += await ingest_national_sides(
                    session, country.code, images, fetcher
                )
                await session.commit()

    return await _run_job(engine, "ecb_discover", body, stats)


async def run_recompute_prices(engine: AsyncEngine) -> SyncRun:
    stats: dict[str, Any] = {"issues_with_observations": 0, "issues_estimated": 0, "by_basis": {}}

    async def body(
        sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any], checkpoint: Checkpoint
    ) -> None:
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
        async with sessions() as session:
            stats.update(await recompute_model_estimates(session))  # key-free fallback
            stats.update(await check_alerts(session))
            stats["watch_notifications"] = await notify_watchers(session)
            await session.commit()

    return await _run_job(engine, "recompute_prices", body, stats)


async def run_publish_news(engine: AsyncEngine) -> SyncRun:
    stats: dict[str, Any] = {}

    async def body(
        sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any], checkpoint: Checkpoint
    ) -> None:
        async with sessions() as session:
            stats.update(await publish_pending(session))
            await session.commit()

    return await _run_job(engine, "publish_news", body, stats)


async def run_embed_types(engine: AsyncEngine) -> SyncRun:
    stats: dict[str, Any] = {}

    async def body(
        sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any], checkpoint: Checkpoint
    ) -> None:
        async with sessions() as session:
            stats.update(await embed_types(session, get_text_embedder()))
            await session.commit()

    return await _run_job(engine, "embed_types", body, stats)


async def run_recompute_rarity(engine: AsyncEngine) -> SyncRun:
    stats: dict[str, Any] = {}

    async def body(
        sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any], checkpoint: Checkpoint
    ) -> None:
        async with sessions() as session:
            stats.update(await recompute_all_rarity(session))
            await session.commit()

    return await _run_job(engine, "recompute_rarity", body, stats)


async def run_embed_images(engine: AsyncEngine) -> SyncRun:
    stats: dict[str, Any] = {}

    async def body(
        sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any], checkpoint: Checkpoint
    ) -> None:
        async with sessions() as session:
            stats.update(await embed_missing_images(session, get_embedder()))
            await session.commit()

    return await _run_job(engine, "embed_images", body, stats)


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

    async def body(
        sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any], checkpoint: Checkpoint
    ) -> None:
        async with sessions() as session:
            targets = await _market_targets(session, hot_days)
            client.charge(await _ebay_calls_today(session))
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
                await checkpoint()

    job = "ebay_hot" if hot_days else "ebay_market"
    return await _run_job(engine, job, body, stats)


EBAY_JOBS = ("ebay_market", "ebay_hot", "auction_close_check")


async def _ebay_calls_today(session: AsyncSession) -> int:
    """Calls already spent today by earlier runs (each run builds a fresh client)."""
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    runs = (
        await session.scalars(
            select(SyncRun).where(SyncRun.job.in_(EBAY_JOBS), SyncRun.started_at >= midnight)
        )
    ).all()
    return sum(
        int((r.stats or {}).get("queries", 0)) + int((r.stats or {}).get("checked", 0))
        for r in runs
    )


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
    stats: dict[str, Any] = {"checked": 0, "sold": 0, "unsold": 0, "gone": 0, "still_open": 0}

    async def body(
        sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any], checkpoint: Checkpoint
    ) -> None:
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
            stats["checked"] += 1
            try:
                item = await client.get_item(listing_id, marketplace=marketplace)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in (404, 410):
                    raise
                item = None  # eBay no longer serves ended items after a while
            sale = closed_auction_from_item(item, marketplace) if item else None
            async with sessions() as session:
                open_row = await session.get(MarketObservation, obs_id)
                if open_row is None:
                    continue
                if item is None:
                    stats["gone"] += 1
                    await session.delete(open_row)
                elif sale is None:
                    if (
                        item.get("itemEndDate")
                        and closed_auction_from_item({**item, "bidCount": 1}, marketplace) is None
                    ):
                        stats["still_open"] += 1  # end date moved into the future
                        await session.commit()
                        continue
                    stats["unsold"] += 1
                    await session.delete(open_row)
                else:
                    await close_auction(session, open_row, sale)
                    stats["sold"] += 1
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

    async def body(
        sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any], checkpoint: Checkpoint
    ) -> None:
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
            await checkpoint()
        async with sessions() as session:
            stats["reconcile"] = await link_by_elimination(session)
            await session.commit()

    return await _run_job(engine, "numista_catalog", body, stats)


CATALOG_PRICE_TTL_DAYS = 30


async def run_numista_prices(
    engine: AsyncEngine,
    *,
    data_dir: Path,
    api_key: str,
    user_agent: str,
    max_calls: int = 1200,
) -> SyncRun:
    """Fetch Numista catalog values for issues lacking a fresh one. Stored with basis
    "catalog" so the valuation layer ranks them below realized sales."""
    client = NumistaClient(
        api_key=api_key, user_agent=user_agent, cache_dir=data_dir / "cache" / "numista"
    )
    stats: dict[str, Any] = {
        "issues_priced": 0,
        "issues_without_prices": 0,
        "budget_exhausted": False,
    }

    async def body(
        sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any], checkpoint: Checkpoint
    ) -> None:
        fresh_after = datetime.now(UTC) - timedelta(days=CATALOG_PRICE_TTL_DAYS)
        async with sessions() as session:
            fresh = (
                select(PriceEstimate.issue_id)
                .where(PriceEstimate.basis == "catalog", PriceEstimate.computed_at >= fresh_after)
                .distinct()
            )
            targets = (
                await session.execute(
                    select(CoinIssue.id, CoinIssue.numista_issue_id, CoinType.numista_type_id)
                    .join(CoinType, CoinType.id == CoinIssue.type_id)
                    .where(
                        CoinIssue.numista_issue_id.is_not(None),
                        CoinType.numista_type_id.is_not(None),
                        CoinIssue.id.not_in(fresh),
                    )
                    # scarcest first: the coins people ask about get a value on day one
                    .order_by(CoinIssue.mintage.asc().nulls_last(), CoinIssue.year.desc())
                )
            ).all()
        for i, (issue_id, numista_issue_id, numista_type_id) in enumerate(targets):
            if i >= max_calls:
                stats["budget_exhausted"] = True
                break
            payload = await client.get_prices(numista_type_id, numista_issue_id)
            prices = parse_prices(payload)
            async with sessions() as session:
                existing = {
                    e.grade: e
                    for e in (
                        await session.scalars(
                            select(PriceEstimate).where(
                                PriceEstimate.issue_id == issue_id, PriceEstimate.basis == "catalog"
                            )
                        )
                    ).all()
                }
                for grade, value in prices.items():
                    row = existing.get(grade)
                    if row is None:
                        session.add(
                            PriceEstimate(
                                issue_id=issue_id,
                                grade=grade,
                                region="global",
                                window_days=0,
                                median=value,
                                p25=value,
                                p75=value,
                                n_obs=0,
                                confidence="catalog",
                                basis="catalog",
                                method_version="numista-catalog-v1",
                            )
                        )
                    else:
                        row.median = row.p25 = row.p75 = value
                        row.computed_at = datetime.now(UTC)
                await session.commit()
            if prices:
                stats["issues_priced"] += 1
            else:
                stats["issues_without_prices"] += 1

    return await _run_job(engine, "numista_prices", body, stats)


async def run_reconcile(engine: AsyncEngine) -> SyncRun:
    stats: dict[str, Any] = {}

    async def body(
        sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any], checkpoint: Checkpoint
    ) -> None:
        async with sessions() as session:
            stats.update(await link_by_elimination(session))
            editions = await link_editions_to_base(session)
            stats["editions_linked"] = editions["linked"]
            stats["editions_unmatched"] = editions["unmatched"]
            await session.commit()

    return await _run_job(engine, "reconcile", body, stats)


WEB_COINS_PER_RUN = 60  # x up to 16 pages each, 1.5 s apart per host: a gentle daily crawl


async def web_targets(session: AsyncSession, limit: int = WEB_COINS_PER_RUN) -> list[uuid.UUID]:
    """Designs worth asking the web about today: followed ones first, then the ones with recent
    market activity, then the rest by year (newest first) so every coin gets its turn."""
    watched = list(await session.scalars(select(WatchItem.type_id).distinct()))
    recent = list(
        await session.scalars(
            select(CoinIssue.type_id)
            .join(MarketObservation, MarketObservation.issue_id == CoinIssue.id)
            .where(MarketObservation.observed_at >= datetime.now(UTC) - timedelta(days=30))
            .distinct()
        )
    )
    rest = list(
        await session.scalars(
            select(CoinType.id)
            .where(CoinType.base_type_id.is_(None))
            .order_by(CoinType.year.desc(), CoinType.country_code)
        )
    )
    out: list[uuid.UUID] = []
    for type_id in [*watched, *recent, *rest]:
        if type_id not in out:
            out.append(type_id)
        if len(out) >= limit:
            break
    return out


async def run_web_listings(engine: AsyncEngine, *, user_agent: str) -> SyncRun:
    """Read what shops and classified sites publish for the coins that matter today."""
    from euro2core.platform.market_assistant import _title
    from euro2core.platform.web_market import search_coin
    from euro2core.sources.web.fetcher import PoliteFetcher

    stats: dict[str, Any] = {
        "coins": 0,
        "queries": 0,
        "pages": 0,
        "listings_stored": 0,
        "refused": 0,
    }
    fetcher = PoliteFetcher(user_agent)

    async def body(
        sessions: Sessions, stats: dict[str, Any], cursor: dict[str, Any], checkpoint: Checkpoint
    ) -> None:
        async with sessions() as session:
            targets = await web_targets(session)
        done = set(cursor.get("done", []))
        for type_id in targets:
            if str(type_id) in done:
                continue
            async with sessions() as session:
                coin_type = await session.get(CoinType, type_id)
                if coin_type is None:
                    continue
                title = await _title(session, type_id, "en") or await _title(session, type_id, "es")
                result = await search_coin(session, fetcher, coin_type, title or None)
                await session.commit()
            stats["coins"] += 1
            stats["queries"] += result.queries
            stats["pages"] += result.pages
            stats["listings_stored"] += result.ingest.stored if result.ingest else 0
            stats["refused"] += len(result.refused)
            done.add(str(type_id))
            cursor["done"] = sorted(done)
            await checkpoint()
            if result.refused and any("duckduckgo" in r for r in result.refused):
                break  # the search engine itself said no: stop for today

    return await _run_job(engine, "web_listings", body, stats)
