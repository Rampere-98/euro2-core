"""Turn market observations into stored price estimates and outlier flags."""

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import CoinKind, Finish, Grade
from euro2core.domain.models import (
    DomainEvent,
    EstimateHistory,
    MarketObservation,
    PriceEstimate,
)
from euro2core.pricing.estimator import (
    EXTENDED_WINDOW_DAYS,
    GLOBAL_REGION,
    Estimate,
    Observation,
    estimate,
)

log = logging.getLogger(__name__)

SPIKE_THRESHOLD = 0.30
COMMON_DESIGN_MINTAGE = 10_000_000  # a circulation design nobody counted is not scarce
CATALOG_BASIS = "catalog"  # maintained by the numista_prices job, not by observations


async def recompute_issue_prices(
    session: AsyncSession, issue_id: uuid.UUID, now: datetime | None = None
) -> list[Estimate]:
    now = now or datetime.now(UTC)
    rows = (
        await session.scalars(
            select(MarketObservation).where(
                MarketObservation.issue_id == issue_id,
                MarketObservation.observed_at >= now - timedelta(days=EXTENDED_WINDOW_DAYS + 1),
            )
        )
    ).all()
    existing = {
        (e.grade, e.region): e
        for e in (
            await session.scalars(
                select(PriceEstimate).where(
                    PriceEstimate.issue_id == issue_id,
                    PriceEstimate.basis.not_in([CATALOG_BASIS, "mintage_model"]),
                )
            )
        ).all()
    }
    if not rows:
        # every observation aged out: a year-old price must not be served as current
        for stale in existing.values():
            await session.delete(stale)
        await session.flush()
        return []
    by_id = {str(r.id): r for r in rows}
    observations = [
        Observation(
            id=str(r.id),
            price=r.price,
            kind=r.observation_kind,
            grade=r.grade,
            marketplace=r.marketplace,
            observed_at=r.observed_at,
            match_confidence=r.match_confidence,
        )
        for r in rows
    ]
    grades = {r.grade for r in rows}
    regions = [GLOBAL_REGION, *sorted({r.marketplace for r in rows})]
    outlier_ids: set[str] = set()
    produced: list[Estimate] = []
    for grade in grades:
        for region in regions:
            est = estimate(observations, grade=grade, region=region, now=now)
            key = (grade, region)
            if est.median is None:
                if key in existing:
                    await session.delete(existing.pop(key))
                continue
            produced.append(est)
            if region == GLOBAL_REGION:
                outlier_ids.update(est.outlier_ids)
            previous = existing.get(key)
            if region == GLOBAL_REGION and (
                previous is None or previous.median != est.median or previous.basis != est.basis
            ):
                session.add(_history_row(issue_id, est))  # the chart keeps every change
            if previous is None:
                session.add(_to_row(issue_id, est))
            else:
                if region == GLOBAL_REGION and previous.basis == "sold" and est.basis == "sold":
                    _maybe_spike(session, issue_id, grade, previous, est)
                _update_row(previous, est)
    # grades/regions that no longer have a sample were neither updated nor deleted above
    kept = {(e.grade, e.region) for e in produced}
    for key, stale in list(existing.items()):
        if key not in kept:
            await session.delete(stale)
    for obs_id, row in by_id.items():
        row.is_outlier = obs_id in outlier_ids
    await session.flush()
    return produced


def _to_row(issue_id: uuid.UUID, est: Estimate) -> PriceEstimate:
    return PriceEstimate(
        issue_id=issue_id,
        grade=est.grade,
        region=est.region,
        window_days=est.window_days,
        median=est.median,
        p25=est.p25,
        p75=est.p75,
        n_obs=est.n_obs,
        confidence=est.confidence,
        basis=est.basis,
        method_version=est.method_version,
    )


def _history_row(issue_id: uuid.UUID, est: Estimate) -> EstimateHistory:
    return EstimateHistory(
        issue_id=issue_id,
        grade=est.grade,
        basis=est.basis,
        median=est.median,
        p25=est.p25,
        p75=est.p75,
        n_obs=est.n_obs,
    )


def _update_row(row: PriceEstimate, est: Estimate) -> None:
    row.window_days = est.window_days
    row.median = est.median
    row.p25 = est.p25
    row.p75 = est.p75
    row.n_obs = est.n_obs
    row.confidence = est.confidence
    row.basis = est.basis
    row.method_version = est.method_version
    row.computed_at = datetime.now(UTC)


def _maybe_spike(
    session: AsyncSession, issue_id: uuid.UUID, grade: Grade, previous: PriceEstimate, est: Estimate
) -> None:
    if not previous.median or not est.median:
        return
    change = float(est.median - previous.median) / float(previous.median)
    if abs(change) >= SPIKE_THRESHOLD:
        session.add(
            DomainEvent(
                kind="price_spike",
                entity="coin_issue",
                entity_id=issue_id,
                payload={
                    "grade": grade.value,
                    "previous_median": float(previous.median),
                    "median": float(est.median),
                    "change": round(change, 3),
                    "n_obs": est.n_obs,
                },
            )
        )


async def issues_with_observations(session: AsyncSession) -> list[uuid.UUID]:
    return list((await session.scalars(select(MarketObservation.issue_id).distinct())).all())


def summarize(estimates: list[Estimate]) -> dict[str, Any]:
    by_basis: dict[str, int] = defaultdict(int)
    for e in estimates:
        by_basis[e.basis] += 1
    return dict(by_basis)


async def recompute_model_estimates(session: AsyncSession) -> dict[str, int]:
    """Give every issue without real sales or a catalog value a `mintage_model` estimate
    (grade UNC, global), calibrated from the issues that do have real sales. Issues that
    gained a better basis lose their model row."""
    from euro2core.domain.models import CoinIssue, CoinType
    from euro2core.pricing.mintage_model import BASIS, METHOD_VERSION, calibrate, model_band

    sold = (
        await session.execute(
            select(CoinIssue.mintage, PriceEstimate.p25, PriceEstimate.p75)
            .join(CoinIssue, CoinIssue.id == PriceEstimate.issue_id)
            .where(
                PriceEstimate.basis == "sold",
                PriceEstimate.region == GLOBAL_REGION,
                PriceEstimate.grade == Grade.UNC,
            )
        )
    ).all()
    calibration = calibrate([(m, p25, p75) for m, p25, p75 in sold])

    better = (
        select(PriceEstimate.issue_id)
        .where(PriceEstimate.basis.in_(["sold", CATALOG_BASIS]))
        .distinct()
    )
    existing = {
        e.issue_id: e
        for e in (
            await session.scalars(select(PriceEstimate).where(PriceEstimate.basis == BASIS))
        ).all()
    }
    rows = (
        await session.execute(
            select(
                CoinIssue.id,
                CoinIssue.mintage,
                CoinIssue.finish,
                CoinType.id,
                CoinType.mintage_total,
                CoinType.base_type_id,
                CoinType.kind,
            )
            .join(CoinType, CoinType.id == CoinIssue.type_id)
            .where(CoinIssue.id.not_in(better))
        )
    ).all()
    # Scarcity belongs to the design, not to the packaging: a BU coincard of a 500 000-coin
    # emission is not a 10 000-coin rarity. Use the emission's total (or the sum of its
    # variants), and the base design's total for coloured/hologram editions.
    # Circulation designs are struck by the million; only the circulation strike's own
    # mintage (Vatican, Monaco, San Marino) can make one scarce — sets and proofs cannot.
    totals: dict[uuid.UUID, int | None] = {}
    for _, mintage, _finish, type_id, type_total, _, kind in rows:
        if kind == CoinKind.CIRCULATION:
            continue  # handled per issue below
        if type_total:
            totals[type_id] = type_total
        elif mintage:
            totals[type_id] = (totals.get(type_id) or 0) + mintage
        else:
            totals.setdefault(type_id, None)
    base_totals = dict(
        (
            await session.execute(
                select(CoinType.id, CoinType.mintage_total).where(
                    CoinType.id.in_({b for *_, b, _ in rows if b is not None})
                )
            )
        ).all()
    )
    # An edition (coloured, hologram) that could not be tied to its base design must not be
    # priced as a rare design: its small print run says nothing about demand.
    from euro2core.catalog.editions import is_special_edition
    from euro2core.domain.models import TextTranslation

    titles = dict(
        (
            await session.execute(
                select(TextTranslation.entity_id, TextTranslation.text).where(
                    TextTranslation.entity == "coin_type",
                    TextTranslation.field == "title",
                    TextTranslation.lang == "en",
                    TextTranslation.entity_id.in_({t for _, _, _, t, _, _, _ in rows}),
                )
            )
        ).all()
    )
    written = 0
    for issue_id, mintage, finish, type_id, _type_total, base_id, kind in rows:
        if kind == CoinKind.CIRCULATION:
            # each year stands alone: 2014 struck for sets only is scarce, 2016 by the million
            scarce_strike = finish == Finish.CIRCULATION and mintage
            design = mintage if scarce_strike else COMMON_DESIGN_MINTAGE
        elif base_id is not None:
            design = base_totals.get(base_id) or totals.get(type_id)
        else:
            design = totals.get(type_id)
        orphan_edition = base_id is None and is_special_edition(titles.get(type_id, ""))
        band = None if orphan_edition else model_band(design, finish, calibration)
        row = existing.pop(issue_id, None)
        if band is None:
            if row is not None:
                await session.delete(row)
            continue
        if row is None:
            session.add(
                PriceEstimate(
                    issue_id=issue_id,
                    grade=Grade.UNC,
                    region=GLOBAL_REGION,
                    window_days=0,
                    median=band.median,
                    p25=band.low,
                    p75=band.high,
                    n_obs=0,
                    confidence="model",
                    basis=BASIS,
                    method_version=METHOD_VERSION,
                )
            )
        else:
            row.median, row.p25, row.p75 = band.median, band.low, band.high
            row.computed_at = datetime.now(UTC)
        written += 1
    for stale in existing.values():  # a better basis appeared
        await session.delete(stale)
    await session.flush()
    return {"model_estimates": written, "calibrated_buckets": len(calibration)}
