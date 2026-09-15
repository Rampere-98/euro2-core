"""How much a marketplace listing can be trusted as the price of one genuine coin.

Listing titles lie in predictable ways: lots priced as a whole, replicas, plated or
colourised coins sold as the real thing, teaser asks below face value, typos. Every
observation is scored before it is shown to a user or used in advice; the reasons are
returned so the UI can say why a listing was ignored.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from euro2core.pricing.title_parser import parse_title

FACE_VALUE = Decimal("2.00")
MATCH_STRONG = 0.95
MATCH_MIN = 0.85
ABSURD_MULTIPLIER = 20

REPLICA_WORDS = (
    "replica",
    "replika",
    "copia",
    "copy",
    "kopie",
    "fantasy",
    "fantasia",
    "fantasie",
    "prueba",
    "essai",
    "pattern",
    "probe",
    "token",
    "medalla",
    "medaille",
    "jeton",
)
ALTERED_WORDS = (
    "plated",
    "gilded",
    "gold plated",
    "vergoldet",
    "chapada",
    "chapado",
    "banada",
    "banado",
    "dorada",
    "dorado",
    "dore",
    "doree",
    "placcata",
    "placcato",
    "verguld",
    "ruthenium",
    "rhodium",
    "farbig",
    "coloured",
    "colored",
    "colorized",
    "coloreada",
    "colorada",
    "colorisee",
    "coloriert",
    "kleur",
)


@dataclass(frozen=True)
class Reliability:
    score: float
    reasons: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.score > 0


def assess(
    *,
    title: str,
    price: Decimal,
    match_confidence: float,
    issue_year: int | None,
    type_is_coloured: bool = False,
    realized: bool = False,
    fair_p75: Decimal | None = None,
) -> Reliability:
    parsed = parse_title(title)
    text = parsed.normalized
    reasons: list[str] = []

    if parsed.is_lot:
        return Reliability(0.0, ["lot"])
    if any(f" {w} " in text for w in REPLICA_WORDS):
        return Reliability(0.0, ["replica"])
    if not type_is_coloured and any(f" {w} " in text for w in ALTERED_WORDS):
        return Reliability(0.0, ["altered"])
    if match_confidence < MATCH_MIN:
        return Reliability(0.0, ["match_weak"])
    if realized and price < FACE_VALUE:
        return Reliability(0.0, ["below_face_value"])

    score = 1.0
    if match_confidence < MATCH_STRONG:
        score = 0.7
        reasons.append("match_medium")
    if fair_p75 is not None and fair_p75 > 0 and price > fair_p75 * ABSURD_MULTIPLIER:
        score = min(score, 0.3)
        reasons.append("price_absurd")
    if issue_year is not None and parsed.year is not None and parsed.year != issue_year:
        score *= 0.5
        reasons.append("year_mismatch")
    if parsed.certified_by:
        score = min(1.0, score + 0.1)
        reasons.append("certified")
    return Reliability(round(score, 4), reasons)
