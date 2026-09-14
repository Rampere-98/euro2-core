import re
import unicodedata
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

CONFLICT_MIN_RANK = 50

NUMERIC_FIELDS = frozenset({"mintage", "year", "diameter_mm", "weight_g", "thickness_mm"})
DATE_FIELDS = frozenset({"issue_date"})

_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-"})
_WS = re.compile(r"\s+")
_NUM_SEPARATORS = re.compile(r"[.,\s ']")

ClaimKey = tuple[str, uuid.UUID, str]


@dataclass(frozen=True)
class Claim:
    entity: str
    entity_id: uuid.UUID
    field: str
    value: Any
    source_code: str
    authority_rank: int
    observed_at: datetime
    evidence_url: str | None = None

    @property
    def key(self) -> ClaimKey:
        return (self.entity, self.entity_id, self.field)


@dataclass
class Resolution:
    winner: Claim
    alternatives: list[Claim] = field(default_factory=list)
    has_conflict: bool = False


def normalize(field_name: str, value: Any) -> Any:
    if value is None:
        return None
    if field_name in NUMERIC_FIELDS:
        if isinstance(value, int | float):
            return int(value)
        digits = _NUM_SEPARATORS.sub("", str(value))
        return int(digits) if digits.lstrip("-").isdigit() else str(value)
    if field_name in DATE_FIELDS:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return date.fromisoformat(str(value)[:10]).isoformat()
    if isinstance(value, str):
        text = unicodedata.normalize("NFKD", value.translate(_DASHES))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        return _WS.sub(" ", text).strip().casefold()
    return value


def _precedence(claim: Claim) -> tuple[int, datetime]:
    return (claim.authority_rank, claim.observed_at)


def resolve(claims: Iterable[Claim], conflict_min_rank: int = CONFLICT_MIN_RANK) -> Resolution:
    ordered = sorted(claims, key=_precedence, reverse=True)
    if not ordered:
        raise ValueError("resolve() needs at least one claim")
    winner = ordered[0]
    winner_value = normalize(winner.field, winner.value)
    alternatives = [c for c in ordered[1:] if normalize(c.field, c.value) != winner_value]
    has_conflict = any(c.authority_rank >= conflict_min_rank for c in alternatives)
    return Resolution(winner=winner, alternatives=alternatives, has_conflict=has_conflict)


def resolve_all(
    claims: Iterable[Claim], conflict_min_rank: int = CONFLICT_MIN_RANK
) -> dict[ClaimKey, Resolution]:
    grouped: dict[ClaimKey, list[Claim]] = defaultdict(list)
    for claim in claims:
        grouped[claim.key].append(claim)
    return {key: resolve(group, conflict_min_rank) for key, group in grouped.items()}
