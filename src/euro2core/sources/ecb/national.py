"""National sides of the circulation 2 euro coin, from the ECB's per-country pages.

Each page lists the designs a country has used for every denomination, oldest first; the
filename usually carries the year the design was introduced (``Belgium_2euro_2008.jpg``).
These are the only official photos of circulation coins, so every circulation ``coin_type``
gets the design that was current in its first year.
"""

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

ECB_COINS_BASE = "https://www.ecb.europa.eu/euro/coins/html/"

# The ECB does not use ISO codes for every country page.
_PAGE_SLUGS = {"EE": "et", "SI": "sl", "MC": "mo"}
_TWO_EURO_HEADING = "€2"
_YEAR_RE = re.compile(r"(?<!\d)(19\d\d|20\d\d)(?!\d)")
# Photos of special circulation sets, not of a design in daily use
_SKIP_RE = re.compile(r"sede ?vacante|placeholder", re.IGNORECASE)


@dataclass(frozen=True)
class NationalSideImage:
    url: str
    year: int | None  # None when the ECB filename is undated (typically the first design)


def national_page_url(country_code: str) -> str:
    return f"{ECB_COINS_BASE}{_PAGE_SLUGS.get(country_code, country_code.lower())}.en.html"


def parse_national_sides(html: str) -> list[NationalSideImage]:
    tree = LexborHTMLParser(html)
    for box in tree.css("div.box"):
        heading = box.css_first("div.content-box h3")
        if heading is None or heading.text(strip=True) != _TWO_EURO_HEADING:
            continue
        images = []
        for img in box.css("div.coins img"):
            src = img.attributes.get("src")
            if not src or _SKIP_RE.search(src):
                continue
            match = _YEAR_RE.search(src.rsplit("/", 1)[-1])
            images.append(
                NationalSideImage(
                    url=urljoin(ECB_COINS_BASE, src), year=int(match.group(1)) if match else None
                )
            )
        return images
    return []


def assign_images_to_years(images: list[NationalSideImage], years: list[int]) -> dict[int, str]:
    """Map each design year to the latest ECB image introduced no later than that year.
    Page order is chronological, so an undated first image is the original design and an
    undated last image is the current one (the ECB rarely dates a country's only design)."""
    if not images or not years:
        return {}
    dated: list[tuple[int, str]] = []
    for index, image in enumerate(images):
        if image.year is not None:
            year = image.year
        elif index == len(images) - 1 and dated:
            year = max(years)
        else:
            year = dated[-1][0] + 1 if dated else 0
        dated.append((year, image.url))
    dated.sort()
    assigned = {}
    for year in years:
        candidates = [url for start, url in dated if start <= year]
        assigned[year] = candidates[-1] if candidates else dated[0][1]
    return assigned
