"""Reconcile catalog records that different sources created for the same coin."""

import logging
from collections import defaultdict

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.catalog.claims import resolve_field
from euro2core.domain.enums import CoinKind
from euro2core.domain.models import (
    CoinImage,
    CoinIssue,
    CoinType,
    DomainEvent,
    FactClaim,
    TextTranslation,
)
from euro2core.sources.linker import link_score
from euro2core.sources.numista.variants import base_title, variant_kind

log = logging.getLogger(__name__)


PAIR_THRESHOLD = 45
LEFTOVER_THRESHOLD = 25  # a last pair in a bigger group must at least look related
# groups that started with more than one candidate per side, within one link_by_elimination call
_lonely_groups: dict[tuple[str, int], bool] = {}


async def link_by_elimination(session: AsyncSession) -> dict[str, int]:
    """Link Numista commemoratives that fuzzy matching missed to their ECB emission.

    Per country and year: a lone leftover on each side is the same coin; bigger groups are paired
    by title similarity, repeatedly, until nothing more can be settled. Coloured and hologram
    editions stay standalone types.
    """
    totals = {"merged": 0, "ambiguous": 0, "unmatched": 0, "editions_kept": 0}
    _lonely_groups.clear()
    while True:
        stats = await _link_pass(session)
        totals["merged"] += stats["merged"]
        totals.update({k: stats[k] for k in ("ambiguous", "unmatched", "editions_kept")})
        if stats["merged"] == 0:
            return totals


async def _link_pass(session: AsyncSession) -> dict[str, int]:
    rows = (
        await session.execute(
            select(CoinType, TextTranslation.text)
            .join(
                TextTranslation,
                (TextTranslation.entity == "coin_type")
                & (TextTranslation.entity_id == CoinType.id)
                & (TextTranslation.field == "title")
                & (TextTranslation.lang == "en"),
            )
            .where(
                CoinType.kind == CoinKind.COMMEMORATIVE,
                (CoinType.ecb_ref.is_(None)) | (CoinType.numista_type_id.is_(None)),
            )
        )
    ).all()
    groups: dict[tuple[str, int], dict[str, list[tuple[CoinType, str]]]] = defaultdict(
        lambda: {"ecb": [], "numista": []}
    )
    stats = {"merged": 0, "ambiguous": 0, "unmatched": 0, "editions_kept": 0}
    for t, title in rows:
        if t.ecb_ref is not None and t.numista_type_id is None:
            groups[(t.country_code, t.year)]["ecb"].append((t, title))
        elif t.ecb_ref is None and t.numista_type_id is not None:
            if variant_kind(title):
                stats["editions_kept"] += 1
                continue
            groups[(t.country_code, t.year)]["numista"].append((t, base_title(title)))
    for (country, year), sides in groups.items():
        ecb_side, numista_side = sides["ecb"], sides["numista"]
        if not ecb_side or not numista_side:
            stats["unmatched"] += 1
            continue
        if len(ecb_side) == 1 and len(numista_side) == 1:
            score = link_score(numista_side[0][1], None, ecb_side[0][1])
            group_was_lonely = _lonely_groups.get((country, year), True)
            if group_was_lonely or score >= LEFTOVER_THRESHOLD:
                pairs = [(ecb_side[0][0], numista_side[0][0])]
            else:
                stats["ambiguous"] += 1
                pairs = []
        else:
            _lonely_groups[(country, year)] = False
            pairs = _pair_by_similarity(ecb_side, numista_side)
            if len(pairs) < min(len(ecb_side), len(numista_side)):
                stats["ambiguous"] += 1
        for keep, drop in pairs:
            await merge_types(session, keep=keep, drop=drop)
            log.info("merged Numista %s into ECB %s", drop.numista_type_id, keep.ecb_ref)
            stats["merged"] += 1
    await session.flush()
    return stats


def _pair_by_similarity(
    ecb_side: list[tuple[CoinType, str]], numista_side: list[tuple[CoinType, str]]
) -> list[tuple[CoinType, CoinType]]:
    scored = sorted(
        (
            (link_score(n_title, None, e_title), e, n)
            for e, e_title in ecb_side
            for n, n_title in numista_side
        ),
        key=lambda x: -x[0],
    )
    used_e: set = set()
    used_n: set = set()
    pairs: list[tuple[CoinType, CoinType]] = []
    for score, e, n in scored:
        if score < PAIR_THRESHOLD:
            break
        if e.id in used_e or n.id in used_n:
            continue
        pairs.append((e, n))
        used_e.add(e.id)
        used_n.add(n.id)
    return pairs


async def merge_types(session: AsyncSession, *, keep: CoinType, drop: CoinType) -> None:
    """Move everything attached to `drop` onto `keep`, then delete `drop`."""
    numista_id = drop.numista_type_id
    drop.numista_type_id = None
    await session.flush()
    keep.numista_type_id = numista_id
    await session.execute(
        update(CoinIssue).where(CoinIssue.type_id == drop.id).values(type_id=keep.id)
    )
    await session.execute(
        update(CoinImage).where(CoinImage.type_id == drop.id).values(type_id=keep.id)
    )
    await session.execute(
        update(CoinType).where(CoinType.base_type_id == drop.id).values(base_type_id=keep.id)
    )
    await session.execute(
        update(FactClaim)
        .where(FactClaim.entity == "coin_type", FactClaim.entity_id == drop.id)
        .values(entity_id=keep.id)
    )
    await session.execute(
        update(DomainEvent)
        .where(DomainEvent.entity == "coin_type", DomainEvent.entity_id == drop.id)
        .values(entity_id=keep.id)
    )
    await _move_translations(session, keep, drop)
    await session.delete(drop)
    await session.flush()
    fields = (
        await session.scalars(
            select(FactClaim.field)
            .where(FactClaim.entity == "coin_type", FactClaim.entity_id == keep.id)
            .distinct()
        )
    ).all()
    for field in fields:
        await resolve_field(session, "coin_type", keep.id, field, keep)
    session.add(
        DomainEvent(
            kind="types_merged",
            entity="coin_type",
            entity_id=keep.id,
            payload={"numista_type_id": numista_id, "ecb_ref": keep.ecb_ref},
        )
    )


async def _move_translations(session: AsyncSession, keep: CoinType, drop: CoinType) -> None:
    existing = {
        (t.field, t.lang)
        for t in (
            await session.scalars(
                select(TextTranslation).where(
                    TextTranslation.entity == "coin_type", TextTranslation.entity_id == keep.id
                )
            )
        ).all()
    }
    moving = (
        await session.scalars(
            select(TextTranslation).where(
                TextTranslation.entity == "coin_type", TextTranslation.entity_id == drop.id
            )
        )
    ).all()
    for t in moving:
        if (t.field, t.lang) in existing:
            await session.delete(t)  # the kept type already has this text from a ranked source
        else:
            t.entity_id = keep.id
