import re
import unicodedata
from dataclasses import dataclass, field

from euro2core.domain.enums import Finish, Grade, Packaging
from euro2core.pricing import vocabulary as V

GERMAN_MINT_MARKS = frozenset("adfgj")
_YEAR_RE = re.compile(r"\b(19[9]\d|20\d\d)\b")
_YEAR_RANGE_RE = re.compile(r"\b(?:19[9]\d|20\d\d)\s*-\s*(?:19[9]\d|20\d\d)\b")
_CERT_RE = re.compile(r"\b(pcgs|ngc|anacs)\b\s*(ms|pf|pr|sp)?\s*(\d{2})\b")
_MULTIPLIER_RE = re.compile(r"\bx\s*(\d+)\b|\b(\d+)\s*x\b")
_COUNT_RE = re.compile(rf"\b([2-9]|[1-9]\d+)\s+(?:{'|'.join(V.COUNT_NOUNS)})\b")
_NON_WORD = re.compile(r"[^a-z0-9]+")


@dataclass
class ParsedTitle:
    raw: str
    normalized: str
    country_code: str | None = None
    year: int | None = None
    mint_mark: str | None = None
    finish: Finish | None = None
    packaging: Packaging | None = None
    grade: Grade = Grade.UNKNOWN
    sheldon: int | None = None
    certified_by: str | None = None
    is_lot: bool = False
    is_coloured: bool = False
    theme_text: str = ""
    matched_phrases: list[str] = field(default_factory=list)


def normalize(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " " + _NON_WORD.sub(" ", ascii_text.casefold()).strip() + " "


def parse_title(title: str) -> ParsedTitle:
    text = normalize(title)
    parsed = ParsedTitle(raw=title, normalized=text)
    consumed: list[str] = []

    parsed.country_code = _match_group(text, V.COUNTRIES, consumed)
    parsed.year = _year(text)
    parsed.finish = _match_group(text, V.FINISH, consumed)
    parsed.packaging = _match_group(text, V.PACKAGING, consumed)
    _certification(text, parsed, consumed)
    parsed.mint_mark, marks_found = _mint_mark(text, parsed.country_code)
    parsed.is_lot = _is_lot(text, marks_found)
    parsed.is_coloured = any(f" {w} " in text for w in V.COLOURED_WORDS)
    consumed.extend(w for w in V.COLOURED_WORDS if f" {w} " in text)
    if parsed.sheldon is None:
        parsed.grade = _grade(text, parsed.finish, consumed)
    parsed.matched_phrases = consumed
    parsed.theme_text = _theme(text, consumed, parsed.mint_mark)
    return parsed


def _match_group(text: str, groups: dict, consumed: list[str]):
    best_key, best_phrase = None, ""
    for key, phrases in groups.items():
        for phrase in phrases:
            if f" {phrase} " in text and len(phrase) > len(best_phrase):
                best_key, best_phrase = key, phrase
    if best_key is not None:
        consumed.append(best_phrase)
    return best_key


def _year(text: str) -> int | None:
    years = [int(y) for y in _YEAR_RE.findall(text)]
    plausible = [y for y in years if 1999 <= y <= 2100]
    return plausible[0] if plausible else None


def _certification(text: str, parsed: ParsedTitle, consumed: list[str]) -> None:
    match = _CERT_RE.search(text)
    if not match:
        return
    certifier, prefix, number = match.groups()
    parsed.certified_by = certifier.upper()
    parsed.sheldon = int(number)
    parsed.grade = Grade.PROOF if prefix in ("pf", "pr") else Grade.UNC
    consumed.extend(t for t in match.group(0).split() if t)


def _mint_mark(text: str, country: str | None) -> tuple[str | None, set[str]]:
    if country != "DE":
        return None, set()
    tokens = text.split()
    letters = {t for t in tokens if len(t) == 1 and t in GERMAN_MINT_MARKS}
    if "adfgj" in tokens:
        letters |= GERMAN_MINT_MARKS
    if len(letters) == 1:
        return next(iter(letters)).upper(), letters
    return None, letters


def _is_lot(text: str, marks_found: set[str]) -> bool:
    if len(marks_found) > 1:
        return True
    if _YEAR_RANGE_RE.search(text) or _MULTIPLIER_RE.search(text) or _COUNT_RE.search(text):
        return True
    return any(f" {w} " in text for w in V.LOT_WORDS)


def _grade(text: str, finish: Finish | None, consumed: list[str]) -> Grade:
    hinted = _match_group(text, V.GRADE, consumed)
    if hinted is not None:
        return hinted
    if finish == Finish.PROOF:
        return Grade.PROOF
    if finish == Finish.BU:
        return Grade.BU
    return Grade.UNKNOWN


def _theme(text: str, consumed: list[str], mint_mark: str | None) -> str:
    cleaned = text
    for phrase in sorted(consumed, key=len, reverse=True):
        cleaned = cleaned.replace(f" {phrase} ", " ")
    words = [
        w
        for w in cleaned.split()
        if not w.isdigit()
        and w not in V.NOISE_WORDS
        and not (mint_mark and w == mint_mark.lower())
        and len(w) > 1
    ]
    return " ".join(words)
