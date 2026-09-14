import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.auth_deps import CurrentUser
from euro2core.api.deps import LangDep, SessionDep
from euro2core.api.queries import summaries_for
from euro2core.api.schemas import IssueSummary, Page, TypeSummary
from euro2core.domain.enums import ListingStatus, OfferStatus
from euro2core.domain.models import CoinIssue, CoinType, CollectionItem, Listing, Offer, User
from euro2core.platform.marketplace import (
    MarketError,
    create_listing,
    decide_offer,
    make_offer,
    rate_counterparty,
    reputation,
    withdraw_listing,
)
from euro2core.platform.provenance import verify_certificate

router = APIRouter(tags=["marketplace"])


class ListingIn(BaseModel):
    item_id: uuid.UUID
    price: Decimal | None = Field(default=None, gt=0)
    accepts_trades: bool = True
    description: str | None = Field(default=None, max_length=4000)


class SellerOut(BaseModel):
    id: uuid.UUID
    display_name: str
    country_code: str | None
    reputation: dict[str, Any]


class ListingOut(BaseModel):
    id: uuid.UUID
    status: ListingStatus
    price: Decimal | None
    accepts_trades: bool
    description: str | None
    created_at: datetime
    seller: SellerOut
    item_id: uuid.UUID
    grade: str
    verified_at: datetime | None
    issue: IssueSummary
    type: TypeSummary


class OfferIn(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0)
    offered_item_ids: list[uuid.UUID] = []
    message: str | None = Field(default=None, max_length=2000)


class OfferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    listing_id: uuid.UUID
    buyer_id: uuid.UUID
    amount: Decimal | None
    offered_item_ids: list[str]
    message: str | None
    status: OfferStatus
    created_at: datetime
    decided_at: datetime | None


class RatingIn(BaseModel):
    stars: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class CertificateCheckIn(BaseModel):
    digest: str
    signature: str


def _raise(exc: MarketError) -> None:
    raise HTTPException(status_code=exc.status, detail=str(exc))


async def _render(session: AsyncSession, listings: list[Listing], lang: str) -> list[ListingOut]:
    if not listings:
        return []
    items = {
        i.id: i
        for i in (
            await session.scalars(
                select(CollectionItem).where(CollectionItem.id.in_({x.item_id for x in listings}))
            )
        ).all()
    }
    issues = {
        i.id: i
        for i in (
            await session.scalars(
                select(CoinIssue).where(CoinIssue.id.in_({it.issue_id for it in items.values()}))
            )
        ).all()
    }
    types = (
        await session.scalars(
            select(CoinType).where(CoinType.id.in_({i.type_id for i in issues.values()}))
        )
    ).all()
    summaries = {s.id: s for s in await summaries_for(session, list(types), lang)}
    sellers = {
        u.id: u
        for u in (
            await session.scalars(select(User).where(User.id.in_({x.seller_id for x in listings})))
        ).all()
    }
    reps = {uid: await reputation(session, uid) for uid in sellers}
    out = []
    for x in listings:
        item = items[x.item_id]
        issue = issues[item.issue_id]
        seller = sellers[x.seller_id]
        out.append(
            ListingOut(
                id=x.id,
                status=x.status,
                price=x.price,
                accepts_trades=x.accepts_trades,
                description=x.description,
                created_at=x.created_at,
                seller=SellerOut(
                    id=seller.id,
                    display_name=seller.display_name,
                    country_code=seller.country_code,
                    reputation=reps[seller.id],
                ),
                item_id=item.id,
                grade=item.grade.value,
                verified_at=item.verified_at,
                issue=IssueSummary.model_validate(issue),
                type=summaries[issue.type_id],
            )
        )
    return out


@router.get("/market/listings", response_model=Page[ListingOut])
async def browse_listings(
    country: str | None = None,
    year: int | None = None,
    max_price: Decimal | None = None,
    trades_only: bool = False,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = SessionDep,
    lang: str = LangDep,
) -> Page[ListingOut]:
    stmt = (
        select(Listing)
        .join(CollectionItem, CollectionItem.id == Listing.item_id)
        .join(CoinIssue, CoinIssue.id == CollectionItem.issue_id)
        .join(CoinType, CoinType.id == CoinIssue.type_id)
        .where(Listing.status == ListingStatus.ACTIVE)
    )
    if country:
        stmt = stmt.where(CoinType.country_code == country.upper())
    if year:
        stmt = stmt.where(CoinIssue.year == year)
    if max_price is not None:
        stmt = stmt.where(Listing.price <= max_price)
    if trades_only:
        stmt = stmt.where(Listing.accepts_trades.is_(True))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.scalars(stmt.order_by(Listing.created_at.desc()).limit(limit).offset(offset))
    ).all()
    return Page(
        items=await _render(session, list(rows), lang), total=total, limit=limit, offset=offset
    )


@router.get("/market/listings/{listing_id}", response_model=ListingOut)
async def get_listing(
    listing_id: uuid.UUID, session: AsyncSession = SessionDep, lang: str = LangDep
) -> ListingOut:
    listing = await session.get(Listing, listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="listing not found")
    return (await _render(session, [listing], lang))[0]


@router.post("/market/listings", response_model=ListingOut, status_code=201)
async def publish_listing(
    body: ListingIn, user: CurrentUser, session: AsyncSession = SessionDep, lang: str = LangDep
) -> ListingOut:
    try:
        listing = await create_listing(session, user, **body.model_dump())
    except MarketError as exc:
        _raise(exc)
    await session.commit()
    return (await _render(session, [listing], lang))[0]


@router.delete("/market/listings/{listing_id}", response_model=ListingOut)
async def withdraw(
    listing_id: uuid.UUID,
    user: CurrentUser,
    session: AsyncSession = SessionDep,
    lang: str = LangDep,
) -> ListingOut:
    try:
        listing = await withdraw_listing(session, user, listing_id)
    except MarketError as exc:
        _raise(exc)
    await session.commit()
    return (await _render(session, [listing], lang))[0]


@router.post("/market/listings/{listing_id}/offers", response_model=OfferOut, status_code=201)
async def offer(
    listing_id: uuid.UUID, body: OfferIn, user: CurrentUser, session: AsyncSession = SessionDep
) -> OfferOut:
    try:
        created = await make_offer(session, user, listing_id=listing_id, **body.model_dump())
    except MarketError as exc:
        _raise(exc)
    await session.commit()
    return OfferOut.model_validate(created)


@router.get("/market/listings/{listing_id}/offers", response_model=list[OfferOut])
async def listing_offers(
    listing_id: uuid.UUID, user: CurrentUser, session: AsyncSession = SessionDep
) -> list[OfferOut]:
    listing = await session.get(Listing, listing_id)
    if listing is None or listing.seller_id != user.id:
        raise HTTPException(status_code=404, detail="listing not found")
    rows = (
        await session.scalars(
            select(Offer).where(Offer.listing_id == listing_id).order_by(Offer.created_at.desc())
        )
    ).all()
    return [OfferOut.model_validate(o) for o in rows]


@router.get("/me/offers", response_model=list[OfferOut])
async def my_offers(user: CurrentUser, session: AsyncSession = SessionDep) -> list[OfferOut]:
    rows = (
        await session.scalars(
            select(Offer).where(Offer.buyer_id == user.id).order_by(Offer.created_at.desc())
        )
    ).all()
    return [OfferOut.model_validate(o) for o in rows]


@router.post("/market/offers/{offer_id}/accept", response_model=OfferOut)
async def accept(offer_id: uuid.UUID, user: CurrentUser, session: AsyncSession = SessionDep):
    try:
        decided = await decide_offer(session, user, offer_id, accept=True)
    except MarketError as exc:
        _raise(exc)
    await session.commit()
    return OfferOut.model_validate(decided)


@router.post("/market/offers/{offer_id}/reject", response_model=OfferOut)
async def reject(offer_id: uuid.UUID, user: CurrentUser, session: AsyncSession = SessionDep):
    try:
        decided = await decide_offer(session, user, offer_id, accept=False)
    except MarketError as exc:
        _raise(exc)
    await session.commit()
    return OfferOut.model_validate(decided)


@router.post("/market/offers/{offer_id}/rate", status_code=201)
async def rate(
    offer_id: uuid.UUID, body: RatingIn, user: CurrentUser, session: AsyncSession = SessionDep
) -> dict[str, Any]:
    try:
        rating = await rate_counterparty(session, user, offer_id, **body.model_dump())
    except MarketError as exc:
        _raise(exc)
    await session.commit()
    return {"id": str(rating.id), "stars": rating.stars, "rated_id": str(rating.rated_id)}


@router.get("/users/{user_id}/reputation")
async def user_reputation(user_id: uuid.UUID, session: AsyncSession = SessionDep) -> dict[str, Any]:
    if await session.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="user not found")
    return await reputation(session, user_id)


@router.post("/certificates/{item_id}/verify")
async def check_certificate(
    item_id: uuid.UUID, body: CertificateCheckIn, session: AsyncSession = SessionDep
) -> dict[str, Any]:
    """Anyone holding a certificate can check that it was issued here and that the provenance
    chain has not changed since."""
    item = await session.get(CollectionItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="piece not found")
    return await verify_certificate(session, item, body.digest, body.signature)
