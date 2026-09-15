import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.deps import LangDep, SessionDep
from euro2core.api.queries import (
    facts_for,
    images_for_types,
    languages_for,
    summaries_for,
    translations_for,
    type_value_subquery,
)
from euro2core.api.schemas import IssueSummary, Page, TypeDetail, TypeSummary
from euro2core.domain.enums import CoinKind
from euro2core.domain.models import CoinIssue, CoinType

router = APIRouter(prefix="/types", tags=["catalog"])


@router.get("", response_model=Page[TypeSummary])
async def list_types(
    country: str | None = Query(default=None, min_length=2, max_length=2),
    year: int | None = None,
    kind: CoinKind | None = None,
    category: str | None = Query(
        default=None,
        pattern="^(plain|joint|edition)$",
        description="plain: national commemoratives; joint: euro-area joint issues; "
        "edition: coloured/hologram editions and other derived designs",
    ),
    min_value: Annotated[Decimal | None, Query(ge=0)] = None,
    max_value: Annotated[Decimal | None, Query(ge=0)] = None,
    sort: str = Query(default="year_desc", pattern="^(year_desc|year_asc|value_desc|value_asc)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = SessionDep,
    lang: str = LangDep,
) -> Page[TypeSummary]:
    values = type_value_subquery()
    stmt = select(CoinType).outerjoin(values, values.c.type_id == CoinType.id)
    # a coin passes a price filter when its value range overlaps the requested one
    if min_value is not None:
        stmt = stmt.where(values.c.high >= min_value)
    if max_value is not None:
        stmt = stmt.where(values.c.low <= max_value)
    if country:
        stmt = stmt.where(CoinType.country_code == country.upper())
    if year:
        stmt = stmt.where(CoinType.year == year)
    if kind:
        stmt = stmt.where(CoinType.kind == kind)
    if category == "joint":
        stmt = stmt.where(CoinType.joint_issue_group.is_not(None))
    elif category == "edition":
        stmt = stmt.where(CoinType.base_type_id.is_not(None), CoinType.kind != CoinKind.ERROR)
    elif category == "plain":
        stmt = stmt.where(
            CoinType.kind == CoinKind.COMMEMORATIVE,
            CoinType.joint_issue_group.is_(None),
            CoinType.base_type_id.is_(None),
        )
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    order = {
        "year_desc": (CoinType.year.desc(), CoinType.country_code),
        "year_asc": (CoinType.year.asc(), CoinType.country_code),
        "value_desc": (values.c.high.desc().nulls_last(), CoinType.year.desc()),
        "value_asc": (values.c.low.asc().nulls_last(), CoinType.year.desc()),
    }[sort]
    rows = (await session.scalars(stmt.order_by(*order).limit(limit).offset(offset))).all()
    return Page(
        items=await summaries_for(session, list(rows), lang),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{type_id}", response_model=TypeDetail)
async def get_type(
    type_id: uuid.UUID, session: AsyncSession = SessionDep, lang: str = LangDep
) -> TypeDetail:
    coin_type = await session.get(CoinType, type_id)
    if coin_type is None:
        raise HTTPException(status_code=404, detail="type not found")
    summary = (await summaries_for(session, [coin_type], lang))[0]
    texts = (await translations_for(session, "coin_type", [type_id], lang)).get(type_id, {})
    facts = await facts_for(session, "coin_type", type_id)
    issues = (
        await session.scalars(
            select(CoinIssue)
            .where(CoinIssue.type_id == type_id)
            .order_by(CoinIssue.year, CoinIssue.mint_mark, CoinIssue.finish, CoinIssue.packaging)
        )
    ).all()
    images = (await images_for_types(session, [type_id])).get(type_id, [])
    return TypeDetail(
        **summary.model_dump(),
        description=texts.get("description"),
        composition=_fact_value(facts, "composition"),
        series=_fact_value(facts, "series"),
        topic=_fact_value(facts, "topic"),
        km_reference=_fact_value(facts, "km_reference"),
        verification_status=coin_type.verification_status.value
        if coin_type.verification_status
        else None,
        facts=facts,
        issues=[IssueSummary.model_validate(i) for i in issues],
        images=images,
        available_languages=await languages_for(session, "coin_type", type_id),
    )


def _fact_value(facts: dict, field: str):
    fact = facts.get(field)
    return fact.value if fact else None
