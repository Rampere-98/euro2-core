import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.auth_deps import CurrentUser
from euro2core.api.deps import LangDep, SessionDep
from euro2core.api.queries import summaries_for
from euro2core.api.schemas import IssueSummary, TypeSummary
from euro2core.domain.enums import Grade
from euro2core.domain.models import (
    CoinIssue,
    CoinType,
    CollectionItem,
    Notification,
    PieceEvent,
    PriceAlert,
)
from euro2core.platform import achievements as ach
from euro2core.platform.portfolio import (
    PortfolioError,
    add_item,
    history,
    list_items,
    net_worth,
    remove_item,
)
from euro2core.platform.provenance import certificate_for
from euro2core.vision.embedder import get_embedder
from euro2core.vision.identify import identify

router = APIRouter(tags=["portfolio"])


class ItemIn(BaseModel):
    issue_id: uuid.UUID
    grade: Grade = Grade.UNKNOWN
    sheldon: int | None = Field(default=None, ge=1, le=70)
    acquired_price: Decimal | None = Field(default=None, ge=0)
    acquired_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)
    # What you paid feeds the app's own market data unless you opt out (Ajustes → Privacidad)
    share_price: bool = True


class ValuationOut(BaseModel):
    value: Decimal
    basis: str
    grade: Grade | None
    n_obs: int
    confidence: str


class ItemOut(BaseModel):
    id: uuid.UUID
    issue: IssueSummary
    type: TypeSummary
    grade: Grade
    sheldon: int | None
    acquired_price: Decimal | None
    acquired_at: datetime | None
    notes: str | None
    verified_at: datetime | None
    valuation: ValuationOut


class CollectionOut(BaseModel):
    items: list[ItemOut]
    net_worth: dict[str, Any]


class AchievementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    earned_at: datetime
    details: dict[str, Any] | None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    from_user_id: uuid.UUID | None
    to_user_id: uuid.UUID | None
    price: Decimal | None
    details: dict[str, Any] | None
    at: datetime


class AlertIn(BaseModel):
    issue_id: uuid.UUID
    direction: str = Field(pattern="^(above|below)$")
    threshold: Decimal = Field(gt=0)


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    issue_id: uuid.UUID
    direction: str
    threshold: Decimal
    active: bool


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    body: str | None
    payload: dict[str, Any] | None
    read_at: datetime | None
    created_at: datetime


async def _render(session: AsyncSession, valued, lang: str) -> list[ItemOut]:
    issue_ids = {v.item.issue_id for v in valued}
    issues = {
        i.id: i
        for i in (await session.scalars(select(CoinIssue).where(CoinIssue.id.in_(issue_ids)))).all()
    }
    types = {
        t.id: t
        for t in (
            await session.scalars(
                select(CoinType).where(CoinType.id.in_({i.type_id for i in issues.values()}))
            )
        ).all()
    }
    summaries = {s.id: s for s in await summaries_for(session, list(types.values()), lang)}
    return [
        ItemOut(
            id=v.item.id,
            issue=IssueSummary.model_validate(issues[v.item.issue_id]),
            type=summaries[issues[v.item.issue_id].type_id],
            grade=v.item.grade,
            sheldon=v.item.sheldon,
            acquired_price=v.item.acquired_price,
            acquired_at=v.item.acquired_at,
            notes=v.item.notes,
            verified_at=v.item.verified_at,
            valuation=ValuationOut(**v.valuation.__dict__),
        )
        for v in valued
    ]


@router.get("/me/collection", response_model=CollectionOut)
async def my_collection(
    user: CurrentUser, session: AsyncSession = SessionDep, lang: str = LangDep
) -> CollectionOut:
    valued = await list_items(session, user.id)
    return CollectionOut(items=await _render(session, valued, lang), net_worth=net_worth(valued))


@router.post("/me/collection", response_model=ItemOut, status_code=201)
async def add_to_collection(
    body: ItemIn, user: CurrentUser, session: AsyncSession = SessionDep, lang: str = LangDep
) -> ItemOut:
    try:
        item = await add_item(session, user, **body.model_dump())
    except PortfolioError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await ach.evaluate(session, user.id)
    await session.commit()
    valued = [v for v in await list_items(session, user.id) if v.item.id == item.id]
    return (await _render(session, valued, lang))[0]


@router.delete("/me/collection/{item_id}", status_code=204)
async def delete_from_collection(
    item_id: uuid.UUID, user: CurrentUser, session: AsyncSession = SessionDep
) -> None:
    if not await remove_item(session, user, item_id):
        raise HTTPException(status_code=404, detail="item not found")
    await session.commit()


@router.get("/me/collection/{item_id}/history", response_model=list[EventOut])
async def item_history(
    item_id: uuid.UUID, user: CurrentUser, session: AsyncSession = SessionDep
) -> list[EventOut]:
    item = await session.get(CollectionItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="item not found")
    return [EventOut.model_validate(e) for e in await history(session, item_id)]


@router.get("/me/collection/{item_id}/certificate")
async def item_certificate(
    item_id: uuid.UUID, user: CurrentUser, session: AsyncSession = SessionDep
) -> dict[str, Any]:
    item = await session.get(CollectionItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="item not found")
    return await certificate_for(session, item)


@router.post("/me/collection/{item_id}/verify", response_model=ItemOut)
async def verify_piece(
    item_id: uuid.UUID,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
    session: AsyncSession = SessionDep,
    lang: str = LangDep,
) -> ItemOut:
    """Photograph the piece: if the identification agrees with the registered coin with high
    confidence, the piece becomes verified (required to list it on the marketplace)."""
    item = await session.get(CollectionItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="item not found")
    issue = await session.get(CoinIssue, item.issue_id)
    try:
        result = await identify(session, await file.read(), get_embedder(), user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    top = result.candidates[0] if result.candidates else None
    if top is None or top.type_id != issue.type_id or top.confidence != "high":
        await session.commit()
        raise HTTPException(
            status_code=409,
            detail="the photo does not match the registered coin with high confidence",
        )
    item.verified_at = datetime.now(UTC)
    item.verification_id = result.identification_id
    session.add(
        PieceEvent(
            item_id=item.id,
            kind="verified",
            to_user_id=user.id,
            details={"identification_id": str(result.identification_id), "score": top.score},
        )
    )
    await ach.evaluate(session, user.id)
    await session.commit()
    valued = [v for v in await list_items(session, user.id) if v.item.id == item.id]
    return (await _render(session, valued, lang))[0]


@router.get("/me/achievements", response_model=list[AchievementOut])
async def my_achievements(user: CurrentUser, session: AsyncSession = SessionDep):
    from euro2core.domain.models import UserAchievement

    rows = (
        await session.scalars(
            select(UserAchievement)
            .where(UserAchievement.user_id == user.id)
            .order_by(UserAchievement.earned_at.desc())
        )
    ).all()
    return [AchievementOut.model_validate(r) for r in rows]


@router.get("/leaderboard")
async def leaderboard(session: AsyncSession = SessionDep) -> list[dict[str, Any]]:
    return await ach.leaderboard(session)


@router.get("/me/alerts", response_model=list[AlertOut])
async def my_alerts(user: CurrentUser, session: AsyncSession = SessionDep):
    rows = (await session.scalars(select(PriceAlert).where(PriceAlert.user_id == user.id))).all()
    return [AlertOut.model_validate(r) for r in rows]


@router.post("/me/alerts", response_model=AlertOut, status_code=201)
async def create_alert(body: AlertIn, user: CurrentUser, session: AsyncSession = SessionDep):
    if await session.get(CoinIssue, body.issue_id) is None:
        raise HTTPException(status_code=404, detail="issue not found")
    alert = PriceAlert(user_id=user.id, **body.model_dump())
    session.add(alert)
    await session.commit()
    return AlertOut.model_validate(alert)


@router.delete("/me/alerts/{alert_id}", status_code=204)
async def delete_alert(alert_id: uuid.UUID, user: CurrentUser, session: AsyncSession = SessionDep):
    alert = await session.get(PriceAlert, alert_id)
    if alert is None or alert.user_id != user.id:
        raise HTTPException(status_code=404, detail="alert not found")
    await session.delete(alert)
    await session.commit()


@router.get("/me/notifications", response_model=list[NotificationOut])
async def my_notifications(user: CurrentUser, session: AsyncSession = SessionDep):
    rows = (
        await session.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc())
            .limit(100)
        )
    ).all()
    return [NotificationOut.model_validate(r) for r in rows]


@router.post("/me/notifications/read", status_code=204)
async def mark_read(user: CurrentUser, session: AsyncSession = SessionDep) -> None:
    rows = (
        await session.scalars(
            select(Notification).where(
                Notification.user_id == user.id, Notification.read_at.is_(None)
            )
        )
    ).all()
    now = datetime.now(UTC)
    for r in rows:
        r.read_at = now
    await session.commit()
