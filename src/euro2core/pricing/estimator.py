import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from euro2core.domain.enums import Grade, ObservationKind

METHOD_VERSION = "price-v1"
GLOBAL_REGION = "global"
MIN_MATCH_CONFIDENCE = 0.85
PRIMARY_WINDOW_DAYS = 90
EXTENDED_WINDOW_DAYS = 365
MIN_SAMPLE = 3
WIDEN_BELOW = 5
MIN_REGIONAL_SAMPLE = 3
MIN_FOR_OUTLIER_DETECTION = 5
IQR_FENCE = 1.5

REALIZED_KINDS = frozenset({ObservationKind.SOLD, ObservationKind.AUCTION_CLOSED})


@dataclass(frozen=True)
class Observation:
    id: str
    price: Decimal
    kind: ObservationKind
    grade: Grade
    marketplace: str
    observed_at: datetime
    match_confidence: float


@dataclass
class Estimate:
    grade: Grade
    region: str
    window_days: int
    median: Decimal | None
    p25: Decimal | None
    p75: Decimal | None
    n_obs: int
    confidence: str
    basis: str
    method_version: str = METHOD_VERSION
    outlier_ids: list[str] = field(default_factory=list)


def estimate(
    observations: Iterable[Observation], *, grade: Grade, region: str, now: datetime
) -> Estimate:
    eligible = [
        o
        for o in observations
        if o.grade == grade
        and o.match_confidence >= MIN_MATCH_CONFIDENCE
        and (region == GLOBAL_REGION or o.marketplace == region)
    ]
    realized = [o for o in eligible if o.kind in REALIZED_KINDS]
    window, sample = _pick_window(realized, now)
    basis = "sold"
    if len(sample) < MIN_SAMPLE:
        asking = [o for o in eligible if o.kind == ObservationKind.ASKING]
        _, asking_sample = _pick_window(asking, now)
        if len(asking_sample) >= MIN_SAMPLE:
            basis, sample = "asking_only", asking_sample
        else:
            return Estimate(
                grade, region, window, None, None, None, len(sample), "low", "insufficient"
            )
    if region != GLOBAL_REGION and len(sample) < MIN_REGIONAL_SAMPLE:
        return Estimate(grade, region, window, None, None, None, len(sample), "low", "insufficient")

    kept, outliers = _split_outliers(sample)
    prices = sorted(float(o.price) for o in kept)
    q1, q2, q3 = (
        statistics.quantiles(prices, n=4, method="inclusive")
        if len(prices) > 1
        else (prices[0],) * 3
    )
    confidence = "low" if basis == "asking_only" else _confidence(len(kept))
    return Estimate(
        grade=grade,
        region=region,
        window_days=window,
        median=_money(q2),
        p25=_money(q1),
        p75=_money(q3),
        n_obs=len(kept),
        confidence=confidence,
        basis=basis,
        outlier_ids=[o.id for o in outliers],
    )


def _pick_window(obs: list[Observation], now: datetime) -> tuple[int, list[Observation]]:
    recent = _within(obs, now, PRIMARY_WINDOW_DAYS)
    if len(recent) >= WIDEN_BELOW:
        return PRIMARY_WINDOW_DAYS, recent
    extended = _within(obs, now, EXTENDED_WINDOW_DAYS)
    return (
        (EXTENDED_WINDOW_DAYS, extended)
        if len(extended) > len(recent)
        else (PRIMARY_WINDOW_DAYS, recent)
    )


def _within(obs: list[Observation], now: datetime, days: int) -> list[Observation]:
    cutoff = now - timedelta(days=days)
    return [o for o in obs if cutoff <= o.observed_at <= now]


def _split_outliers(sample: list[Observation]) -> tuple[list[Observation], list[Observation]]:
    if len(sample) < MIN_FOR_OUTLIER_DETECTION:
        return sample, []
    logs = sorted(math.log(float(o.price)) for o in sample)
    q1, _, q3 = statistics.quantiles(logs, n=4, method="inclusive")
    low, high = q1 - IQR_FENCE * (q3 - q1), q3 + IQR_FENCE * (q3 - q1)
    kept = [o for o in sample if low <= math.log(float(o.price)) <= high]
    outliers = [o for o in sample if o not in kept]
    return kept, outliers


def _confidence(n: int) -> str:
    if n >= 10:
        return "high"
    if n >= 5:
        return "medium"
    return "low"


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
