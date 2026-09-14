"""Read helpers shared by routers: translations, facts with provenance, images."""

import uuid
from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.schemas import FactAlternative, FactOut, ImageOut
from euro2core.domain.models import CoinImage, FactClaim, Source, TextTranslation


async def translations_for(
    session: AsyncSession, entity: str, ids: Iterable[uuid.UUID], lang: str
) -> dict[uuid.UUID, dict[str, str]]:
    """Field -> text per entity, preferring `lang` and falling back to English."""
    ids = list(ids)
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(TextTranslation).where(
                TextTranslation.entity == entity, TextTranslation.entity_id.in_(ids)
            )
        )
    ).scalars()
    by_entity: dict[uuid.UUID, dict[str, dict[str, str]]] = defaultdict(lambda: defaultdict(dict))
    for t in rows:
        by_entity[t.entity_id][t.field][t.lang] = t.text
    out: dict[uuid.UUID, dict[str, str]] = {}
    for entity_id, fields in by_entity.items():
        out[entity_id] = {
            field: langs.get(lang) or langs.get("en") or next(iter(langs.values()))
            for field, langs in fields.items()
        }
    return out


async def languages_for(session: AsyncSession, entity: str, entity_id: uuid.UUID) -> list[str]:
    rows = await session.scalars(
        select(TextTranslation.lang)
        .where(TextTranslation.entity == entity, TextTranslation.entity_id == entity_id)
        .distinct()
    )
    return sorted(rows.all())


async def facts_for(session: AsyncSession, entity: str, entity_id: uuid.UUID) -> dict[str, FactOut]:
    rows = (
        await session.execute(
            select(FactClaim, Source.code, Source.authority_rank)
            .join(Source, Source.id == FactClaim.source_id)
            .where(FactClaim.entity == entity, FactClaim.entity_id == entity_id)
            .order_by(FactClaim.field, FactClaim.observed_at.desc())
        )
    ).all()
    grouped: dict[str, list] = defaultdict(list)
    for claim, code, rank in rows:
        grouped[claim.field].append((claim, code, rank))
    facts: dict[str, FactOut] = {}
    for field, claims in grouped.items():
        winner = next(((c, code) for c, code, _ in claims if c.is_winner), None)
        if winner is None:
            continue
        w, w_code = winner
        alternatives = [
            FactAlternative(
                value=c.value, source=code, observed_at=c.observed_at, evidence_url=c.evidence_url
            )
            for c, code, _ in claims
            if not c.is_winner and c.value != w.value
        ]
        facts[field] = FactOut(
            value=w.value,
            source=w_code,
            observed_at=w.observed_at,
            evidence_url=w.evidence_url,
            has_conflict=any(
                rank >= 50 for c, _, rank in claims if not c.is_winner and c.value != w.value
            ),
            alternatives=alternatives,
        )
    return facts


async def images_for_types(
    session: AsyncSession, type_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[ImageOut]]:
    type_ids = list(type_ids)
    if not type_ids:
        return {}
    rows = (
        await session.scalars(
            select(CoinImage).where(CoinImage.type_id.in_(type_ids)).order_by(CoinImage.fetched_at)
        )
    ).all()
    out: dict[uuid.UUID, list[ImageOut]] = defaultdict(list)
    for img in rows:
        out[img.type_id].append(image_out(img))
    return out


async def images_for_issue(session: AsyncSession, issue_id: uuid.UUID) -> list[ImageOut]:
    rows = (await session.scalars(select(CoinImage).where(CoinImage.issue_id == issue_id))).all()
    return [image_out(i) for i in rows]


def image_out(img: CoinImage) -> ImageOut:
    return ImageOut(
        id=img.id,
        side=img.side.value,
        url=f"/images/{img.id}",
        source_url=img.source_url,
        author=img.author,
        license=img.license,
    )
