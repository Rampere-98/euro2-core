"""Numista catalog values per grade: a labelled fallback, never presented as market price."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from euro2core.domain.enums import Grade

# Numista grades -> ours. Only the most representative grade of each class is kept.
GRADE_MAP = {"xf": Grade.CIRCULATED, "unc": Grade.UNC, "bu": Grade.BU, "pf": Grade.PROOF}


def parse_prices(payload: dict[str, Any]) -> dict[Grade, Decimal]:
    if payload.get("currency") != "EUR":
        return {}
    out: dict[Grade, Decimal] = {}
    for entry in payload.get("prices") or []:
        grade = GRADE_MAP.get(str(entry.get("grade", "")).lower())
        price = entry.get("price")
        if grade is None or price is None:
            continue
        value = Decimal(str(price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if value > 0:
            out[grade] = value
    return out
