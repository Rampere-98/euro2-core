"""Resolve a marketplace listing title to a concrete coin issue with a confidence score."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import CoinKind, Finish, Grade, Packaging
from euro2core.domain.models import CoinIssue, CoinType, TextTranslation
from euro2core.pricing.title_parser import ParsedTitle, parse_title
from euro2core.sources.linker import link_score

NO_THEME_CONFIDENCE = 0.5
MISSING_MINT_MARK_CAP = 0.8
FINISH_FALLBACK_PENALTY = 0.15


@dataclass(frozen=True)
class Match:
    issue_id: uuid.UUID
    type_id: uuid.UUID
    confidence: float
    grade: Grade
    sheldon: int | None
    certified_by: str | None
    parsed: ParsedTitle


async def match_listing(session: AsyncSession, title: str) -> Match | None:
    parsed = parse_title(title)
    if parsed.is_lot or parsed.country_code is None or parsed.year is None:
        return None
    candidates = (
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
                CoinType.country_code == parsed.country_code,
                CoinType.year <= parsed.year,
                CoinType.kind != CoinKind.ERROR,
            )
        )
    ).all()
    candidates = [(ct, t) for ct, t in candidates if _type_covers_year(ct, parsed.year)]
    if not candidates:
        return None

    if parsed.theme_text:
        scored = [(link_score(parsed.theme_text, None, t), ct) for ct, t in candidates]
        best_score, best_type = max(scored, key=lambda x: x[0])
        confidence = best_score / 100
    elif len(candidates) == 1:
        best_type, confidence = candidates[0][0], NO_THEME_CONFIDENCE
    else:
        return None
    if confidence < 0.4:
        return None

    issue, confidence = await _pick_issue(session, best_type, parsed, confidence)
    if issue is None:
        return None
    return Match(
        issue_id=issue.id,
        type_id=best_type.id,
        confidence=round(min(confidence, 1.0), 3),
        grade=parsed.grade,
        sheldon=parsed.sheldon,
        certified_by=parsed.certified_by,
        parsed=parsed,
    )


def _type_covers_year(coin_type: CoinType, year: int) -> bool:
    if coin_type.kind == CoinKind.CIRCULATION:
        return True  # circulation types span years; issues carry the exact year
    return coin_type.year == year


async def _pick_issue(
    session: AsyncSession, coin_type: CoinType, parsed: ParsedTitle, confidence: float
) -> tuple[CoinIssue | None, float]:
    issues = (
        await session.scalars(
            select(CoinIssue).where(
                CoinIssue.type_id == coin_type.id, CoinIssue.year == parsed.year
            )
        )
    ).all()
    if not issues:
        return None, confidence
    finish = parsed.finish or Finish.CIRCULATION
    packaging = parsed.packaging or Packaging.LOOSE
    pool = [i for i in issues if i.finish == finish]
    if not pool:
        pool, confidence = issues, confidence - FINISH_FALLBACK_PENALTY
    exact_packaging = [i for i in pool if i.packaging == packaging]
    if exact_packaging:
        pool = exact_packaging
    if parsed.mint_mark:
        marked = [i for i in pool if i.mint_mark == parsed.mint_mark]
        if marked:
            pool = marked
        else:
            confidence -= FINISH_FALLBACK_PENALTY
    elif any(i.mint_mark for i in pool):
        # several mints, none named: attach to the most common one but never let it count
        confidence = min(confidence, MISSING_MINT_MARK_CAP)
    best = max(pool, key=lambda i: i.mintage or 0)
    return best, confidence
