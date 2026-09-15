"""A value band from the mintage alone, for coins with no sales and no catalog value.

Nobody needs an API key for this: it encodes the one relationship every 2 euro collector
knows (scarce mintages command steep premiums) as explicit buckets, and it recalibrates
itself from the app's own realized sales as soon as a bucket has enough of them. The basis
`mintage_model` is always shown to the user; it is never mixed with real sales.
"""

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from euro2core.domain.enums import Finish

BASIS = "mintage_model"
METHOD_VERSION = "mintage-model-v1"
MIN_SALES_TO_CALIBRATE = 5

# (upper mintage bound exclusive, low €, high €) for a loose circulation-strike coin
DEFAULT_BUCKETS: tuple[tuple[int, Decimal, Decimal], ...] = (
    (15_000, Decimal("800"), Decimal("3000")),  # Monaco 2015 (10 000)
    (30_000, Decimal("300"), Decimal("1500")),  # Monaco 2007 / 2008 (20 000)
    (60_000, Decimal("80"), Decimal("300")),
    (120_000, Decimal("40"), Decimal("120")),  # Vatican 2004 (85 000), San Marino 2004
    (250_000, Decimal("15"), Decimal("50")),
    (600_000, Decimal("6"), Decimal("18")),
    (1_500_000, Decimal("4"), Decimal("9")),
    (8_000_000, Decimal("2.80"), Decimal("5")),
    (10**12, Decimal("2.20"), Decimal("3.50")),
)
FINISH_FACTOR = {
    Finish.CIRCULATION: Decimal("1"),
    Finish.BU: Decimal("1.3"),
    Finish.PROOF: Decimal("2"),
}
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class ModelBand:
    low: Decimal
    median: Decimal
    high: Decimal
    bucket: int  # index into the bucket table, for calibration and audit


def bucket_index(mintage: int) -> int:
    for i, (upper, _, _) in enumerate(DEFAULT_BUCKETS):
        if mintage < upper:
            return i
    return len(DEFAULT_BUCKETS) - 1


def _money(x: Decimal) -> Decimal:
    return x.quantize(_CENT, rounding=ROUND_HALF_UP)


def model_band(
    mintage: int | None,
    finish: Finish = Finish.CIRCULATION,
    calibration: dict[int, tuple[Decimal, Decimal]] | None = None,
) -> ModelBand | None:
    """Band for one issue. `calibration` maps bucket index → (p25, p75) observed in real
    sales of coins in that bucket; when present it replaces the default bucket."""
    if mintage is None or mintage <= 0:
        return None
    i = bucket_index(mintage)
    low, high = DEFAULT_BUCKETS[i][1], DEFAULT_BUCKETS[i][2]
    if calibration and i in calibration:
        low, high = calibration[i]
    factor = FINISH_FACTOR.get(finish, Decimal("1"))
    low, high = low * factor, high * factor
    median = Decimal(str(math.sqrt(float(low * high))))  # geometric mean suits a log scale
    return ModelBand(_money(low), _money(median), _money(high), i)


def calibrate(
    observed: list[tuple[int, Decimal, Decimal]],
) -> dict[int, tuple[Decimal, Decimal]]:
    """From (mintage, p25, p75) of issues that do have real sales, derive per-bucket bands:
    the median p25 and median p75 of the bucket, once it holds enough coins."""
    per_bucket: dict[int, list[tuple[Decimal, Decimal]]] = {}
    for mintage, p25, p75 in observed:
        if mintage and p25 is not None and p75 is not None:
            per_bucket.setdefault(bucket_index(mintage), []).append((p25, p75))
    out: dict[int, tuple[Decimal, Decimal]] = {}
    for i, rows in per_bucket.items():
        if len(rows) < MIN_SALES_TO_CALIBRATE:
            continue
        lows = sorted(r[0] for r in rows)
        highs = sorted(r[1] for r in rows)
        out[i] = (lows[len(lows) // 2], highs[len(highs) // 2])
    return out
