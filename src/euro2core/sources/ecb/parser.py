"""Parser for ECB yearly commemorative coin pages (comm_<year>.en.html)."""

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import unquote, urljoin

from selectolax.lexbor import LexborHTMLParser

from euro2core.domain.eurozone import member_states

ECB_COMM_BASE = "https://www.ecb.europa.eu/euro/coins/comm/html/"

COUNTRY_CODES: dict[str, str] = {
    "andorra": "AD",
    "austria": "AT",
    "belgium": "BE",
    "bulgaria": "BG",
    "croatia": "HR",
    "cyprus": "CY",
    "estonia": "EE",
    "finland": "FI",
    "france": "FR",
    "germany": "DE",
    "greece": "GR",
    "ireland": "IE",
    "italy": "IT",
    "latvia": "LV",
    "lithuania": "LT",
    "luxembourg": "LU",
    "malta": "MT",
    "monaco": "MC",
    "netherlands": "NL",
    "the netherlands": "NL",
    "nederland": "NL",
    "portugal": "PT",
    "san marino": "SM",
    "slovakia": "SK",
    "slovenia": "SI",
    "spain": "ES",
    "vatican": "VA",
    "vatican city": "VA",
    "vatican city state": "VA",
}

JOINT_ISSUE_HEADING = "euro area countries"

_LABELS = ("Feature", "Description", "Issuing volume", "Issuing date")
# ECB editors are inconsistent about spacing around the colon ("Feature:" vs "Feature :")
_LABEL_RE = re.compile(
    r"Feature\s*:\s*(?P<feature>.*?)\s*Description\s*:\s*(?P<description>.*?)\s*"
    r"Issuing volume\s*:\s*(?P<volume>.*?)\s*Issuing date\s*:\s*(?P<date>.*)",
    re.DOTALL | re.IGNORECASE,
)
_MINTAGE_RE = re.compile(r"\d[\d.,\s ]*\d|\d")
_SLUG_KEEP = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class EcbEntry:
    year: int
    country_code: str
    country_name: str
    feature: str
    description: str
    mintage: int | None
    mintage_raw: str
    issue_date_raw: str
    image_urls: list[str] = field(default_factory=list)
    joint_issue_group: str | None = None

    @property
    def ecb_ref(self) -> str:
        return f"{self.year}/{self.country_code}/{slugify(self.feature, max_words=6)}"


def country_code_for(name: str) -> str:
    return COUNTRY_CODES[_clean(name).casefold()]


def slugify(text: str, max_words: int | None = None) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    words = [w for w in _SLUG_KEEP.split(ascii_text.casefold()) if w]
    if max_words is not None:
        words = words[:max_words]
    return "-".join(words)


def parse_mintage(raw: str) -> int | None:
    match = _MINTAGE_RE.search(raw)
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(0))
    return int(digits) if digits else None


def parse_commemorative_page(html: str, year: int) -> list[EcbEntry]:
    tree = LexborHTMLParser(html)
    entries: list[EcbEntry] = []
    for box in tree.css("div.box"):
        heading = box.css_first("h3")
        content = box.css_first("div.content-box")
        if heading is None or content is None:
            continue
        fields = _extract_fields(content.text(separator=" "))
        if fields is None:
            continue
        images = [
            urljoin(ECB_COMM_BASE, img.attributes["src"])
            for img in box.css("picture img")
            if img.attributes.get("src")
        ]
        country_name = _clean(heading.text())
        if country_name.casefold() == JOINT_ISSUE_HEADING:
            entries.extend(_expand_joint_issue(year, fields, images))
        else:
            entries.append(
                _entry(year, country_code_for(country_name), country_name, fields, images)
            )
    return entries


def _extract_fields(text: str) -> dict[str, str] | None:
    match = _LABEL_RE.search(_clean(text))
    if not match:
        return None
    return {k: _clean(v) for k, v in match.groupdict().items()}


def _entry(
    year: int,
    code: str,
    country_name: str,
    fields: dict[str, str],
    images: list[str],
    joint_issue_group: str | None = None,
) -> EcbEntry:
    volume = fields["volume"]
    return EcbEntry(
        year=year,
        country_code=code,
        country_name=country_name,
        feature=fields["feature"],
        description=fields["description"],
        mintage=None if joint_issue_group else parse_mintage(volume),
        mintage_raw=volume,
        issue_date_raw=fields["date"],
        image_urls=images,
        joint_issue_group=joint_issue_group,
    )


def _expand_joint_issue(year: int, fields: dict[str, str], images: list[str]) -> list[EcbEntry]:
    group = f"{year}-{slugify(fields['feature'], max_words=6)}"
    group = _JOINT_GROUP_ALIASES.get(group, group)
    # Every member state of that year takes part (micro-states never join joint
    # issues); the ECB page may still miss or add a national photo, so union both.
    by_country: dict[str, list[str]] = {c.code: [] for c in member_states(year)}
    shared: list[str] = []
    for url in images:
        code = country_from_image_url(url)
        if code is None:
            shared.append(url)
        else:
            by_country.setdefault(code, []).append(url)
    names = {c.code: c.name for c in member_states(year, include_micro_states=True)}
    return [
        _entry(year, code, names.get(code, code), fields, urls + shared, group)
        for code, urls in by_country.items()
    ]


_COUNTRY_NAMES_BY_LENGTH = sorted(COUNTRY_CODES, key=len, reverse=True)


def country_from_image_url(url: str) -> str | None:
    """Infer the issuing country from an ECB image filename, or None for shared images."""
    stem = unquote(url.rsplit("/", 1)[-1]).rsplit(".", 1)[0]
    stem = re.sub(r"^joint_comm_\d{4}_", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\d+x\d+|\d+|\bface\b", " ", stem, flags=re.IGNORECASE)
    stem = _clean(stem).casefold()
    for name in _COUNTRY_NAMES_BY_LENGTH:
        if stem == name or stem.startswith(name + " "):
            return COUNTRY_CODES[name]
    return None


# Short, human-readable group ids for well-known joint issues
_JOINT_GROUP_ALIASES = {
    "2007-50th-anniversary-of-the-treaty-of": "2007-treaty-of-rome",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip()
