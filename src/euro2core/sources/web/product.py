"""Read a product page the way search engines do: schema.org JSON-LD first, OpenGraph tags
second. Works for most shops (PrestaShop, WooCommerce, OpenCart, Shopify) and for classified
ads that mark up their listing; a page without a positive price is not a product."""

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from selectolax.parser import HTMLParser

_SOLD_OUT = ("outofstock", "soldout", "discontinued", "out of stock", "sold out", "agotado")
_IN_STOCK = ("instock", "in stock", "limitedavailability", "preorder", "onlineonly", "disponible")


@dataclass(frozen=True)
class ProductPage:
    url: str
    host: str
    title: str
    price: Decimal
    currency: str
    availability: str | None  # in_stock | sold_out | None
    condition: str | None = None


def parse_product(html: str, url: str) -> ProductPage | None:
    tree = HTMLParser(html)
    host = urlparse(url).netloc.lower().removeprefix("www.")
    found = _from_json_ld(tree) or _from_opengraph(tree)
    if found is None:
        return None
    title, price, currency, availability, condition = found
    if price is None or price <= 0:
        return None
    if not title:
        node = tree.css_first("title")
        title = node.text(strip=True) if node else url
    return ProductPage(
        url=url,
        host=host,
        title=_clean(title),
        price=price,
        currency=(currency or "EUR").upper()[:3],
        availability=availability,
        condition=condition,
    )


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:300]


def _money(value) -> Decimal | None:
    """'3,600.00', '3.600,00', '4600' and '4490.00' all mean what a human reads."""
    if value is None:
        return None
    text = str(value).strip().replace("\xa0", "").replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(".") > text.rfind(","):
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    text = re.sub(r"[^0-9.]", "", text)
    try:
        return Decimal(text) if text else None
    except InvalidOperation:
        return None


def _availability(value) -> str | None:
    if not value:
        return None
    v = str(value).lower()
    if any(k in v for k in _SOLD_OUT):
        return "sold_out"
    if any(k in v for k in _IN_STOCK):
        return "in_stock"
    return None


def _condition(value) -> str | None:
    if not value:
        return None
    v = str(value).lower()
    return "used" if "used" in v else "new" if "new" in v else None


def _from_json_ld(tree: HTMLParser):
    products = []
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text())
        except (ValueError, TypeError):
            continue
        products.extend(_walk_products(data))
    best = None
    for product in products:
        for offer in _offers(product):
            price = _money(offer.get("price") or offer.get("lowPrice"))
            if price is None or price <= 0:
                continue
            candidate = (
                product.get("name") or "",
                price,
                offer.get("priceCurrency"),
                _availability(offer.get("availability")),
                _condition(offer.get("itemCondition")),
            )
            # a page may carry a placeholder offer next to the real one: prefer the one in stock
            if best is None or (best[3] != "in_stock" and candidate[3] == "in_stock"):
                best = candidate
    return best


def _walk_products(data):
    if isinstance(data, list):
        for item in data:
            yield from _walk_products(item)
    elif isinstance(data, dict):
        kind = data.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "Product" in kinds:
            yield data
        for key in ("@graph", "mainEntity", "itemListElement", "item"):
            if key in data:
                yield from _walk_products(data[key])


def _offers(product: dict) -> list[dict]:
    offers = product.get("offers")
    if offers is None:
        return []
    return [o for o in (offers if isinstance(offers, list) else [offers]) if isinstance(o, dict)]


def _from_opengraph(tree: HTMLParser):
    meta: dict[str, str] = {}
    for node in tree.css("meta[property], meta[name]"):
        key = (node.attributes.get("property") or node.attributes.get("name") or "").lower()
        content = node.attributes.get("content")
        if key and content and key not in meta:
            meta[key] = content
    price = _money(meta.get("product:price:amount") or meta.get("og:price:amount"))
    if price is None:
        return None
    return (
        meta.get("og:title") or "",
        price,
        meta.get("product:price:currency") or meta.get("og:price:currency"),
        _availability(meta.get("product:availability") or meta.get("og:availability")),
        _condition(meta.get("product:condition")),
    )
