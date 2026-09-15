"""Read helpers shared by routers: translations, facts with provenance, images."""

import uuid
from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.schemas import FactAlternative, FactOut, ImageOut, TypeSummary, ValueHint
from euro2core.consensus.resolver import CONFLICT_MIN_RANK, normalize
from euro2core.domain.models import (
    CoinImage,
    CoinIssue,
    CoinType,
    FactClaim,
    PriceEstimate,
    Source,
    TextTranslation,
)


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
        w_norm = normalize(field, w.value)
        differing = [
            (c, code, rank)
            for c, code, rank in claims
            if not c.is_winner and normalize(field, c.value) != w_norm
        ]
        alternatives = [
            FactAlternative(
                value=c.value, source=code, observed_at=c.observed_at, evidence_url=c.evidence_url
            )
            for c, code, _ in differing
        ]
        facts[field] = FactOut(
            value=w.value,
            source=w_code,
            observed_at=w.observed_at,
            evidence_url=w.evidence_url,
            has_conflict=any(rank >= CONFLICT_MIN_RANK for _, _, rank in differing),
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
    # a derived type (special edition, error) without its own photo shows the base design
    bases = (
        await session.execute(
            select(CoinType.id, CoinType.base_type_id).where(
                CoinType.id.in_([t for t in type_ids if t not in out]),
                CoinType.base_type_id.is_not(None),
            )
        )
    ).all()
    if bases:
        base_rows = (
            await session.scalars(
                select(CoinImage)
                .where(
                    CoinImage.type_id.in_({b for _, b in bases}), CoinImage.local_path.is_not(None)
                )
                .order_by(CoinImage.fetched_at)
            )
        ).all()
        base_images: dict[uuid.UUID, list[CoinImage]] = defaultdict(list)
        for img in base_rows:
            base_images[img.type_id].append(img)
        for type_id, base_id in bases:
            out[type_id] = [image_out(img, borrowed=True) for img in base_images.get(base_id, [])]
    return out


async def images_for_issue(session: AsyncSession, issue_id: uuid.UUID) -> list[ImageOut]:
    rows = (await session.scalars(select(CoinImage).where(CoinImage.issue_id == issue_id))).all()
    return [image_out(i) for i in rows]


def image_out(img: CoinImage, *, borrowed: bool = False) -> ImageOut:
    return ImageOut(
        borrowed=borrowed,
        id=img.id,
        side=img.side.value,
        url=f"/images/{img.id}" if img.local_path else None,
        source_url=img.source_url,
        author=img.author,
        license=img.license,
    )


BASIS_ORDER = case(
    (PriceEstimate.basis == "sold", 0),
    (PriceEstimate.basis == "catalog", 1),
    (PriceEstimate.basis == "mintage_model", 2),
    (PriceEstimate.basis == "asking_only", 3),
    else_=9,
)


def type_value_subquery():
    """One value range per coin type: the estimate of its reference variant — best basis
    available, then the largest mintage (the loose coin most people hold). Proof and other
    scarce variants are shown on the coin page, not in list rows."""
    mintage = func.coalesce(CoinIssue.mintage, CoinType.mintage_total)
    ranked = (
        select(
            CoinIssue.type_id.label("type_id"),
            PriceEstimate.p25.label("p25"),
            PriceEstimate.p75.label("p75"),
            PriceEstimate.median.label("median"),
            PriceEstimate.basis.label("basis"),
            func.row_number()
            .over(
                partition_by=CoinIssue.type_id,
                order_by=(BASIS_ORDER, mintage.desc().nulls_last(), PriceEstimate.median),
            )
            .label("pos"),
        )
        .join(CoinIssue, CoinIssue.id == PriceEstimate.issue_id)
        .join(CoinType, CoinType.id == CoinIssue.type_id)
        .where(PriceEstimate.region == "global", PriceEstimate.median.is_not(None))
        .subquery()
    )
    return (
        select(
            ranked.c.type_id,
            ranked.c.p25.label("low"),
            ranked.c.p75.label("high"),
            ranked.c.median.label("median"),
            ranked.c.basis.label("basis"),
        )
        .where(ranked.c.pos == 1)
        .subquery()
    )


async def values_for_types(
    session: AsyncSession, type_ids: list[uuid.UUID]
) -> dict[uuid.UUID, ValueHint]:
    if not type_ids:
        return {}
    v = type_value_subquery()
    rows = (
        await session.execute(
            select(v.c.type_id, v.c.low, v.c.high, v.c.median, v.c.basis).where(
                v.c.type_id.in_(type_ids)
            )
        )
    ).all()
    return {
        type_id: ValueHint(low=low, high=high, median=median, basis=basis)
        for type_id, low, high, median, basis in rows
    }


async def summaries_for(
    session: AsyncSession, types: list[CoinType], lang: str
) -> list[TypeSummary]:
    ids = [t.id for t in types]
    texts = await translations_for(session, "coin_type", ids, lang)
    images = await images_for_types(session, ids)
    values = await values_for_types(session, ids)
    counts = (
        dict(
            (
                await session.execute(
                    select(CoinIssue.type_id, func.count())
                    .where(CoinIssue.type_id.in_(ids))
                    .group_by(CoinIssue.type_id)
                )
            ).all()
        )
        if ids
        else {}
    )
    return [
        TypeSummary(
            id=t.id,
            kind=t.kind.value,
            country_code=t.country_code,
            year=t.year,
            title=texts.get(t.id, {}).get("title"),
            mintage_total=t.mintage_total,
            joint_issue_group=t.joint_issue_group,
            ecb_ref=t.ecb_ref,
            numista_type_id=t.numista_type_id,
            base_type_id=t.base_type_id,
            issue_count=counts.get(t.id, 0),
            image=next(iter(images.get(t.id, [])), None),
            value=values.get(t.id),
        )
        for t in types
    ]
