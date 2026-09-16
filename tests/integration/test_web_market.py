"""The open-web reader end to end, with the network mocked: search -> shop pages -> observations."""

# ruff: noqa: F811  (fixtures imported from test_platform are re-bound as parameters)

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select

from euro2core.domain.enums import ObservationKind
from euro2core.domain.models import CoinType, MarketObservation, MarketSite
from euro2core.platform.web_market import search_coin, sites
from euro2core.sources.web.fetcher import PoliteFetcher
from tests.integration.test_platform import catalog, client  # noqa: F401

pytestmark = pytest.mark.integration
FIX = Path(__file__).parent.parent / "fixtures" / "html"

DDG = "https://html.duckduckgo.com/html/"


def _shop_page(title: str, price: str, availability: str = "instock") -> str:
    return f"""<html><head><title>{title}</title>
    <meta property="og:title" content="{title}">
    <meta property="product:price:amount" content="{price}">
    <meta property="product:price:currency" content="EUR">
    <meta property="product:availability" content="{availability}">
    </head><body></body></html>"""


def _ddg(*urls: str) -> str:
    from urllib.parse import quote

    return (
        "<html><body>"
        + "".join(
            f'<a class="result__a" href="//duckduckgo.com/l/?uddg={quote(u, safe="")}&rut=x">r</a>'
            for u in urls
        )
        + "</body></html>"
    )


@respx.mock
async def test_shop_pages_become_asks_and_sold_out_pages_become_sales(session, catalog):
    coin_type = await session.get(CoinType, catalog["de_type"])  # Germany 2006 Schleswig-Holstein
    respx.get(url__regex=r".*/robots\.txt").mock(return_value=httpx.Response(404))
    respx.get(url__startswith=DDG).mock(
        return_value=httpx.Response(
            200,
            text=_ddg(
                "https://tienda-a.example/2-euros-alemania-2006-schleswig-holstein",
                "https://tienda-b.example/de-2006-sh",
                "https://tienda-c.example/otra-cosa",
            ),
        )
    )
    respx.get("https://tienda-a.example/2-euros-alemania-2006-schleswig-holstein").mock(
        return_value=httpx.Response(
            200, text=_shop_page("2 Euros Alemania 2006 Schleswig-Holstein A", "4.50")
        )
    )
    respx.get("https://tienda-b.example/de-2006-sh").mock(
        return_value=httpx.Response(
            200,
            text=_shop_page("2 Euro Deutschland 2006 Schleswig-Holstein", "5.90", "out of stock"),
        )
    )
    respx.get("https://tienda-c.example/otra-cosa").mock(
        return_value=httpx.Response(200, text="<html><head><title>Blog</title></head></html>")
    )

    fetcher = PoliteFetcher("euro2-core-test")
    fetcher_now = datetime(2026, 9, 16, 12, tzinfo=UTC)
    result = await search_coin(session, fetcher, coin_type, "Schleswig-Holstein", now=fetcher_now)
    await session.commit()

    assert result.queries == 2
    assert len(result.products) == 2
    assert result.ingest is not None and result.ingest.stored == 2
    rows = (
        await session.scalars(
            select(MarketObservation).where(MarketObservation.marketplace == "WEB")
        )
    ).all()
    by_kind = {r.observation_kind: r for r in rows}
    assert by_kind[ObservationKind.ASKING].price == Decimal("4.50")
    assert by_kind[ObservationKind.SOLD].price == Decimal("5.90")
    assert by_kind[ObservationKind.SOLD].ends_at == fetcher_now
    assert all(r.listing_url.startswith("https://tienda-") for r in rows)
    hosts = {s.host: s for s in await sites(session)}
    assert hosts["tienda-a.example"].listings_found == 1
    assert (
        hosts["tienda-c.example"].pages_read == 1 and hosts["tienda-c.example"].listings_found == 0
    )


@respx.mock
async def test_refusing_hosts_are_paused_and_disabled_sites_are_skipped(session, catalog):
    coin_type = await session.get(CoinType, catalog["de_type"])
    session.add(MarketSite(host="apagada.example", enabled=False))
    await session.commit()
    respx.get(url__regex=r".*/robots\.txt").mock(return_value=httpx.Response(404))
    respx.get(url__startswith=DDG).mock(
        return_value=httpx.Response(
            200, text=_ddg("https://bloquea.example/p1", "https://apagada.example/p2")
        )
    )
    blocked = respx.get("https://bloquea.example/p1").mock(return_value=httpx.Response(403))
    off = respx.get("https://apagada.example/p2").mock(
        return_value=httpx.Response(200, text=_shop_page("2 Euros Alemania 2006", "4"))
    )

    fetcher = PoliteFetcher("euro2-core-test")
    result = await search_coin(session, fetcher, coin_type, "Schleswig-Holstein")
    await session.commit()

    assert blocked.called and not off.called
    assert result.pages == 0 and result.products == []
    site = await session.get(MarketSite, "bloquea.example")
    assert site.paused_until is not None and "403" in (site.last_error or "")
    # the same host is not asked again within the pause
    assert fetcher.is_paused("bloquea.example")


@respx.mock
async def test_robots_txt_is_honoured_before_any_page_is_read(session, catalog):
    coin_type = await session.get(CoinType, catalog["de_type"])
    respx.get("https://html.duckduckgo.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(url__startswith=DDG).mock(
        return_value=httpx.Response(200, text=_ddg("https://cerrado.example/s/item"))
    )
    respx.get("https://cerrado.example/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /s/\n")
    )
    page = respx.get("https://cerrado.example/s/item").mock(
        return_value=httpx.Response(200, text=_shop_page("2 Euros Alemania 2006", "4"))
    )
    result = await search_coin(session, PoliteFetcher("euro2-core-test"), coin_type, None)
    assert not page.called
    assert result.products == [] and any("robots" in r for r in result.refused)


@respx.mock
async def test_on_demand_search_endpoint_refreshes_the_market_view(client, catalog):
    respx.get(url__regex=r".*/robots\.txt").mock(return_value=httpx.Response(404))
    respx.get(url__startswith=DDG).mock(
        return_value=httpx.Response(200, text=_ddg("https://tienda.example/de-2006"))
    )
    respx.get("https://tienda.example/de-2006").mock(
        return_value=httpx.Response(
            200, text=_shop_page("2 Euros Alemania 2006 Schleswig-Holstein A", "4.20")
        )
    )
    r = await client.post(f"/types/{catalog['de_type']}/market/search")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] == 1 and body["stored"] == 1
    offers = body["market"]["offers"]
    assert offers and offers[0]["marketplace"] == "WEB" and offers[0]["price"] == "4.20"
    assert offers[0]["url"] == "https://tienda.example/de-2006"
    # the admin panel lists the site the reader met
    from tests.integration.test_platform import _signup

    admin = await _signup(client, "owner@example.org")
    sites_out = (await client.get("/admin/sites", headers=admin)).json()
    assert sites_out[0]["host"] == "tienda.example" and sites_out[0]["listings_found"] == 1
    off = await client.patch("/admin/sites/tienda.example", json={"enabled": False}, headers=admin)
    assert off.json()["enabled"] is False
