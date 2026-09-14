"""Persist source claims, resolve winners by authority, and apply them to the catalog."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.consensus.resolver import Claim, normalize, resolve
from euro2core.domain.enums import CoinKind
from euro2core.domain.models import DomainEvent, FactClaim, Source

# Fields whose resolved winner is copied onto a column of the entity itself.
APPLIED_FIELDS: dict[str, frozenset[str]] = {
    "coin_type": frozenset({"kind", "mintage_total", "joint_issue_group"}),
    "coin_issue": frozenset({"mintage"}),
}
COERCIONS: dict[str, Any] = {"kind": CoinKind}


async def record_claim(
    session: AsyncSession,
    *,
    entity: str,
    entity_id: uuid.UUID,
    field: str,
    value: Any,
    source: Source,
    evidence_url: str | None = None,
    observed_at: datetime | None = None,
) -> FactClaim | None:
    """Store a claim unless this source already asserts the same value for the field."""
    latest = (
        await session.scalars(
            select(FactClaim)
            .where(
                FactClaim.entity == entity,
                FactClaim.entity_id == entity_id,
                FactClaim.field == field,
                FactClaim.source_id == source.id,
            )
            .order_by(FactClaim.observed_at.desc())
            .limit(1)
        )
    ).first()
    if latest is not None and normalize(field, latest.value) == normalize(field, value):
        return None
    claim = FactClaim(
        entity=entity,
        entity_id=entity_id,
        field=field,
        value=value,
        source_id=source.id,
        observed_at=observed_at or datetime.now(UTC),
        evidence_url=evidence_url,
    )
    session.add(claim)
    await session.flush()
    return claim


async def resolve_field(
    session: AsyncSession, entity: str, entity_id: uuid.UUID, field: str, target: Any
) -> Any:
    """Recompute the winner for one field, flag rows, apply to `target`, emit events."""
    rows = (
        await session.scalars(
            select(FactClaim).where(
                FactClaim.entity == entity,
                FactClaim.entity_id == entity_id,
                FactClaim.field == field,
            )
        )
    ).all()
    if not rows:
        return None
    ranks = {
        s.id: s.authority_rank
        for s in (
            await session.scalars(select(Source).where(Source.id.in_({r.source_id for r in rows})))
        ).all()
    }
    by_id = {r.id: r for r in rows}
    resolution = resolve(
        Claim(
            entity=r.entity,
            entity_id=r.entity_id,
            field=r.field,
            value=r.value,
            source_code=str(r.id),
            authority_rank=ranks[r.source_id],
            observed_at=r.observed_at,
        )
        for r in rows
    )
    winner_row = by_id[uuid.UUID(resolution.winner.source_code)]
    previous_winner = next((r for r in rows if r.is_winner), None)
    for r in rows:
        r.is_winner = r is winner_row
    if previous_winner is not None and previous_winner is not winner_row:
        prev_norm, new_norm = (
            normalize(field, previous_winner.value),
            normalize(field, winner_row.value),
        )
        if prev_norm != new_norm:
            session.add(
                DomainEvent(
                    kind="fact_revised",
                    entity=entity,
                    entity_id=entity_id,
                    payload={
                        "field": field,
                        "previous": previous_winner.value,
                        "current": winner_row.value,
                        "has_conflict": resolution.has_conflict,
                    },
                )
            )
    if field in APPLIED_FIELDS.get(entity, frozenset()) and target is not None:
        coerce = COERCIONS.get(field)
        setattr(target, field, coerce(winner_row.value) if coerce else winner_row.value)
    return winner_row.value
