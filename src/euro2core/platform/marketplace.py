"""Listings, offers, trades and reputation between collectors."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import ListingStatus, OfferStatus, Plan, Role
from euro2core.domain.models import CollectionItem, Listing, Notification, Offer, Rating, User
from euro2core.platform.portfolio import transfer_item

FREE_ACTIVE_LISTINGS = 3


class MarketError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


async def create_listing(
    session: AsyncSession,
    seller: User,
    *,
    item_id: uuid.UUID,
    price: Decimal | None,
    accepts_trades: bool,
    description: str | None,
) -> Listing:
    item = await session.get(CollectionItem, item_id)
    if item is None or item.user_id != seller.id:
        raise MarketError("item not found in your collection", 404)
    if item.verified_at is None:
        raise MarketError("verify the piece with a photo before listing it", 409)
    if price is None and not accepts_trades:
        raise MarketError("a listing needs a price, trades, or both", 422)
    already = await session.scalar(
        select(func.count())
        .select_from(Listing)
        .where(Listing.item_id == item_id, Listing.status == ListingStatus.ACTIVE)
    )
    if already:
        raise MarketError("this piece is already listed", 409)
    if seller.plan == Plan.FREE and seller.role != Role.ADMIN:
        active = await session.scalar(
            select(func.count())
            .select_from(Listing)
            .where(Listing.seller_id == seller.id, Listing.status == ListingStatus.ACTIVE)
        )
        if active >= FREE_ACTIVE_LISTINGS:
            raise MarketError(
                f"free plan allows {FREE_ACTIVE_LISTINGS} active listings; upgrade to Pro", 402
            )
    listing = Listing(
        seller_id=seller.id,
        item_id=item_id,
        price=price,
        accepts_trades=accepts_trades,
        description=description,
    )
    session.add(listing)
    await session.flush()
    return listing


async def withdraw_listing(session: AsyncSession, seller: User, listing_id: uuid.UUID) -> Listing:
    listing = await session.get(Listing, listing_id)
    if listing is None or listing.seller_id != seller.id:
        raise MarketError("listing not found", 404)
    if listing.status != ListingStatus.ACTIVE:
        raise MarketError("listing is not active", 409)
    listing.status = ListingStatus.WITHDRAWN
    for offer in await _pending_offers(session, listing.id):
        offer.status = OfferStatus.REJECTED
        offer.decided_at = datetime.now(UTC)
    await session.flush()
    return listing


async def make_offer(
    session: AsyncSession,
    buyer: User,
    *,
    listing_id: uuid.UUID,
    amount: Decimal | None,
    offered_item_ids: list[uuid.UUID],
    message: str | None,
) -> Offer:
    listing = await session.get(Listing, listing_id)
    if listing is None or listing.status != ListingStatus.ACTIVE:
        raise MarketError("listing not available", 404)
    if listing.seller_id == buyer.id:
        raise MarketError("you cannot bid on your own listing", 409)
    if amount is None and not offered_item_ids:
        raise MarketError("offer money, pieces, or both", 422)
    if offered_item_ids and not listing.accepts_trades:
        raise MarketError("this listing does not accept trades", 409)
    for item_id in offered_item_ids:
        item = await session.get(CollectionItem, item_id)
        if item is None or item.user_id != buyer.id:
            raise MarketError("offered piece not found in your collection", 404)
        if item.verified_at is None:
            raise MarketError("offered pieces must be verified", 409)
    offer = Offer(
        listing_id=listing.id,
        buyer_id=buyer.id,
        amount=amount,
        offered_item_ids=[str(i) for i in offered_item_ids],
        message=message,
    )
    session.add(offer)
    await session.flush()
    session.add(
        Notification(
            user_id=listing.seller_id,
            kind="offer_received",
            title="Nueva oferta por tu moneda",
            body="New offer on your listing",
            payload={"listing_id": str(listing.id), "offer_id": str(offer.id)},
        )
    )
    await session.flush()
    return offer


async def decide_offer(
    session: AsyncSession, seller: User, offer_id: uuid.UUID, *, accept: bool
) -> Offer:
    offer = await session.get(Offer, offer_id)
    if offer is None:
        raise MarketError("offer not found", 404)
    listing = await session.get(Listing, offer.listing_id)
    if listing.seller_id != seller.id:
        raise MarketError("offer not found", 404)
    if offer.status != OfferStatus.PENDING or listing.status != ListingStatus.ACTIVE:
        raise MarketError("offer is no longer pending", 409)
    offer.decided_at = datetime.now(UTC)
    if not accept:
        offer.status = OfferStatus.REJECTED
        await session.flush()
        return offer
    buyer = await session.get(User, offer.buyer_id)
    item = await session.get(CollectionItem, listing.item_id)
    details = {"listing_id": str(listing.id), "offer_id": str(offer.id)}
    await transfer_item(
        session,
        item,
        to_user=buyer,
        kind="trade" if offer.offered_item_ids else "sale",
        price=offer.amount,
        details=details,
    )
    for offered_id in offer.offered_item_ids:
        offered = await session.get(CollectionItem, uuid.UUID(offered_id))
        if offered is not None and offered.user_id == buyer.id:
            await transfer_item(
                session, offered, to_user=seller, kind="trade", price=None, details=details
            )
    offer.status = OfferStatus.ACCEPTED
    listing.status = ListingStatus.SOLD
    for other in await _pending_offers(session, listing.id):
        if other.id != offer.id:
            other.status = OfferStatus.REJECTED
            other.decided_at = datetime.now(UTC)
    session.add(
        Notification(
            user_id=buyer.id,
            kind="offer_accepted",
            title="Oferta aceptada: la moneda ya es tuya",
            body="Offer accepted: the piece is now in your collection",
            payload=details,
        )
    )
    await session.flush()
    return offer


async def rate_counterparty(
    session: AsyncSession, rater: User, offer_id: uuid.UUID, *, stars: int, comment: str | None
) -> Rating:
    offer = await session.get(Offer, offer_id)
    if offer is None or offer.status != OfferStatus.ACCEPTED:
        raise MarketError("only completed transactions can be rated", 409)
    listing = await session.get(Listing, offer.listing_id)
    parties = {listing.seller_id, offer.buyer_id}
    if rater.id not in parties:
        raise MarketError("you were not part of this transaction", 403)
    rated_id = next(p for p in parties if p != rater.id)
    if await session.scalar(
        select(Rating.id).where(Rating.offer_id == offer.id, Rating.rater_id == rater.id)
    ):
        raise MarketError("already rated", 409)
    rating = Rating(
        offer_id=offer.id, rater_id=rater.id, rated_id=rated_id, stars=stars, comment=comment
    )
    session.add(rating)
    await session.flush()
    return rating


async def reputation(session: AsyncSession, user_id: uuid.UUID) -> dict:
    stars, count = (
        await session.execute(
            select(func.avg(Rating.stars), func.count()).where(Rating.rated_id == user_id)
        )
    ).one()
    completed = await session.scalar(
        select(func.count())
        .select_from(Offer)
        .join(Listing, Listing.id == Offer.listing_id)
        .where(
            Offer.status == OfferStatus.ACCEPTED,
            (Listing.seller_id == user_id) | (Offer.buyer_id == user_id),
        )
    )
    return {
        "average_stars": round(float(stars), 2) if stars is not None else None,
        "ratings": count,
        "completed_transactions": completed,
    }


async def _pending_offers(session: AsyncSession, listing_id: uuid.UUID) -> list[Offer]:
    return list(
        (
            await session.scalars(
                select(Offer).where(
                    Offer.listing_id == listing_id, Offer.status == OfferStatus.PENDING
                )
            )
        ).all()
    )
