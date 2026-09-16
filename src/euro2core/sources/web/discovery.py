"""Find pages that sell a coin through a public search engine (the DuckDuckGo HTML endpoint,
which allows crawling), keeping only shop-like results we are allowed to read."""

import re
from urllib.parse import parse_qs, quote_plus, urlparse

from selectolax.parser import HTMLParser

SEARCH_URL = "https://html.duckduckgo.com/html/?q={q}"
# Reference sites, social networks and search pages other sites forbid to bots: not shops.
_SKIP = (
    "duckduckgo.com/y.js",  # ads
    "wikipedia.org",
    "numista.com",
    "ecb.europa.eu",
    "youtube.com",
    "facebook.com",
    "instagram.com",
    "pinterest.",
    "reddit.com",
    "amazon.",  # marketplace search pages, no per-coin structured data
    "/sch/",  # eBay search results: Disallow in robots.txt
)
_DDG_REDIRECT = re.compile(r"^(?:https?:)?//duckduckgo\.com/l/")


def search_url(query: str) -> str:
    return SEARCH_URL.format(q=quote_plus(query))


def search_result_urls(html: str) -> list[str]:
    """Organic result links, decoded from the redirect wrapper, de-duplicated, in page order."""
    out: list[str] = []
    for node in HTMLParser(html).css("a.result__a"):
        href = node.attributes.get("href") or ""
        if _DDG_REDIRECT.match(href):
            target = parse_qs(urlparse(href).query).get("uddg", [""])[0]
        else:
            target = href
        if not target.startswith("http"):
            continue
        if any(marker in target for marker in _SKIP):
            continue
        if target not in out:
            out.append(target)
    return out
