import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from euro2core.catalog.ingest_ecb import ingest_ecb_entries
from euro2core.catalog.ingest_numista import ingest_numista_type
from euro2core.catalog.seed import ensure_reference_data
from euro2core.domain.enums import ObservationKind, SyncStatus
from euro2core.domain.models import MarketObservation
from euro2core.scheduler.jobs import run_auction_close_check, run_ebay_market
from euro2core.sources.ebay.client import BROWSE_BASE, TOKEN_URL
from euro2core.sources.ebay.queries import search_query
from euro2core.sources.ecb.parser import EcbEntry
from euro2core.sources.numista.parser import parse_issue, parse_type

pytestmark = pytest.mark.integration

FIX = Path(__file__).parent.parent / "fixtures" / "numista"
NOW = datetime.now(UTC)

FIXED = {
    "itemId": "v1|100|0",
    "title": "2 Euro Deutschland 2006 Schleswig-Holstein A Stempelglanz",
    "price": {"value": "12.50", "currency": "EUR"},
    "buyingOptions": ["FIXED_PRICE"],
    "itemWebUrl": "https://www.ebay.de/itm/100",
}
AUCTION = {
    "itemId": "v1|200|0",
    "title": "2 Euro Deutschland 2006 Schleswig-Holstein J",
    "currentBidPrice": {"value": "3.00", "currency": "EUR"},
    "bidCount": 2,
    "buyingOptions": ["AUCTION"],
    "itemWebUrl": "https://www.ebay.de/itm/200",
    "itemEndDate": (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
}


@pytest.fixture
async def catalog(session):
    await ensure_reference_data(session)
    await ingest_ecb_entries(
        session,
        [
            EcbEntry(
                year=2006,
                country_code="DE",
                country_name="Germany",
                feature="Schleswig-Holstein",
                description="",
                mintage=None,
                mintage_raw="",
                issue_date_raw="",
            )
        ],
        fetcher=None,
    )
    await ingest_numista_type(
        session,
        parse_type(json.loads((FIX / "type_2169.json").read_text("utf-8"))),
        [parse_issue(i) for i in json.loads((FIX / "type_2169_issues.json").read_text("utf-8"))],
        translations=[],
        fetcher=None,
    )
    await session.commit()


def _token():
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
    )


def test_search_query_uses_the_marketplace_language():
    assert search_query("DE", 2006, "EBAY_DE") == "2 euro deutschland 2006"
    assert search_query("DE", 2006, "EBAY_ES") == "2 euros alemania 2006"
    assert search_query("VA", 2004, "EBAY_IT") == "2 euro vaticano 2004"
    assert search_query("NL", 2013, "EBAY_FR") == "2 euros pays-bas 2013"


@respx.mock
async def test_market_job_searches_each_country_year_and_stores_listings(engine, catalog):
    _token()
    search = respx.get(f"{BROWSE_BASE}/item_summary/search").mock(
        return_value=httpx.Response(200, json={"total": 2, "itemSummaries": [FIXED, AUCTION]})
    )
    run = await run_ebay_market(
        engine,
        client_id="a",
        client_secret="b",
        user_agent="t",
        marketplaces=["EBAY_DE", "EBAY_ES"],
    )
    assert run.status == SyncStatus.SUCCEEDED, run.error
    assert run.stats["queries"] == 2
    assert run.stats["listings_stored"] == 4
    assert search.calls[0].request.url.params["q"] == "2 euro deutschland 2006"
    async with async_sessionmaker(engine)() as s:
        rows = (await s.scalars(select(MarketObservation))).all()
    assert {(r.marketplace, r.observation_kind) for r in rows} == {
        ("EBAY_DE", ObservationKind.ASKING),
        ("EBAY_DE", ObservationKind.AUCTION_OPEN),
        ("EBAY_ES", ObservationKind.ASKING),
        ("EBAY_ES", ObservationKind.AUCTION_OPEN),
    }
    assert all(
        r.ends_at is not None for r in rows if r.observation_kind == ObservationKind.AUCTION_OPEN
    )


@respx.mock
async def test_market_job_keeps_a_cursor_when_the_budget_runs_out(engine, catalog):
    _token()
    respx.get(f"{BROWSE_BASE}/item_summary/search").mock(
        return_value=httpx.Response(200, json={"total": 0, "itemSummaries": []})
    )
    run = await run_ebay_market(
        engine,
        client_id="a",
        client_secret="b",
        user_agent="t",
        marketplaces=["EBAY_DE", "EBAY_ES"],
        daily_budget=1,
    )
    assert run.status == SyncStatus.FAILED
    assert "budget" in run.error
    assert run.cursor["done"] == ["DE/2006/EBAY_DE"]


@respx.mock
async def test_auction_close_check_turns_ended_auctions_into_sales(engine, catalog):
    _token()
    respx.get(f"{BROWSE_BASE}/item_summary/search").mock(
        return_value=httpx.Response(200, json={"total": 1, "itemSummaries": [AUCTION]})
    )
    await run_ebay_market(
        engine, client_id="a", client_secret="b", user_agent="t", marketplaces=["EBAY_DE"]
    )
    respx.get(f"{BROWSE_BASE}/item/v1%7C200%7C0").mock(
        return_value=httpx.Response(
            200,
            json={
                **AUCTION,
                "currentBidPrice": {"value": "7.50", "currency": "EUR"},
                "bidCount": 5,
            },
        )
    )

    run = await run_auction_close_check(engine, client_id="a", client_secret="b", user_agent="t")

    assert run.status == SyncStatus.SUCCEEDED, run.error
    assert run.stats["checked"] == 1
    assert run.stats["sold"] == 1
    async with async_sessionmaker(engine)() as s:
        rows = (await s.scalars(select(MarketObservation))).all()
    kinds = {r.observation_kind: r for r in rows}
    assert set(kinds) == {ObservationKind.AUCTION_CLOSED}
    assert float(kinds[ObservationKind.AUCTION_CLOSED].price) == 7.5


@respx.mock
async def test_auction_close_check_drops_unsold_auctions(engine, catalog):
    _token()
    respx.get(f"{BROWSE_BASE}/item_summary/search").mock(
        return_value=httpx.Response(200, json={"total": 1, "itemSummaries": [AUCTION]})
    )
    await run_ebay_market(
        engine, client_id="a", client_secret="b", user_agent="t", marketplaces=["EBAY_DE"]
    )
    respx.get(f"{BROWSE_BASE}/item/v1%7C200%7C0").mock(
        return_value=httpx.Response(200, json={**AUCTION, "bidCount": 0})
    )
    run = await run_auction_close_check(engine, client_id="a", client_secret="b", user_agent="t")
    assert run.stats["unsold"] == 1
    async with async_sessionmaker(engine)() as s:
        assert (await s.scalars(select(MarketObservation))).all() == []


@respx.mock
async def test_gone_auction_does_not_block_the_queue(engine, catalog):
    _token()
    second = {**AUCTION, "itemId": "v1|201|0", "itemWebUrl": "https://www.ebay.de/itm/201"}
    respx.get(f"{BROWSE_BASE}/item_summary/search").mock(
        return_value=httpx.Response(200, json={"total": 2, "itemSummaries": [AUCTION, second]})
    )
    await run_ebay_market(
        engine, client_id="a", client_secret="b", user_agent="t", marketplaces=["EBAY_DE"]
    )
    respx.get(f"{BROWSE_BASE}/item/v1%7C200%7C0").mock(return_value=httpx.Response(404))
    respx.get(f"{BROWSE_BASE}/item/v1%7C201%7C0").mock(
        return_value=httpx.Response(200, json={**second, "bidCount": 3})
    )

    run = await run_auction_close_check(engine, client_id="a", client_secret="b", user_agent="t")

    assert run.status == SyncStatus.SUCCEEDED, run.error
    assert run.stats == {"checked": 2, "sold": 1, "unsold": 0, "gone": 1, "still_open": 0}
    async with async_sessionmaker(engine)() as s:
        rows = (await s.scalars(select(MarketObservation))).all()
    assert [(r.listing_id, r.observation_kind) for r in rows] == [
        ("v1|201|0", ObservationKind.AUCTION_CLOSED)
    ]


@respx.mock
async def test_closed_sale_inherits_issue_and_grade_from_the_open_auction(engine, catalog):
    _token()
    respx.get(f"{BROWSE_BASE}/item_summary/search").mock(
        return_value=httpx.Response(200, json={"total": 1, "itemSummaries": [AUCTION]})
    )
    await run_ebay_market(
        engine, client_id="a", client_secret="b", user_agent="t", marketplaces=["EBAY_DE"]
    )
    async with async_sessionmaker(engine)() as s:
        open_row = (await s.scalars(select(MarketObservation))).one()
        open_issue, open_conf = open_row.issue_id, open_row.match_confidence
    # eBay now returns a title the matcher could not place at all
    respx.get(f"{BROWSE_BASE}/item/v1%7C200%7C0").mock(
        return_value=httpx.Response(200, json={**AUCTION, "title": "???", "bidCount": 3})
    )
    run = await run_auction_close_check(engine, client_id="a", client_secret="b", user_agent="t")
    assert run.stats["sold"] == 1
    async with async_sessionmaker(engine)() as s:
        sale = (await s.scalars(select(MarketObservation))).one()
    assert sale.observation_kind == ObservationKind.AUCTION_CLOSED
    assert sale.issue_id == open_issue
    assert sale.match_confidence == open_conf
