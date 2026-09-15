"""Market intelligence for one coin issue: what it really sells for, what is on offer now,
and what a collector should do about it. Pure functions over observations; the API layer
loads them from the database.
"""

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from euro2core.domain.enums import Grade, ObservationKind
from euro2core.pricing.reliability import FACE_VALUE, Reliability, assess

REALIZED_KINDS = frozenset({ObservationKind.SOLD, ObservationKind.AUCTION_CLOSED})
ASKING_KINDS = frozenset({ObservationKind.ASKING, ObservationKind.AUCTION_OPEN})
WINDOWS = (90, 365)
MIN_SALES_SHORT = 5
MIN_SALES = 3
MIN_SALES_MARKETPLACE = 3
CATALOG_SPREAD = Decimal("0.20")
DEAL_THRESHOLD_PCT = 15.0
WAIT_TREND_PCT = -10.0
HOLD_TREND_PCT = 15.0
EBAY_FEE_RATE = Decimal("0.1325")
EBAY_FEE_FIXED = Decimal("0.35")
GRADE_FACTOR = {
    Grade.CIRCULATED: Decimal("0.70"),
    Grade.UNKNOWN: Decimal("0.85"),
    Grade.UNC: Decimal("1.00"),
    Grade.BU: Decimal("1.15"),
    Grade.PROOF: Decimal("1.50"),
}
_CENT = Decimal("0.01")


def _money(value: Decimal | float) -> Decimal:
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Listing:
    """One market observation, already loaded from the database."""

    listing_id: str
    kind: ObservationKind
    price: Decimal
    observed_at: datetime
    marketplace: str
    url: str
    title: str
    match_confidence: float
    grade: Grade = Grade.UNKNOWN
    ends_at: datetime | None = None


@dataclass(frozen=True)
class ScoredListing:
    listing: Listing
    reliability: Reliability


@dataclass(frozen=True)
class RangeStats:
    n: int
    min: Decimal
    p25: Decimal
    median: Decimal
    p75: Decimal
    max: Decimal
    window_days: int


@dataclass(frozen=True)
class Band:
    low: Decimal
    high: Decimal
    basis: str  # sold | catalog | face_value


@dataclass(frozen=True)
class Snapshot:
    realized: RangeStats | None
    asking: RangeStats | None
    band: Band
    trend_pct: float | None
    sales_per_month: float
    expected_days_to_sell: int | None
    best_marketplace: str | None
    offers: list[ScoredListing] = field(default_factory=list)  # reliable, cheapest first
    ignored: list[Listing] = field(default_factory=list)  # with the reason in `ignored_reasons`
    ignored_reasons: dict[str, list[str]] = field(default_factory=dict)


def _stats(prices: list[Decimal], window_days: int) -> RangeStats:
    ordered = sorted(prices)
    if len(ordered) >= 2:
        q1, med, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
    else:
        q1 = med = q3 = ordered[0]
    return RangeStats(
        n=len(ordered),
        min=_money(ordered[0]),
        p25=_money(q1),
        median=_money(med),
        p75=_money(q3),
        max=_money(ordered[-1]),
        window_days=window_days,
    )


def fair_band(realized: RangeStats | None, catalog: Decimal | None) -> tuple[Decimal, Decimal, str]:
    if realized is not None:
        return realized.p25, realized.p75, "sold"
    if catalog is not None and catalog > 0:
        return (
            _money(catalog * (1 - CATALOG_SPREAD)),
            _money(catalog * (1 + CATALOG_SPREAD)),
            "catalog",
        )
    return FACE_VALUE, FACE_VALUE, "face_value"


def snapshot(
    listings: list[Listing],
    *,
    issue_year: int | None,
    now: datetime,
    catalog: Decimal | None = None,
    type_is_coloured: bool = False,
) -> Snapshot:
    scored: list[ScoredListing] = []
    ignored: list[Listing] = []
    reasons: dict[str, list[str]] = {}
    for x in listings:
        r = assess(
            title=x.title,
            price=x.price,
            match_confidence=x.match_confidence,
            issue_year=issue_year,
            type_is_coloured=type_is_coloured,
            realized=x.kind in REALIZED_KINDS,
        )
        if r.usable:
            scored.append(ScoredListing(x, r))
        else:
            ignored.append(x)
            reasons[x.listing_id] = r.reasons

    sold = [s for s in scored if s.listing.kind in REALIZED_KINDS]
    realized: RangeStats | None = None
    recent: list[ScoredListing] = []
    for window in WINDOWS:
        since = now - timedelta(days=window)
        recent = [s for s in sold if s.listing.observed_at >= since]
        needed = MIN_SALES_SHORT if window == WINDOWS[0] else MIN_SALES
        if len(recent) >= needed:
            realized = _stats([s.listing.price for s in recent], window)
            break

    # trend: last 90 days against the rest of the year
    short = now - timedelta(days=WINDOWS[0])
    year = now - timedelta(days=WINDOWS[1])
    last = [s.listing.price for s in sold if s.listing.observed_at >= short]
    before = [s.listing.price for s in sold if year <= s.listing.observed_at < short]
    trend = None
    if len(last) >= 2 and len(before) >= 2:
        m_last, m_before = statistics.median(last), statistics.median(before)
        if m_before > 0:
            trend = round(float((m_last - m_before) / m_before) * 100, 1)

    per_month = len(last) / (WINDOWS[0] / 30)
    days_to_sell = round(30 / per_month) if per_month > 0 else None

    by_market: dict[str, list[Decimal]] = {}
    for s in recent if realized else sold:
        by_market.setdefault(s.listing.marketplace, []).append(s.listing.price)
    eligible = {
        m: statistics.median(p) for m, p in by_market.items() if len(p) >= MIN_SALES_MARKETPLACE
    }
    best = max(eligible, key=eligible.get) if eligible else None

    asks = sorted(
        (s for s in scored if s.listing.kind in ASKING_KINDS), key=lambda s: s.listing.price
    )
    asking = _stats([s.listing.price for s in asks], 0) if asks else None
    low, high, basis = fair_band(realized, catalog)
    return Snapshot(
        realized=realized,
        asking=asking,
        band=Band(low, high, basis),
        trend_pct=trend,
        sales_per_month=round(per_month, 3),
        expected_days_to_sell=days_to_sell,
        best_marketplace=best,
        offers=asks,
        ignored=ignored,
        ignored_reasons=reasons,
    )


def deal_discount(price: Decimal, band: Band) -> float:
    """Percentage below the low end of the fair band (0 when not a deal)."""
    if band.low <= 0 or price >= band.low:
        return 0.0
    return round(float((band.low - price) / band.low) * 100, 1)


@dataclass(frozen=True)
class BuyAdvice:
    verdict: str  # buy_now | fair | overpriced | wait | no_offers
    cheapest: Listing | None
    saving_pct: float
    band: Band
    trend_pct: float | None


def buy_advice(s: Snapshot, *, consider_trend: bool = False) -> BuyAdvice:
    if not s.offers:
        return BuyAdvice("no_offers", None, 0.0, s.band, s.trend_pct)
    cheapest = s.offers[0].listing
    price = cheapest.price
    if price <= s.band.low:
        verdict = "buy_now"
    elif price <= s.band.high:
        verdict = "fair"
    else:
        verdict = "overpriced"
    falling = s.trend_pct is not None and s.trend_pct <= WAIT_TREND_PCT
    if consider_trend and verdict != "buy_now" and falling:
        verdict = "wait"
    saving = round(float((s.band.low - price) / s.band.low) * 100, 1) if s.band.low > 0 else 0.0
    return BuyAdvice(verdict, cheapest, max(saving, 0.0), s.band, s.trend_pct)


@dataclass(frozen=True)
class SellAdvice:
    start: Decimal  # suggested asking price
    floor: Decimal  # do not go below
    grade: Grade
    expected_days: int | None
    best_marketplace: str | None
    net_ebay: Decimal
    net_euro2: Decimal
    hold: bool
    band: Band
    trend_pct: float | None


def sell_advice(s: Snapshot, *, grade: Grade) -> SellAdvice:
    factor = GRADE_FACTOR.get(grade, Decimal("1"))
    start = _money(s.band.high * factor)
    floor = _money(s.band.low * factor)
    net_ebay = max(_money(start * (1 - EBAY_FEE_RATE) - EBAY_FEE_FIXED), Decimal("0"))
    hold = s.trend_pct is not None and s.trend_pct >= HOLD_TREND_PCT
    return SellAdvice(
        start=start,
        floor=floor,
        grade=grade,
        expected_days=s.expected_days_to_sell,
        best_marketplace=s.best_marketplace,
        net_ebay=net_ebay,
        net_euro2=start,
        hold=hold,
        band=s.band,
        trend_pct=s.trend_pct,
    )


@dataclass(frozen=True)
class MonthPoint:
    month: str  # YYYY-MM
    sold_n: int
    sold_min: Decimal | None
    sold_median: Decimal | None
    sold_max: Decimal | None
    ask_n: int
    ask_median: Decimal | None


def monthly_history(
    listings: list[Listing], *, now: datetime, months: int = 24
) -> list[MonthPoint]:
    """Reliable sales and asks bucketed by month, oldest first, for the price chart.
    Months without data are kept (with zeros) so the chart axis is regular."""
    scored = [
        x
        for x in listings
        if assess(
            title=x.title,
            price=x.price,
            match_confidence=x.match_confidence,
            issue_year=None,
            realized=x.kind in REALIZED_KINDS,
        ).usable
    ]
    keys: list[str] = []
    y, m = now.year, now.month
    for _ in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    keys.reverse()
    sold: dict[str, list[Decimal]] = {k: [] for k in keys}
    asks: dict[str, list[Decimal]] = {k: [] for k in keys}
    for x in scored:
        key = f"{x.observed_at.year:04d}-{x.observed_at.month:02d}"
        if key not in sold:
            continue
        (sold if x.kind in REALIZED_KINDS else asks)[key].append(x.price)
    out = []
    for k in keys:
        s, a = sold[k], asks[k]
        out.append(
            MonthPoint(
                month=k,
                sold_n=len(s),
                sold_min=_money(min(s)) if s else None,
                sold_median=_money(statistics.median(s)) if s else None,
                sold_max=_money(max(s)) if s else None,
                ask_n=len(a),
                ask_median=_money(statistics.median(a)) if a else None,
            )
        )
    return out
