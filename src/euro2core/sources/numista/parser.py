"""Pure parsing of Numista API v3 payloads into domain-shaped records."""

import re
from dataclasses import dataclass
from typing import Any

from euro2core.domain.enums import CoinKind, Finish, Packaging

# Numista issuer codes (both the top-level section and the modern child issuer) -> ISO 3166-1
EUROZONE_ISSUERS: dict[str, str] = {
    "andorre": "AD",
    "austria": "AT",
    "autriche": "AT",
    "belgium": "BE",
    "belgique": "BE",
    "bulgaria_section": "BG",
    "bulgarie": "BG",
    "croatia": "HR",
    "croatie": "HR",
    "chypre_section": "CY",
    "chypre": "CY",
    "estonia_section": "EE",
    "estonie": "EE",
    "finland_section": "FI",
    "finlande": "FI",
    "france_section": "FR",
    "france": "FR",
    "germany": "DE",
    "allemagne": "DE",
    "greece": "GR",
    "grece": "GR",
    "irlande": "IE",
    "italy": "IT",
    "italie": "IT",
    "lettonie_section": "LV",
    "lettonie": "LV",
    "lithuania_section": "LT",
    "lituanie": "LT",
    "luxembourg_section": "LU",
    "luxembourg": "LU",
    "malte": "MT",
    "monaco_section": "MC",
    "monaco": "MC",
    "netherlands": "NL",
    "pays-bas": "NL",
    "portugal_section": "PT",
    "portugal": "PT",
    "saint-marin": "SM",
    "slovaquie": "SK",
    "slovenie": "SI",
    "spain": "ES",
    "espagne": "ES",
    "papal_states_section": "VA",
    "vatican": "VA",
}

# Top-level codes to pass as `issuer` when searching (children are included by Numista)
SEARCH_ISSUERS: tuple[str, ...] = (
    "andorre",
    "austria",
    "belgium",
    "bulgaria_section",
    "croatia",
    "chypre_section",
    "estonia_section",
    "finland_section",
    "france_section",
    "germany",
    "greece",
    "irlande",
    "italy",
    "lettonie_section",
    "lithuania_section",
    "luxembourg_section",
    "malte",
    "monaco_section",
    "netherlands",
    "portugal_section",
    "saint-marin",
    "slovaquie",
    "slovenie",
    "spain",
    "papal_states_section",
)

STANDARD_CIRCULATION = "Standard circulation coins"
EXCLUDED_OBJECT_TYPES = frozenset({"Patterns", "Fantasy coins", "Mint set tokens"})

_TWO_EURO_TITLE = re.compile(r"^2 Euros?\b(?! Cents?)")
_ERROR_MARKERS = re.compile(r"\b(mule|error|fehlpr[aä]gung|variante|variety)\b", re.IGNORECASE)
# "(1st map)" / "(2nd map)" name the common-side design of a standard coin, not a commemoration
_MAP_VARIANT = re.compile(r"\((1st|2nd)\s+map\)", re.IGNORECASE)


@dataclass(frozen=True)
class NumistaPicture:
    url: str
    thumbnail: str | None
    author: str | None
    license: str | None
    license_url: str | None


@dataclass(frozen=True)
class NumistaType:
    id: int
    lang: str
    title: str
    country_code: str
    issuer_code: str
    kind: CoinKind
    year: int
    max_year: int
    url: str
    series: str | None
    topic: str | None
    obverse_description: str | None
    reverse_description: str | None
    obverse: NumistaPicture | None
    reverse: NumistaPicture | None
    km_reference: str | None
    composition: str | None
    diameter_mm: float | None
    weight_g: float | None
    comments_html: str | None


@dataclass(frozen=True)
class NumistaIssue:
    id: int
    year: int
    mint_mark: str
    finish: Finish
    packaging: Packaging
    mintage: int | None
    comment: str | None


def iso_for_issuer(code: str) -> str:
    return EUROZONE_ISSUERS[code]


def is_two_euro(search_result: dict[str, Any]) -> bool:
    if search_result.get("object_type", {}).get("name") in EXCLUDED_OBJECT_TYPES:
        return False
    return bool(_TWO_EURO_TITLE.match(search_result.get("title", "")))


def classify_kind(title: str, object_type_name: str) -> CoinKind:
    if _ERROR_MARKERS.search(title):
        return CoinKind.ERROR
    if object_type_name == STANDARD_CIRCULATION or _MAP_VARIANT.search(title):
        return CoinKind.CIRCULATION
    return CoinKind.COMMEMORATIVE


def parse_type(data: dict[str, Any], lang: str | None = None) -> NumistaType:
    title = data["title"]
    object_type = data.get("object_type", {}).get("name", "")
    issuer_code = data["issuer"]["code"]
    references = data.get("references") or []
    km = next((r for r in references if r.get("catalogue", {}).get("code") == "KM"), None)
    return NumistaType(
        id=data["id"],
        lang=lang or _lang_from_url(data.get("url", "")),
        title=title,
        country_code=iso_for_issuer(issuer_code),
        issuer_code=issuer_code,
        kind=classify_kind(title, object_type),
        year=data["min_year"],
        max_year=data.get("max_year", data["min_year"]),
        url=data.get("url", f"https://en.numista.com/{data['id']}"),
        series=data.get("series"),
        topic=data.get("commemorated_topic"),
        obverse_description=(data.get("obverse") or {}).get("description"),
        reverse_description=(data.get("reverse") or {}).get("description"),
        obverse=_picture(data.get("obverse")),
        reverse=_picture(data.get("reverse")),
        km_reference=f"KM {km['number']}" if km else None,
        composition=(data.get("composition") or {}).get("text"),
        diameter_mm=data.get("size"),
        weight_g=data.get("weight"),
        comments_html=data.get("comments"),
    )


def parse_issue(data: dict[str, Any]) -> NumistaIssue:
    comment = data.get("comment")
    finish, packaging = _finish_and_packaging(comment)
    return NumistaIssue(
        id=data["id"],
        year=data.get("gregorian_year") or data["year"],
        mint_mark=(data.get("mint_letter") or "").strip().upper(),
        finish=finish,
        packaging=packaging,
        mintage=data.get("mintage"),
        comment=comment,
    )


def _finish_and_packaging(comment: str | None) -> tuple[Finish, Packaging]:
    text = (comment or "").casefold()
    if "proof" in text or "polierte" in text or "belle epreuve" in text:
        finish = Finish.PROOF
    elif "bu" in text.split() or "brilliant" in text or "set" in text or "coincard" in text:
        finish = Finish.BU
    else:
        finish = Finish.CIRCULATION
    if "coincard" in text or "coin card" in text or "blister" in text:
        packaging = Packaging.COINCARD
    elif "set" in text or "folder" in text:
        packaging = Packaging.SET
    else:
        packaging = Packaging.LOOSE
    return finish, packaging


def _picture(side: dict[str, Any] | None) -> NumistaPicture | None:
    if not side or not side.get("picture"):
        return None
    return NumistaPicture(
        url=side["picture"],
        thumbnail=side.get("thumbnail"),
        author=side.get("picture_copyright"),
        license=side.get("picture_license_name"),
        license_url=side.get("picture_license_url"),
    )


def _lang_from_url(url: str) -> str:
    match = re.match(r"https://(\w{2})\.numista\.com", url)
    return match.group(1) if match else "en"
