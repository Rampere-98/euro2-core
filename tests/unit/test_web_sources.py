"""Key-free market readers: any shop page with standard product data, plus open discovery."""

from decimal import Decimal
from pathlib import Path

import pytest

from euro2core.sources.web.discovery import search_result_urls
from euro2core.sources.web.product import parse_product
from euro2core.sources.web.queries import shop_queries

FIX = Path(__file__).parent.parent / "fixtures" / "html"


def test_json_ld_product_offer_gives_title_price_and_currency():
    page = parse_product(
        (FIX / "shop_jsonld.html").read_text("utf-8"), "https://www.2eur.es/monaco"
    )
    assert page is not None
    assert page.price == Decimal("3600")
    assert page.currency == "EUR"
    assert "Grace Kelly" in page.title
    assert page.host == "2eur.es"
    # the first Product block carries a placeholder 0.00 "out of stock" offer; the real one
    # (priced, no availability given) wins and does not inherit that flag
    assert page.availability is None


def test_opengraph_product_tags_are_enough_when_there_is_no_json_ld():
    page = parse_product(
        (FIX / "shop_opengraph.html").read_text("utf-8"), "https://finumas.es/x.html"
    )
    assert page is not None
    assert page.price == Decimal("4600")
    assert page.currency == "EUR"
    assert page.title.startswith("2 EUROS CONMEMORATIVOS MONACO 2007")


def test_out_of_stock_pages_report_it_so_they_can_count_as_a_sale_signal():
    page = parse_product(
        (FIX / "shop_woocommerce.html").read_text("utf-8"), "https://numismaticaromacoins.com/p/"
    )
    assert page is not None
    assert page.price == Decimal("4490.00")
    assert page.availability == "sold_out"


def test_pages_without_a_price_are_not_products():
    assert (
        parse_product("<html><head><title>Blog</title></head></html>", "https://x.org/post") is None
    )
    assert (
        parse_product(
            '<html><head><meta property="product:price:amount" content="0"></head></html>',
            "https://x.org/p",
        )
        is None
    )


def test_duckduckgo_results_are_decoded_and_ads_and_non_shops_dropped():
    urls = search_result_urls((FIX / "ddg_results.html").read_text("utf-8"))
    assert (
        "https://finumas.es/2-conmemorativos-monaco/3994-2-euros-conmemorativos-monaco-2007-grace-kelly.html"
        in urls
    )
    assert "https://www.2eur.es/monaco-2-unc-2007-grace-kelly" in urls
    assert not any("duckduckgo.com/y.js" in u for u in urls)  # ads
    assert not any("numista.com" in u for u in urls)  # catalog, not a shop
    assert not any("ebay.com/sch/" in u for u in urls)  # search pages eBay forbids to bots
    assert len(urls) == len(set(urls))


@pytest.mark.parametrize(
    ("country", "year", "title", "expected"),
    [
        ("MC", 2007, "Grace Kelly", "2 euros Mónaco 2007 Grace Kelly comprar"),
        ("DE", 2006, "Schleswig-Holstein", "2 Euro Deutschland 2006 Schleswig-Holstein kaufen"),
    ],
)
def test_shop_queries_are_phrased_in_the_shopper_language(country, year, title, expected):
    assert expected in shop_queries(country_code=country, year=year, title=title)
