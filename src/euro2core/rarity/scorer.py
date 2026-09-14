import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

METHOD_VERSION = "rarity-v1"
FACE_VALUE = 2.0

WEIGHTS = {"mintage": 0.60, "availability": 0.25, "premium": 0.15}
MINTAGE_COMMON = 30_000_000  # -> 0
MINTAGE_EXCEPTIONAL = 10_000  # -> 100
PREMIUM_CAP_MULTIPLE = 500  # 500x face value -> 100

TIERS = (
    (85, "exceptional"),
    (65, "very_rare"),
    (45, "rare"),
    (25, "uncommon"),
    (0, "common"),
)


@dataclass(frozen=True)
class MarketSignals:
    active_listings_per_million: float | None
    median_sale_price: Decimal | None
    catalog_median_listings_per_million: float | None


@dataclass(frozen=True)
class RarityResult:
    score: float
    tier: str
    components: dict[str, Any]
    method_version: str = METHOD_VERSION


def score(mintage: int | None, market: MarketSignals) -> RarityResult | None:
    if mintage is None or mintage <= 0:
        return None
    components = {
        "mintage": _mintage_component(mintage),
        "availability": _availability_component(market),
        "premium": _premium_component(market.median_sale_price),
    }
    available = {k: v for k, v in components.items() if v is not None}
    total_weight = sum(WEIGHTS[k] for k in available)
    value = sum(WEIGHTS[k] * v for k, v in available.items()) / total_weight
    value = round(_clamp(value), 2)
    return RarityResult(
        score=value,
        tier=tier_for(value),
        components={**components, "weights": WEIGHTS, "inputs": _inputs(mintage, market)},
    )


def tier_for(value: float) -> str:
    for threshold, name in TIERS:
        if value >= threshold:
            return name
    return "common"


def _mintage_component(mintage: int) -> float:
    hi, lo = math.log10(MINTAGE_COMMON), math.log10(MINTAGE_EXCEPTIONAL)
    return _clamp(100 * (hi - math.log10(mintage)) / (hi - lo))


def _availability_component(market: MarketSignals) -> float | None:
    lpm, baseline = market.active_listings_per_million, market.catalog_median_listings_per_million
    if lpm is None or not baseline:
        return None
    # ratio 1 (typical supply) -> 50; 10x more supply -> 0; 10x less -> 100
    ratio = max(lpm, 1e-6) / baseline
    return _clamp(50 * (1 - math.log10(ratio)))


def _premium_component(median_sale: Decimal | None) -> float | None:
    if median_sale is None or median_sale <= 0:
        return None
    multiple = float(median_sale) / FACE_VALUE
    if multiple <= 1:
        return 0.0
    return _clamp(100 * math.log10(multiple) / math.log10(PREMIUM_CAP_MULTIPLE))


def _inputs(mintage: int, market: MarketSignals) -> dict[str, Any]:
    return {
        "mintage": mintage,
        "active_listings_per_million": market.active_listings_per_million,
        "median_sale_price": float(market.median_sale_price) if market.median_sale_price else None,
        "catalog_median_listings_per_million": market.catalog_median_listings_per_million,
    }


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))
