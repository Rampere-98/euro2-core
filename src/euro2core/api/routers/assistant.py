"""Market assistant: what a coin really sells for, deals, movers, buy/sell advice, watchlist."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.auth_deps import CurrentUser
from euro2core.api.deps import LangDep, SessionDep
from euro2core.api.queries import summaries_for
from euro2core.api.routers.marketplace import ListingOut
from euro2core.api.routers.marketplace import _render as render_peers
from euro2core.api.schemas import TypeSummary
from euro2core.domain.enums import Grade
from euro2core.domain.models import CoinIssue, CoinType, CollectionItem, WatchItem
from euro2core.platform import market_assistant as ma
from euro2core.pricing.market_intel import Listing, RangeStats, sell_advice

router = APIRouter(tags=["assistant"])


class RangeOut(BaseModel):
    n: int
    min: Decimal
    p25: Decimal
    median: Decimal
    p75: Decimal
    max: Decimal
    window_days: int


class BandOut(BaseModel):
    low: Decimal
    high: Decimal
    basis: str


class OfferOut(BaseModel):
    listing_id: str
    kind: str
    price: Decimal
    marketplace: str
    url: str
    title: str
    observed_at: datetime
    ends_at: datetime | None
    reliability: float
    reasons: list[str]
    discount_pct: float


class IgnoredOut(BaseModel):
    listing_id: str
    price: Decimal
    title: str
    url: str
    reasons: list[str]


class BuyOut(BaseModel):
    verdict: str
    cheapest: OfferOut | None
    saving_pct: float


class MonthOut(BaseModel):
    month: str
    sold_n: int
    sold_min: Decimal | None
    sold_median: Decimal | None
    sold_max: Decimal | None
    ask_n: int
    ask_median: Decimal | None


class EstimatePointOut(BaseModel):
    at: datetime
    grade: str
    basis: str
    median: Decimal
    p25: Decimal | None
    p75: Decimal | None
    n_obs: int


class TypeMarketOut(BaseModel):
    realized: RangeOut | None
    asking: RangeOut | None
    band: BandOut
    trend_pct: float | None
    sales_per_month: float
    expected_days_to_sell: int | None
    best_marketplace: str | None
    buy: BuyOut
    offers: list[OfferOut]
    ignored: list[IgnoredOut]
    history: list[MonthOut]
    estimate_history: list[EstimatePointOut]
    peers: list[ListingOut]


class SellOut(BaseModel):
    start: Decimal
    floor: Decimal
    grade: str
    expected_days: int | None
    best_marketplace: str | None
    net_ebay: Decimal
    net_euro2: Decimal
    hold: bool
    band: BandOut
    trend_pct: float | None
    realized: RangeOut | None


class DealOut(BaseModel):
    type: TypeSummary
    listing: OfferOut
    band: BandOut
    rank: float


class MoverOut(BaseModel):
    type: TypeSummary
    trend_pct: float
    median: Decimal
    n: int


class WatchIn(BaseModel):
    type_id: uuid.UUID


class WatchOut(BaseModel):
    id: uuid.UUID
    type: TypeSummary
    buy: BuyOut
    band: BandOut
    trend_pct: float | None


def _range(r: RangeStats | None) -> RangeOut | None:
    return RangeOut(**r.__dict__) if r else None


def _offer(x: Listing, reliability: float, reasons: list[str], discount: float) -> OfferOut:
    return OfferOut(
        listing_id=x.listing_id,
        kind=x.kind.value,
        price=x.price,
        marketplace=x.marketplace,
        url=x.url,
        title=x.title,
        observed_at=x.observed_at,
        ends_at=x.ends_at,
        reliability=reliability,
        reasons=reasons,
        discount_pct=discount,
    )


def _buy(market: ma.TypeMarket) -> BuyOut:
    b = market.buy
    cheapest = None
    if b.cheapest is not None:
        scored = next(o for o in market.snapshot.offers if o.listing is b.cheapest)
        cheapest = _offer(
            b.cheapest,
            scored.reliability.score,
            scored.reliability.reasons,
            ma.deal_discount(b.cheapest.price, market.snapshot.band),
        )
    return BuyOut(verdict=b.verdict, cheapest=cheapest, saving_pct=b.saving_pct)


async def _market_out(session: AsyncSession, market: ma.TypeMarket, lang: str) -> TypeMarketOut:
    s = market.snapshot
    return TypeMarketOut(
        realized=_range(s.realized),
        asking=_range(s.asking),
        band=BandOut(**s.band.__dict__),
        trend_pct=s.trend_pct,
        sales_per_month=s.sales_per_month,
        expected_days_to_sell=s.expected_days_to_sell,
        best_marketplace=s.best_marketplace,
        buy=_buy(market),
        offers=[
            _offer(
                o.listing,
                o.reliability.score,
                o.reliability.reasons,
                ma.deal_discount(o.listing.price, s.band),
            )
            for o in s.offers
        ],
        ignored=[
            IgnoredOut(
                listing_id=x.listing_id,
                price=x.price,
                title=x.title,
                url=x.url,
                reasons=s.ignored_reasons.get(x.listing_id, []),
            )
            for x in s.ignored
        ],
        history=[MonthOut(**p.__dict__) for p in market.history],
        estimate_history=[
            EstimatePointOut(
                at=e.computed_at,
                grade=e.grade.value,
                basis=e.basis,
                median=e.median,
                p25=e.p25,
                p75=e.p75,
                n_obs=e.n_obs,
            )
            for e in market.estimate_history
        ],
        peers=await render_peers(session, market.peers, lang),
    )


@router.get("/types/{type_id}/market", response_model=TypeMarketOut)
async def type_market(
    type_id: uuid.UUID, session: AsyncSession = SessionDep, lang: str = LangDep
) -> TypeMarketOut:
    coin_type = await session.get(CoinType, type_id)
    if coin_type is None:
        raise HTTPException(status_code=404, detail="type not found")
    return await _market_out(session, await ma.market_for_type(session, coin_type), lang)


@router.get("/market/deals", response_model=list[DealOut])
async def market_deals(
    limit: int = Query(default=30, ge=1, le=100),
    session: AsyncSession = SessionDep,
    lang: str = LangDep,
) -> list[DealOut]:
    found = await ma.deals(session, limit=limit)
    summaries = {s.id: s for s in await summaries_for(session, [d.coin_type for d in found], lang)}
    return [
        DealOut(
            type=summaries[d.coin_type.id],
            listing=_offer(d.listing, d.reliability, [], d.discount_pct),
            band=BandOut(low=d.band_low, high=d.band_high, basis=d.basis),
            rank=d.rank,
        )
        for d in found
    ]


@router.get("/market/movers", response_model=list[MoverOut])
async def market_movers(
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = SessionDep,
    lang: str = LangDep,
) -> list[MoverOut]:
    found = await ma.movers(session, limit=limit)
    summaries = {s.id: s for s in await summaries_for(session, [m.coin_type for m in found], lang)}
    return [
        MoverOut(type=summaries[m.coin_type.id], trend_pct=m.trend_pct, median=m.median, n=m.n)
        for m in found
    ]


@router.get("/me/collection/{item_id}/sell-advice", response_model=SellOut)
async def item_sell_advice(
    item_id: uuid.UUID, user: CurrentUser, session: AsyncSession = SessionDep
) -> SellOut:
    item = await session.get(CollectionItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="item not found")
    issue = await session.get(CoinIssue, item.issue_id)
    coin_type = await session.get(CoinType, issue.type_id)
    market = await ma.market_for_type(session, coin_type)
    advice = sell_advice(market.snapshot, grade=Grade(item.grade))
    return SellOut(
        start=advice.start,
        floor=advice.floor,
        grade=advice.grade.value,
        expected_days=advice.expected_days,
        best_marketplace=advice.best_marketplace,
        net_ebay=advice.net_ebay,
        net_euro2=advice.net_euro2,
        hold=advice.hold,
        band=BandOut(**advice.band.__dict__),
        trend_pct=advice.trend_pct,
        realized=_range(market.snapshot.realized),
    )


@router.get("/me/watchlist", response_model=list[WatchOut])
async def my_watchlist(
    user: CurrentUser, session: AsyncSession = SessionDep, lang: str = LangDep
) -> list[WatchOut]:
    rows = (
        await session.scalars(
            select(WatchItem).where(WatchItem.user_id == user.id).order_by(WatchItem.created_at)
        )
    ).all()
    types = {
        t.id: t
        for t in (
            await session.scalars(
                select(CoinType).where(CoinType.id.in_({w.type_id for w in rows}))
            )
        ).all()
    }
    summaries = {s.id: s for s in await summaries_for(session, list(types.values()), lang)}
    out = []
    for w in rows:
        market = await ma.market_for_type(session, types[w.type_id])
        out.append(
            WatchOut(
                id=w.id,
                type=summaries[w.type_id],
                buy=_buy(market),
                band=BandOut(**market.snapshot.band.__dict__),
                trend_pct=market.snapshot.trend_pct,
            )
        )
    return out


@router.post("/me/watchlist", status_code=201)
async def watch(
    body: WatchIn, user: CurrentUser, session: AsyncSession = SessionDep
) -> dict[str, Any]:
    if await session.get(CoinType, body.type_id) is None:
        raise HTTPException(status_code=404, detail="type not found")
    existing = await session.scalar(
        select(WatchItem).where(WatchItem.user_id == user.id, WatchItem.type_id == body.type_id)
    )
    if existing is None:
        existing = WatchItem(user_id=user.id, type_id=body.type_id)
        session.add(existing)
        await session.commit()
    return {"id": str(existing.id), "type_id": str(body.type_id)}


@router.delete("/me/watchlist/{type_id}", status_code=204)
async def unwatch(
    type_id: uuid.UUID, user: CurrentUser, session: AsyncSession = SessionDep
) -> None:
    row = await session.scalar(
        select(WatchItem).where(WatchItem.user_id == user.id, WatchItem.type_id == type_id)
    )
    if row is not None:
        await session.delete(row)
        await session.commit()
