import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.deps import LangDep, SessionDep
from euro2core.api.queries import facts_for, images_for_issue
from euro2core.api.routers.types import summaries_for
from euro2core.api.schemas import EstimateOut, IssueDetail, ObservationOut, Page, RarityOut
from euro2core.domain.models import (
    CoinIssue,
    CoinType,
    MarketObservation,
    PriceEstimate,
    RarityScore,
)

router = APIRouter(prefix="/issues", tags=["catalog"])


@router.get("/{issue_id}", response_model=IssueDetail)
async def get_issue(
    issue_id: uuid.UUID, session: AsyncSession = SessionDep, lang: str = LangDep
) -> IssueDetail:
    issue = await session.get(CoinIssue, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="issue not found")
    coin_type = await session.get(CoinType, issue.type_id)
    estimates = (
        await session.scalars(
            select(PriceEstimate)
            .where(PriceEstimate.issue_id == issue_id)
            .order_by(PriceEstimate.region, PriceEstimate.grade)
        )
    ).all()
    rarity = (
        await session.scalars(select(RarityScore).where(RarityScore.issue_id == issue_id))
    ).first()
    return IssueDetail(
        id=issue.id,
        year=issue.year,
        mint_mark=issue.mint_mark,
        finish=issue.finish.value,
        packaging=issue.packaging.value,
        mintage=issue.mintage,
        numista_issue_id=issue.numista_issue_id,
        type=(await summaries_for(session, [coin_type], lang))[0],
        facts=await facts_for(session, "coin_issue", issue_id),
        estimates=[EstimateOut.model_validate(e) for e in estimates],
        rarity=RarityOut.model_validate(rarity) if rarity else None,
        images=await images_for_issue(session, issue_id),
    )


@router.get("/{issue_id}/observations", response_model=Page[ObservationOut])
async def list_observations(
    issue_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = SessionDep,
) -> Page[ObservationOut]:
    if await session.get(CoinIssue, issue_id) is None:
        raise HTTPException(status_code=404, detail="issue not found")
    base = select(MarketObservation).where(MarketObservation.issue_id == issue_id)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await session.scalars(
            base.order_by(MarketObservation.observed_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return Page(
        items=[ObservationOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
