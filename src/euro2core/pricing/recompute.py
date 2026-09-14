"""Turn market observations into stored price estimates and outlier flags."""

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import Grade
from euro2core.domain.models import DomainEvent, MarketObservation, PriceEstimate
from euro2core.pricing.estimator import (
    EXTENDED_WINDOW_DAYS,
    GLOBAL_REGION,
    Estimate,
    Observation,
    estimate,
)

log = logging.getLogger(__name__)

SPIKE_THRESHOLD = 0.30
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
                    PriceEstimate.issue_id == issue_id, PriceEstimate.basis != CATALOG_BASIS
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
