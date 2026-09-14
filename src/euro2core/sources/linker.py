"""Links catalog records from different sources that describe the same emission."""

import re
import unicodedata
from collections.abc import Sequence

from rapidfuzz import fuzz

from euro2core.sources.ecb.parser import EcbEntry

LINK_THRESHOLD = 70

_BOILERPLATE = frozenset(
    {
        "2",
        "euro",
        "euros",
        "bundeslander",
        "bundeslaender",
        "the",
        "of",
        "and",
        "a",
        "an",
        "in",
        "de",
        "la",
        "del",
        "th",
        "st",
        "nd",
        "rd",
        "anniversary",
        "years",
        "year",
        "commemorative",
        "coin",
        "ii",
    }
)
_NON_WORD = re.compile(r"[^a-z0-9]+")


def clean(text: str | None) -> str:
    if not text:
        return ""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    tokens = [t for t in _NON_WORD.split(ascii_text) if t and t not in _BOILERPLATE]
    return " ".join(tokens)


def link_score(title: str, topic: str | None, feature: str) -> float:
    target = clean(feature)
    if not target:
        return 0.0
    scores = [fuzz.token_set_ratio(clean(title), target)] if clean(title) else [0.0]
    if clean(topic):
        scores.append(fuzz.token_set_ratio(clean(topic), target))
    return max(scores)


def match_ecb_entry(
    *,
    country: str,
    year: int,
    title: str,
    topic: str | None,
    candidates: Sequence[EcbEntry],
    threshold: float = LINK_THRESHOLD,
) -> tuple[EcbEntry | None, float]:
    best: EcbEntry | None = None
    best_score = 0.0
    for entry in candidates:
        if entry.country_code != country or entry.year != year:
            continue
        score = link_score(title, topic, entry.feature)
        if score > best_score:
            best, best_score = entry, score
    if best is None or best_score < threshold:
        return None, best_score
    return best, best_score
