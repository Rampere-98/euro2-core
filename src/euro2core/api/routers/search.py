from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.deps import LangDep, SessionDep
from euro2core.api.routers.types import summaries_for
from euro2core.api.schemas import Page, TypeSummary
from euro2core.domain.models import CoinType, TextTranslation

router = APIRouter(tags=["catalog"])


@router.get("/search", response_model=Page[TypeSummary])
async def search(
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = SessionDep,
    lang: str = LangDep,
) -> Page[TypeSummary]:
    """Accent- and case-insensitive substring search over titles and descriptions."""
    pattern = f"%{q}%"
    matches = (
        select(TextTranslation.entity_id)
        .where(
            TextTranslation.entity == "coin_type",
            func.unaccent(TextTranslation.text).ilike(func.unaccent(pattern)),
        )
        .distinct()
        .subquery()
    )
    base = select(CoinType).where(CoinType.id.in_(select(matches.c.entity_id)))
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await session.scalars(
            base.order_by(CoinType.year.desc(), CoinType.country_code).limit(limit).offset(offset)
        )
    ).all()
    return Page(
        items=await summaries_for(session, list(rows), lang),
        total=total,
        limit=limit,
        offset=offset,
    )
