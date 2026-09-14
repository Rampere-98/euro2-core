"""Compute rarity scores for every issue with a known mintage."""

import statistics
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import Finish, ObservationKind
from euro2core.domain.models import (
    CoinIssue,
    CoinType,
    MarketObservation,
    PriceEstimate,
    RarityScore,
)
from euro2core.pricing.estimator import GLOBAL_REGION
from euro2core.rarity.scorer import MarketSignals, score

ACTIVE_LISTING_WINDOW_DAYS = 30
MIN_CLASS_SIZE = 10  # below this a finish class keeps the default (circulation) scale


async def recompute_all_rarity(session: AsyncSession) -> dict[str, int]:
    now = datetime.now(UTC)
    issues = (await session.scalars(select(CoinIssue))).all()
    listings = await _active_listings(session, now)
    sale_medians = await _sale_medians(session)
    covered = await _searched_country_years(session)
    country_of = dict((await session.execute(select(CoinType.id, CoinType.country_code))).all())
    per_million = {
        i.id: listings.get(i.id, 0) / (i.mintage / 1_000_000)
        for i in issues
        if i.mintage and i.mintage > 0 and (country_of.get(i.type_id), i.year) in covered
    }
    with_supply = [v for v in per_million.values() if v > 0]
    baseline = statistics.median(with_supply) if with_supply else None
    bounds = _mintage_bounds_by_finish(issues)
    existing = {r.issue_id: r for r in (await session.scalars(select(RarityScore))).all()}

    stats = {"issues_scored": 0, "issues_without_mintage": 0}
    for issue in issues:
        if not issue.mintage or issue.mintage <= 0:
            stats["issues_without_mintage"] += 1
            continue
        result = score(
            issue.mintage,
            MarketSignals(
                active_listings_per_million=per_million.get(issue.id) if baseline else None,
                median_sale_price=sale_medians.get(issue.id),
                catalog_median_listings_per_million=baseline,
            ),
            mintage_bounds=bounds.get(issue.finish),
        )
        if result is None:
            continue
        row = existing.get(issue.id)
        if row is None:
            session.add(
                RarityScore(
                    issue_id=issue.id,
                    score=result.score,
                    tier=result.tier,
                    components=result.components,
                    method_version=result.method_version,
                )
            )
        else:
            row.score = result.score
            row.tier = result.tier
            row.components = result.components
            row.method_version = result.method_version
            row.computed_at = now
        stats["issues_scored"] += 1
    await session.flush()
    return stats


def _mintage_bounds_by_finish(issues) -> dict[Finish, tuple[int, int]]:
    """(rare, common) mintage per finish class from the catalog's own 1st/99th percentiles,
    so proofs are judged against proofs and circulation strikes against circulation strikes."""
    by_finish: dict[Finish, list[int]] = {}
    for issue in issues:
        if issue.mintage and issue.mintage > 0:
            by_finish.setdefault(issue.finish, []).append(issue.mintage)
    bounds: dict[Finish, tuple[int, int]] = {}
    for finish, mintages in by_finish.items():
        if len(mintages) < MIN_CLASS_SIZE:
            continue
        quantiles = statistics.quantiles(sorted(mintages), n=100, method="inclusive")
        rare, common = int(quantiles[0]), int(quantiles[-1])
        if common > rare:
            bounds[finish] = (rare, common)
    return bounds


async def _searched_country_years(session: AsyncSession) -> set[tuple[str, int]]:
    """(country, year) pairs with at least one observation: zero listings there is a signal;
    zero listings elsewhere only means the market job has not looked yet."""
    rows = await session.execute(
        select(CoinType.country_code, CoinIssue.year)
        .join(CoinIssue, CoinIssue.type_id == CoinType.id)
        .join(MarketObservation, MarketObservation.issue_id == CoinIssue.id)
        .distinct()
    )
    return {(c, y) for c, y in rows.all()}


async def _active_listings(session: AsyncSession, now: datetime) -> dict[uuid.UUID, int]:
    rows = await session.execute(
        select(MarketObservation.issue_id, func.count())
        .where(
            MarketObservation.observation_kind == ObservationKind.ASKING,
            MarketObservation.observed_at >= now - timedelta(days=ACTIVE_LISTING_WINDOW_DAYS),
            MarketObservation.match_confidence >= 0.85,
        )
        .group_by(MarketObservation.issue_id)
    )
    return dict(rows.all())


async def _sale_medians(session: AsyncSession) -> dict[uuid.UUID, Decimal]:
    """Global sold-based median per issue, taking the grade with the largest sample."""
    rows = (
        await session.scalars(
            select(PriceEstimate).where(
                PriceEstimate.region == GLOBAL_REGION,
                PriceEstimate.basis == "sold",
                PriceEstimate.median.is_not(None),
            )
        )
    ).all()
    best: dict[uuid.UUID, PriceEstimate] = {}
    for est in rows:
        current = best.get(est.issue_id)
        if current is None or est.n_obs > current.n_obs:
            best[est.issue_id] = est
    return {issue_id: est.median for issue_id, est in best.items()}
