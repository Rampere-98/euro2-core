"""Achievements: computed from the collection, awarded once, announced with a notification."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import CoinKind
from euro2core.domain.models import (
    CoinIssue,
    CoinType,
    CollectionItem,
    Notification,
    RarityScore,
    UserAchievement,
)

COUNT_MILESTONES = ((1, "first_coin"), (10, "ten_coins"), (50, "fifty_coins"), (200, "two_hundred"))
TITLES = {
    "first_coin": ("First coin", "Primera moneda"),
    "ten_coins": ("Ten coins", "Diez monedas"),
    "fifty_coins": ("Fifty coins", "Cincuenta monedas"),
    "two_hundred": ("Two hundred coins", "Doscientas monedas"),
    "verified_piece": ("Verified piece", "Pieza verificada"),
    "rare_hunter": ("Rare hunter", "Cazador de rarezas"),
}


@dataclass(frozen=True)
class Achievement:
    code: str
    title_en: str
    title_es: str
    details: dict


def _series_titles(kind: str, key: str) -> tuple[str, str]:
    if kind == "country_complete":
        return (f"Complete country: {key}", f"País completo: {key}")
    if kind == "joint_complete":
        return (f"Complete joint issue: {key}", f"Emisión conjunta completa: {key}")
    return (kind, kind)


async def evaluate(session: AsyncSession, user_id: uuid.UUID) -> list[Achievement]:
    """Award every achievement the collection now qualifies for and not yet earned."""
    owned_types = set(
        (
            await session.scalars(
                select(CoinIssue.type_id)
                .join(CollectionItem, CollectionItem.issue_id == CoinIssue.id)
                .where(CollectionItem.user_id == user_id)
                .distinct()
            )
        ).all()
    )
    pieces = await session.scalar(
        select(func.count()).select_from(CollectionItem).where(CollectionItem.user_id == user_id)
    )
    earned_before = set(
        (
            await session.scalars(
                select(UserAchievement.code).where(UserAchievement.user_id == user_id)
            )
        ).all()
    )
    candidates: list[Achievement] = []
    for threshold, code in COUNT_MILESTONES:
        if pieces >= threshold:
            en, es = TITLES[code]
            candidates.append(Achievement(code, en, es, {"pieces": pieces}))
    if owned_types:
        candidates += await _series_completions(session, owned_types)
        candidates += await _rarity_and_verification(session, user_id, owned_types)
    fresh = [a for a in candidates if a.code not in earned_before]
    for a in fresh:
        session.add(UserAchievement(user_id=user_id, code=a.code, details=a.details))
        session.add(
            Notification(
                user_id=user_id,
                kind="achievement",
                title=a.title_es,
                body=a.title_en,
                payload={"code": a.code, **a.details},
            )
        )
    await session.flush()
    return fresh


async def _series_completions(session: AsyncSession, owned: set) -> list[Achievement]:
    out: list[Achievement] = []
    rows = (
        await session.execute(
            select(CoinType.country_code, CoinType.joint_issue_group, CoinType.id).where(
                CoinType.kind == CoinKind.COMMEMORATIVE
            )
        )
    ).all()
    by_country: dict[str, set] = {}
    by_group: dict[str, set] = {}
    for country, group, type_id in rows:
        by_country.setdefault(country, set()).add(type_id)
        if group:
            by_group.setdefault(group, set()).add(type_id)
    for country, types in by_country.items():
        if types and types <= owned:
            en, es = _series_titles("country_complete", country)
            out.append(Achievement(f"country_complete:{country}", en, es, {"types": len(types)}))
    for group, types in by_group.items():
        if len(types) > 1 and types <= owned:
            en, es = _series_titles("joint_complete", group)
            out.append(Achievement(f"joint_complete:{group}", en, es, {"types": len(types)}))
    return out


async def _rarity_and_verification(
    session: AsyncSession, user_id: uuid.UUID, owned_types: set
) -> list[Achievement]:
    out: list[Achievement] = []
    exceptional = await session.scalar(
        select(func.count())
        .select_from(CollectionItem)
        .join(RarityScore, RarityScore.issue_id == CollectionItem.issue_id)
        .where(CollectionItem.user_id == user_id, RarityScore.tier == "exceptional")
    )
    if exceptional:
        en, es = TITLES["rare_hunter"]
        out.append(Achievement("rare_hunter", en, es, {"exceptional_pieces": exceptional}))
    verified = await session.scalar(
        select(func.count())
        .select_from(CollectionItem)
        .where(CollectionItem.user_id == user_id, CollectionItem.verified_at.is_not(None))
    )
    if verified:
        en, es = TITLES["verified_piece"]
        out.append(Achievement("verified_piece", en, es, {"verified_pieces": verified}))
    return out


async def leaderboard(session: AsyncSession, limit: int = 50) -> list[dict]:
    """Score = pieces owned + rarity bonus (a 100-point piece is worth five extra points)."""
    from euro2core.domain.models import User

    rows = (
        await session.execute(
            select(
                User.id,
                User.display_name,
                User.country_code,
                func.count(CollectionItem.id),
                func.coalesce(func.sum(RarityScore.score), 0.0),
            )
            .join(CollectionItem, CollectionItem.user_id == User.id)
            .outerjoin(RarityScore, RarityScore.issue_id == CollectionItem.issue_id)
            .group_by(User.id, User.display_name, User.country_code)
        )
    ).all()
    ranked = [
        {
            "user_id": uid,
            "display_name": name,
            "country_code": cc,
            "pieces": pieces,
            "score": round(pieces + float(rarity) / 20, 1),
        }
        for uid, name, cc, pieces, rarity in rows
    ]
    ranked.sort(key=lambda r: -r["score"])
    for i, r in enumerate(ranked[:limit], start=1):
        r["rank"] = i
    return ranked[:limit]
