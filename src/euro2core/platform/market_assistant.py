"""Database side of the market assistant: load observations for a coin, build the snapshot,
find deals and movers across the catalog, notify watchers."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import Grade, ListingStatus, ObservationKind
from euro2core.domain.models import (
    CoinIssue,
    CoinType,
    CollectionItem,
    EstimateHistory,
    MarketObservation,
    Notification,
    PriceEstimate,
    RarityScore,
    TextTranslation,
    WatchItem,
)
from euro2core.domain.models import (
    Listing as PeerListing,
)
from euro2core.platform.credentials import credentials
from euro2core.pricing.market_intel import (
    ASKING_KINDS,
    BuyAdvice,
    Listing,
    MonthPoint,
    Snapshot,
    buy_advice,
    deal_discount,
    monthly_history,
    snapshot,
)
from euro2core.pricing.recompute import CATALOG_BASIS

LOOKBACK_DAYS = 400
MOVE_NOTIFY_PCT = 20.0
RARITY_WEIGHT = {"common": 1.0, "uncommon": 1.1, "rare": 1.3, "very_rare": 1.6, "exceptional": 2.0}


def _listing(row: MarketObservation) -> Listing:
    return Listing(
        listing_id=f"{row.marketplace}:{row.listing_id}",
        kind=row.observation_kind,
        price=row.price,
        observed_at=row.observed_at,
        marketplace=row.marketplace,
        url=row.listing_url,
        title=row.title_raw,
        match_confidence=row.match_confidence,
        grade=row.grade,
        ends_at=row.ends_at,
    )


async def listings_for_type(
    session: AsyncSession, type_id: uuid.UUID, *, now: datetime
) -> list[Listing]:
    rows = (
        await session.scalars(
            select(MarketObservation)
            .join(CoinIssue, CoinIssue.id == MarketObservation.issue_id)
            .where(
                CoinIssue.type_id == type_id,
                MarketObservation.observed_at >= now - timedelta(days=LOOKBACK_DAYS),
            )
            .order_by(MarketObservation.observed_at.desc())
        )
    ).all()
    return [_listing(r) for r in rows]


async def model_band_for(
    session: AsyncSession, type_id: uuid.UUID
) -> tuple[Decimal, Decimal] | None:
    """Lowest mintage-model band among the type's variants (the loose coin most people hold)."""
    rows = (
        await session.execute(
            select(PriceEstimate.p25, PriceEstimate.p75)
            .join(CoinIssue, CoinIssue.id == PriceEstimate.issue_id)
            .where(CoinIssue.type_id == type_id, PriceEstimate.basis == "mintage_model")
            .order_by(PriceEstimate.p25)
        )
    ).all()
    if not rows:
        return None
    return rows[0][0], rows[0][1]


async def catalog_value(session: AsyncSession, type_id: uuid.UUID) -> Decimal | None:
    """Numista catalog value for the plain uncirculated coin, if any (fallback band)."""
    rows = (
        await session.execute(
            select(PriceEstimate.grade, PriceEstimate.median)
            .join(CoinIssue, CoinIssue.id == PriceEstimate.issue_id)
            .where(
                CoinIssue.type_id == type_id,
                PriceEstimate.basis == CATALOG_BASIS,
                PriceEstimate.region == "global",
                PriceEstimate.median.is_not(None),
            )
        )
    ).all()
    if not rows:
        return None
    preferred = [m for g, m in rows if g == Grade.UNC] or [m for _, m in rows]
    return min(preferred)


@dataclass(frozen=True)
class TypeMarket:
    snapshot: Snapshot
    buy: BuyAdvice
    history: list[MonthPoint]
    estimate_history: list[EstimateHistory]
    peers: list[PeerListing]


async def market_for_type(
    session: AsyncSession, coin_type: CoinType, *, now: datetime | None = None
) -> TypeMarket:
    now = now or datetime.now(UTC)
    listings = await listings_for_type(session, coin_type.id, now=now)
    catalog = await catalog_value(session, coin_type.id)
    model = await model_band_for(session, coin_type.id)
    coloured = coin_type.base_type_id is not None
    creds = await credentials(session)
    snap = snapshot(
        listings,
        issue_year=coin_type.year,
        now=now,
        catalog=catalog,
        model=model,
        type_is_coloured=coloured,
        extra_replica=tuple(creds.replica_words),
        extra_altered=tuple(creds.altered_words),
    )
    history = monthly_history(listings, now=now)
    est_rows = (
        await session.scalars(
            select(EstimateHistory)
            .join(CoinIssue, CoinIssue.id == EstimateHistory.issue_id)
            .where(CoinIssue.type_id == coin_type.id, EstimateHistory.basis != CATALOG_BASIS)
            .order_by(EstimateHistory.computed_at)
        )
    ).all()
    peers = (
        await session.scalars(
            select(PeerListing)
            .join(CollectionItem, CollectionItem.id == PeerListing.item_id)
            .join(CoinIssue, CoinIssue.id == CollectionItem.issue_id)
            .where(CoinIssue.type_id == coin_type.id, PeerListing.status == ListingStatus.ACTIVE)
            .order_by(PeerListing.price.nulls_last())
        )
    ).all()
    return TypeMarket(
        snapshot=snap,
        buy=buy_advice(snap, consider_trend=True),
        history=history,
        estimate_history=list(est_rows),
        peers=list(peers),
    )


@dataclass(frozen=True)
class Deal:
    coin_type: CoinType
    listing: Listing
    discount_pct: float
    band_low: Decimal
    band_high: Decimal
    basis: str
    reliability: float
    rank: float


async def _types_with_active_asks(session: AsyncSession, *, now: datetime) -> list[CoinType]:
    since = now - timedelta(days=45)
    ids = (
        await session.scalars(
            select(CoinIssue.type_id)
            .join(MarketObservation, MarketObservation.issue_id == CoinIssue.id)
            .where(
                MarketObservation.observation_kind.in_(list(ASKING_KINDS)),
                MarketObservation.observed_at >= since,
            )
            .distinct()
        )
    ).all()
    if not ids:
        return []
    return list((await session.scalars(select(CoinType).where(CoinType.id.in_(ids)))).all())


async def _rarity_weight(session: AsyncSession, type_id: uuid.UUID) -> float:
    tier = await session.scalar(
        select(RarityScore.tier)
        .join(CoinIssue, CoinIssue.id == RarityScore.issue_id)
        .where(CoinIssue.type_id == type_id)
        .order_by(RarityScore.score.desc())
        .limit(1)
    )
    return RARITY_WEIGHT.get(tier or "common", 1.0)


async def deals(
    session: AsyncSession, *, limit: int = 50, now: datetime | None = None
) -> list[Deal]:
    """Reliable active listings priced well below the fair band, best first."""
    now = now or datetime.now(UTC)
    threshold = (await credentials(session)).deal_threshold_pct
    found: list[Deal] = []
    for coin_type in await _types_with_active_asks(session, now=now):
        market = await market_for_type(session, coin_type, now=now)
        snap = market.snapshot
        if snap.band.basis in ("face_value", "mintage_model"):
            continue  # a deal needs a real reference, not a model
        weight = await _rarity_weight(session, coin_type.id)
        for offer in snap.offers:
            discount = deal_discount(offer.listing.price, snap.band)
            if discount < threshold:
                continue
            found.append(
                Deal(
                    coin_type=coin_type,
                    listing=offer.listing,
                    discount_pct=discount,
                    band_low=snap.band.low,
                    band_high=snap.band.high,
                    basis=snap.band.basis,
                    reliability=offer.reliability.score,
                    rank=round(discount * offer.reliability.score * weight, 2),
                )
            )
    found.sort(key=lambda d: -d.rank)
    return found[:limit]


@dataclass(frozen=True)
class Mover:
    coin_type: CoinType
    trend_pct: float
    median: Decimal
    n: int


async def movers(
    session: AsyncSession, *, limit: int = 20, now: datetime | None = None
) -> list[Mover]:
    """Coins whose realized median moved most in the last 90 days versus the previous window."""
    now = now or datetime.now(UTC)
    since = now - timedelta(days=365)
    ids = (
        await session.scalars(
            select(CoinIssue.type_id)
            .join(MarketObservation, MarketObservation.issue_id == CoinIssue.id)
            .where(
                MarketObservation.observation_kind.in_(
                    [ObservationKind.SOLD, ObservationKind.AUCTION_CLOSED]
                ),
                MarketObservation.observed_at >= since,
            )
            .group_by(CoinIssue.type_id)
            .having(func.count() >= 4)
        )
    ).all()
    out: list[Mover] = []
    for coin_type in (await session.scalars(select(CoinType).where(CoinType.id.in_(ids)))).all():
        snap = snapshot(
            await listings_for_type(session, coin_type.id, now=now),
            issue_year=coin_type.year,
            now=now,
        )
        if snap.trend_pct is None or snap.realized is None:
            continue
        out.append(Mover(coin_type, snap.trend_pct, snap.realized.median, snap.realized.n))
    out.sort(key=lambda m: -abs(m.trend_pct))
    return out[:limit]


async def _title(session: AsyncSession, type_id: uuid.UUID, lang: str) -> str:
    text = await session.scalar(
        select(TextTranslation.text).where(
            TextTranslation.entity == "coin_type",
            TextTranslation.entity_id == type_id,
            TextTranslation.field == "title",
            TextTranslation.lang == lang,
        )
    )
    return text or ""


async def notify_watchers(session: AsyncSession, *, now: datetime | None = None) -> int:
    """After a market sync: tell each watcher about new deals and big moves on watched coins.
    A deal is announced once per listing (the notification payload remembers it)."""
    now = now or datetime.now(UTC)
    watches = (await session.scalars(select(WatchItem))).all()
    sent = 0
    cache: dict[uuid.UUID, TypeMarket] = {}
    for watch in watches:
        coin_type = await session.get(CoinType, watch.type_id)
        if coin_type is None:
            continue
        if watch.type_id not in cache:
            cache[watch.type_id] = await market_for_type(session, coin_type, now=now)
        market = cache[watch.type_id]
        title_es = await _title(session, coin_type.id, "es")
        title_en = await _title(session, coin_type.id, "en")
        buy = market.buy
        if buy.verdict == "buy_now" and buy.cheapest is not None:
            already = await session.scalar(
                select(Notification.id).where(
                    Notification.user_id == watch.user_id,
                    Notification.kind == "deal",
                    Notification.payload["listing_id"].astext == buy.cheapest.listing_id,
                )
            )
            if already is None:
                session.add(
                    Notification(
                        user_id=watch.user_id,
                        kind="deal",
                        title=f"Chollo: {title_es or title_en} a {buy.cheapest.price} €",
                        body=(
                            f"{buy.saving_pct:.0f} % por debajo del rango de ventas reales "
                            f"({buy.band.low}–{buy.band.high} €)."
                        ),
                        payload={
                            "type_id": str(coin_type.id),
                            "listing_id": buy.cheapest.listing_id,
                            "url": buy.cheapest.url,
                            "price": str(buy.cheapest.price),
                        },
                    )
                )
                sent += 1
        trend = market.snapshot.trend_pct
        if trend is not None and abs(trend) >= MOVE_NOTIFY_PCT:
            marker = f"{now:%Y-%m}"
            already = await session.scalar(
                select(Notification.id).where(
                    Notification.user_id == watch.user_id,
                    Notification.kind == "price_move",
                    Notification.payload["type_id"].astext == str(coin_type.id),
                    Notification.payload["period"].astext == marker,
                )
            )
            if already is None:
                direction = "sube" if trend > 0 else "baja"
                session.add(
                    Notification(
                        user_id=watch.user_id,
                        kind="price_move",
                        title=f"{title_es or title_en} {direction} un {abs(trend):.0f} %",
                        body=(
                            "Mediana de ventas reales de los últimos 90 días "
                            "frente al resto del año."
                        ),
                        payload={
                            "type_id": str(coin_type.id),
                            "trend_pct": trend,
                            "period": marker,
                        },
                    )
                )
                sent += 1
    await session.flush()
    return sent
