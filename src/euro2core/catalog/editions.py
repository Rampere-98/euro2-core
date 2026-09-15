"""Special editions (coloured, hologram, "classic version") are the plain emission with a
finish applied. Numista lists them as their own types and they stay standalone in the catalog;
here each one is pointed at the ECB emission it derives from, so the official photo and the
official facts can be shown next to it."""

import logging
import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.catalog.reconcile import PAIR_THRESHOLD
from euro2core.domain.enums import CoinKind
from euro2core.domain.models import CoinType, TextTranslation
from euro2core.sources.linker import link_score
from euro2core.sources.numista.variants import base_title, variant_kind

log = logging.getLogger(__name__)

_CLASSIC = re.compile(r"-\s*classic version", re.IGNORECASE)
# A plain Numista record left over after reconciliation is usually a second listing of an
# emission the ECB coin already took (Numista splits some by mint); require a clearer match.
DUPLICATE_THRESHOLD = 60


def is_special_edition(title: str) -> bool:
    return variant_kind(title) is not None or _CLASSIC.search(title) is not None


async def link_editions_to_base(session: AsyncSession) -> dict[str, int]:
    """Set `base_type_id` on every Numista-only commemorative that is a special edition — or a
    second listing — of an ECB emission of the same country and year with a matching title."""
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
            .where(CoinType.kind == CoinKind.COMMEMORATIVE)
        )
    ).all()
    ecb_by_group: dict[tuple[str, int], list[tuple[CoinType, str]]] = defaultdict(list)
    editions: list[tuple[CoinType, str]] = []
    for coin_type, title in rows:
        if coin_type.ecb_ref is not None:
            ecb_by_group[(coin_type.country_code, coin_type.year)].append((coin_type, title))
        elif coin_type.base_type_id is None and coin_type.numista_type_id is not None:
            editions.append((coin_type, title))
    stats = {"linked": 0, "unmatched": 0}
    for edition, title in editions:
        candidates = ecb_by_group.get((edition.country_code, edition.year), [])
        plain = base_title(title)
        scored = sorted(
            ((link_score(plain, None, ecb_title), ecb) for ecb, ecb_title in candidates),
            key=lambda x: -x[0],
        )
        threshold = PAIR_THRESHOLD if is_special_edition(title) else DUPLICATE_THRESHOLD
        if scored and scored[0][0] >= threshold:
            edition.base_type_id = scored[0][1].id
            stats["linked"] += 1
            log.info("edition %s -> base %s", edition.numista_type_id, scored[0][1].ecb_ref)
        else:
            stats["unmatched"] += 1
    await session.flush()
    return stats
