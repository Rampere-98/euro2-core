"""What to type in a search box to find a given coin for sale."""

from euro2core.pricing.market_intel import COUNTRY_NAMES

# (language, head, verb): how a buyer in that market would search
_PHRASES = (
    ("es", "2 euros", "comprar"),
    ("de", "2 Euro", "kaufen"),
    ("en", "2 euro", "buy"),
)


def shop_queries(*, country_code: str, year: int, title: str | None) -> list[str]:
    """One query per shopper language; Spanish first because most shops we can read are Spanish."""
    out = []
    for lang, head, verb in _PHRASES:
        country = COUNTRY_NAMES[lang].get(country_code, country_code)
        words = " ".join(w for w in (head, country, str(year), title or "", verb) if w)
        out.append(words)
    return out
