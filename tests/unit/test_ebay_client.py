import base64
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from euro2core.domain.enums import ObservationKind
from euro2core.sources.ebay.client import BROWSE_BASE, TOKEN_URL, EbayClient
from euro2core.sources.ebay.parser import closed_auction_from_item, listing_from_summary

SUMMARY = {
    "itemId": "v1|123|0",
    "title": "2 Euro Deutschland 2006 Schleswig-Holstein A Stempelglanz",
    "price": {"value": "12.50", "currency": "EUR"},
    "buyingOptions": ["FIXED_PRICE"],
    "itemWebUrl": "https://www.ebay.de/itm/123",
    "condition": "Used",
    "itemEndDate": "2026-10-01T10:00:00.000Z",
}
AUCTION = {
    "itemId": "v1|456|0",
    "title": "2 Euro Vatikan 2004 Gründung Vatikanstaat",
    "currentBidPrice": {"value": "41.00", "currency": "EUR"},
    "bidCount": 7,
    "buyingOptions": ["AUCTION"],
    "itemWebUrl": "https://www.ebay.de/itm/456",
    "itemEndDate": "2026-09-20T18:00:00.000Z",
}


@pytest.fixture
def client() -> EbayClient:
    return EbayClient(
        client_id="app", client_secret="cert", user_agent="t", requests_per_second=1000
    )


def _token_route():
    return respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
    )


@respx.mock
async def test_fetches_a_client_credentials_token_once_and_reuses_it(client):
    token = _token_route()
    search = respx.get(f"{BROWSE_BASE}/item_summary/search").mock(
        return_value=httpx.Response(200, json={"total": 1, "itemSummaries": [SUMMARY]})
    )
    await client.search("2 euro", marketplace="EBAY_DE")
    await client.search("2 euro", marketplace="EBAY_ES")
    assert token.call_count == 1
    auth = token.calls[0].request.headers["Authorization"]
    assert auth == "Basic " + base64.b64encode(b"app:cert").decode()
    assert b"grant_type=client_credentials" in token.calls[0].request.content
    assert b"api_scope" in token.calls[0].request.content
    req = search.calls.last.request
    assert req.headers["Authorization"] == "Bearer tok"
    assert req.headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_ES"
    assert req.url.params["q"] == "2 euro"
    assert "buyingOptions" in req.url.params["filter"]


@respx.mock
async def test_search_follows_pagination_until_total(client):
    _token_route()
    pages = [
        httpx.Response(
            200, json={"total": 3, "limit": 2, "offset": 0, "itemSummaries": [SUMMARY, AUCTION]}
        ),
        httpx.Response(200, json={"total": 3, "limit": 2, "offset": 2, "itemSummaries": [SUMMARY]}),
    ]
    route = respx.get(f"{BROWSE_BASE}/item_summary/search").mock(side_effect=pages)
    items = await client.search("2 euro", marketplace="EBAY_DE", page_size=2)
    assert len(items) == 3
    assert route.call_count == 2
    assert route.calls[1].request.url.params["offset"] == "2"


@respx.mock
async def test_expired_token_is_refreshed_on_401(client):
    token = respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "old", "expires_in": 7200}),
            httpx.Response(200, json={"access_token": "new", "expires_in": 7200}),
        ]
    )
    respx.get(f"{BROWSE_BASE}/item/v1%7C1%7C0").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={"itemId": "v1|1|0"})]
    )
    item = await client.get_item("v1|1|0", marketplace="EBAY_DE")
    assert item["itemId"] == "v1|1|0"
    assert token.call_count == 2


@respx.mock
async def test_daily_budget_stops_calls_before_ebay_does(client):
    _token_route()
    respx.get(f"{BROWSE_BASE}/item_summary/search").mock(
        return_value=httpx.Response(200, json={"total": 0, "itemSummaries": []})
    )
    client.daily_budget = 2
    await client.search("a", marketplace="EBAY_DE")
    await client.search("b", marketplace="EBAY_DE")
    with pytest.raises(RuntimeError, match="budget"):
        await client.search("c", marketplace="EBAY_DE")


def test_summary_becomes_asking_listing():
    listing = listing_from_summary(SUMMARY, "EBAY_DE", observed_at=datetime(2026, 9, 1, tzinfo=UTC))
    assert listing.kind == ObservationKind.ASKING
    assert listing.price == Decimal("12.50")
    assert listing.listing_id == "v1|123|0"
    assert listing.end_date == datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


def test_live_auction_becomes_auction_open_and_non_eur_is_dropped():
    listing = listing_from_summary(AUCTION, "EBAY_DE")
    assert listing.kind == ObservationKind.AUCTION_OPEN
    assert listing.price == Decimal("41.00")
    assert listing.bid_count == 7
    gbp = {**SUMMARY, "price": {"value": "10", "currency": "GBP"}}
    assert listing_from_summary(gbp, "EBAY_DE") is None


def test_ended_auction_with_bids_is_a_realized_sale_but_unsold_is_not():
    now = datetime(2026, 9, 21, tzinfo=UTC)
    sale = closed_auction_from_item(AUCTION, "EBAY_DE", observed_at=now)
    assert sale.kind == ObservationKind.AUCTION_CLOSED
    assert sale.observed_at == datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
    assert closed_auction_from_item({**AUCTION, "bidCount": 0}, "EBAY_DE", observed_at=now) is None
    still_live = datetime(2026, 9, 19, tzinfo=UTC)
    assert closed_auction_from_item(AUCTION, "EBAY_DE", observed_at=still_live) is None
