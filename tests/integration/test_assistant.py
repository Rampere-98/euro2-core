"""Market assistant end to end: snapshot per coin, deals, sell advice, watchlist notifications."""

# ruff: noqa: F811  (fixtures imported from test_platform are re-bound as parameters)

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from euro2core.catalog.seed import get_source
from euro2core.domain.enums import Grade, ObservationKind
from euro2core.domain.models import MarketObservation, Notification
from euro2core.platform.market_assistant import notify_watchers
from tests.integration.test_platform import _signup, catalog, client  # noqa: F401

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


async def _seed_market(session, issue_id, *, prices, asks=(), lot_price=None):
    ebay = await get_source(session, "ebay")
    rows = []
    for i, (price, days) in enumerate(prices):
        rows.append(
            MarketObservation(
                issue_id=issue_id,
                source_id=ebay.id,
                marketplace="EBAY_DE" if i % 2 else "EBAY_ES",
                observation_kind=ObservationKind.SOLD,
                price=Decimal(str(price)),
                grade=Grade.UNC,
                listing_id=f"s{i}",
                listing_url=f"https://ebay.de/itm/s{i}",
                title_raw="2 Euro Deutschland 2006 A Schleswig-Holstein",
                match_confidence=0.96,
                observed_at=NOW - timedelta(days=days),
            )
        )
    for i, price in enumerate(asks):
        rows.append(
            MarketObservation(
                issue_id=issue_id,
                source_id=ebay.id,
                marketplace="EBAY_ES",
                observation_kind=ObservationKind.ASKING,
                price=Decimal(str(price)),
                grade=Grade.UNC,
                listing_id=f"a{i}",
                listing_url=f"https://ebay.es/itm/a{i}",
                title_raw="2 euros Alemania 2006 A Schleswig-Holstein",
                match_confidence=0.96,
                observed_at=NOW - timedelta(days=1),
            )
        )
    if lot_price is not None:
        rows.append(
            MarketObservation(
                issue_id=issue_id,
                source_id=ebay.id,
                marketplace="EBAY_ES",
                observation_kind=ObservationKind.ASKING,
                price=Decimal(str(lot_price)),
                grade=Grade.UNC,
                listing_id="lot",
                listing_url="https://ebay.es/itm/lot",
                title_raw="Lote 10 monedas 2 euros Alemania 2006",
                match_confidence=0.96,
                observed_at=NOW - timedelta(days=1),
            )
        )
    session.add_all(rows)
    await session.commit()


SALES = [(3.0, 5), (3.5, 12), (4.0, 20), (3.8, 40), (3.2, 70), (6.0, 200), (5.5, 300)]


async def test_type_market_reports_range_band_offers_and_chart(client, catalog, session):
    await _seed_market(session, catalog["de_a"], prices=SALES, asks=(2.5, 9.0), lot_price=1.0)
    r = await client.get(f"/types/{catalog['de_type']}/market")
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["realized"]["n"] == 5
    assert (m["realized"]["min"], m["realized"]["max"]) == ("3.00", "4.00")
    assert m["band"]["basis"] == "sold"
    assert m["buy"]["verdict"] == "buy_now"
    assert m["buy"]["cheapest"]["price"] == "2.50"
    assert m["buy"]["cheapest"]["url"].startswith("https://ebay.es/")
    assert [o["price"] for o in m["offers"]] == ["2.50", "9.00"]
    assert m["ignored"][0]["reasons"] == ["lot"]
    assert len(m["history"]) == 24 and m["history"][-1]["sold_n"] >= 1
    assert m["trend_pct"] < 0


async def test_deals_feed_lists_bargains_with_links(client, catalog, session):
    await _seed_market(session, catalog["de_a"], prices=SALES, asks=(2.5, 3.6))
    deals = (await client.get("/market/deals")).json()
    assert len(deals) == 1
    assert deals[0]["listing"]["price"] == "2.50"
    assert deals[0]["listing"]["discount_pct"] > 15
    assert deals[0]["type"]["id"] == str(catalog["de_type"])


async def test_sell_advice_for_my_piece(client, catalog, session):
    await _seed_market(session, catalog["de_a"], prices=SALES)
    auth = await _signup(client, "seller2@example.org")
    r = await client.post(
        "/me/collection", json={"issue_id": str(catalog["de_a"]), "grade": "bu"}, headers=auth
    )
    item_id = r.json()["id"]
    advice = (await client.get(f"/me/collection/{item_id}/sell-advice", headers=auth)).json()
    assert advice["grade"] == "bu"
    assert Decimal(advice["start"]) > Decimal(advice["floor"])
    assert Decimal(advice["net_ebay"]) < Decimal(advice["start"])
    assert advice["expected_days"] == 18
    assert advice["best_marketplace"] in {"EBAY_DE", "EBAY_ES"}


async def test_watchlist_notifies_deals_once(client, catalog, session):
    await _seed_market(session, catalog["de_a"], prices=SALES, asks=(2.5,))
    auth = await _signup(client, "watcher@example.org")
    r = await client.post("/me/watchlist", json={"type_id": str(catalog["de_type"])}, headers=auth)
    assert r.status_code == 201
    watching = (await client.get("/me/watchlist", headers=auth)).json()
    assert watching[0]["buy"]["verdict"] == "buy_now"

    assert await notify_watchers(session) == 2  # a deal and a > 20 % move
    await session.commit()
    assert await notify_watchers(session) == 0  # not repeated
    kinds = sorted(
        (
            await session.scalars(
                select(Notification.kind).where(Notification.kind != "achievement")
            )
        ).all()
    )
    assert kinds == ["deal", "price_move"]
    listed = (await client.get("/me/notifications", headers=auth)).json()
    assert any(n["kind"] == "deal" and "Chollo" in n["title"] for n in listed)

    assert (
        await client.delete(f"/me/watchlist/{catalog['de_type']}", headers=auth)
    ).status_code == 204
    assert (await client.get("/me/watchlist", headers=auth)).json() == []


async def test_alerts_do_not_require_pro_any_more(client, catalog):
    auth = await _signup(client, "free@example.org")
    body = {"issue_id": str(catalog["de_a"]), "direction": "below", "threshold": "3"}
    assert (await client.post("/me/alerts", json=body, headers=auth)).status_code == 201


async def test_collectors_own_purchases_and_sales_feed_the_market(client, catalog, session):
    """No external API: what users pay and sell for becomes the app's own market data."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from euro2core.domain.models import CollectionItem

    buyer = await _signup(client, "own1@example.org")
    for price in ("3.50", "4.00", "3.80", "3.20", "4.20"):
        r = await client.post(
            "/me/collection",
            json={
                "issue_id": str(catalog["de_a"]),
                "grade": "unc",
                "acquired_price": price,
                "acquired_at": (datetime.now(UTC) - timedelta(days=10)).isoformat(),
            },
            headers=buyer,
        )
        assert r.status_code == 201, r.text
    gift = await client.post(
        "/me/collection",
        json={"issue_id": str(catalog["de_a"]), "grade": "unc", "acquired_price": "0.50"},
        headers=buyer,
    )
    assert gift.status_code == 201  # kept in the collection, not counted as a market price

    m = (await client.get(f"/types/{catalog['de_type']}/market")).json()
    assert m["realized"]["n"] == 5
    assert m["band"]["basis"] == "sold"
    assert (m["realized"]["min"], m["realized"]["max"]) == ("3.20", "4.20")

    # a peer listing is an offer; accepting an offer turns it into a sale
    seller = await _signup(client, "own2@example.org")
    piece = CollectionItem(
        user_id=seller["_id"], issue_id=catalog["de_a"], grade="unc", verified_at=datetime.now(UTC)
    )
    session.add(piece)
    await session.commit()
    listing = (
        await client.post(
            "/market/listings", json={"item_id": str(piece.id), "price": "2.90"}, headers=seller
        )
    ).json()
    m = (await client.get(f"/types/{catalog['de_type']}/market")).json()
    assert m["buy"]["verdict"] == "buy_now" and m["buy"]["cheapest"]["url"].startswith("euro2://")
    offer = (
        await client.post(
            f"/market/listings/{listing['id']}/offers", json={"amount": "2.90"}, headers=buyer
        )
    ).json()
    assert (
        await client.post(f"/market/offers/{offer['id']}/accept", headers=seller)
    ).status_code == 200
    m = (await client.get(f"/types/{catalog['de_type']}/market")).json()
    assert m["buy"]["verdict"] == "no_offers"
    assert m["realized"]["n"] == 6 and m["realized"]["min"] == "2.90"
    sold_urls = (
        await session.scalars(
            select(CollectionItem.id).where(CollectionItem.user_id == buyer["_id"])
        )
    ).all()
    assert len(sold_urls) == 7  # 6 purchases + the piece bought from the peer


async def test_a_collector_can_keep_a_purchase_price_private(client, catalog):
    from datetime import UTC, datetime

    buyer = await _signup(client, "private@example.org")
    r = await client.post(
        "/me/collection",
        json={
            "issue_id": str(catalog["de_a"]),
            "grade": "unc",
            "acquired_price": "50",
            "acquired_at": datetime.now(UTC).isoformat(),
            "share_price": False,
        },
        headers=buyer,
    )
    assert r.status_code == 201
    m = (await client.get(f"/types/{catalog['de_type']}/market")).json()
    assert m["realized"] is None  # nothing entered the market data
