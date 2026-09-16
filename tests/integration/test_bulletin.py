"""The daily market bulletin: a short article the local assistant writes from the database."""

# ruff: noqa: F811  (fixtures imported from test_platform are re-bound as parameters)

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from euro2core.catalog.seed import get_source
from euro2core.domain.enums import Grade, ObservationKind
from euro2core.domain.models import MarketObservation, NewsItem, Notification
from euro2core.platform.bulletin import write_bulletin
from tests.integration.test_platform import _signup, catalog, client  # noqa: F401

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 16, 7, 0, tzinfo=UTC)


async def _sales(session, issue_id, rows):
    ebay = await get_source(session, "ebay")
    for i, (price, days_ago, marketplace) in enumerate(rows):
        session.add(
            MarketObservation(
                issue_id=issue_id,
                source_id=ebay.id,
                marketplace=marketplace,
                observation_kind=ObservationKind.SOLD,
                price=Decimal(str(price)),
                grade=Grade.UNC,
                listing_id=f"b{i}",
                listing_url=f"https://ebay.example/{i}",
                title_raw="2 Euro Deutschland 2006 A Schleswig-Holstein",
                match_confidence=0.96,
                observed_at=NOW - timedelta(days=days_ago, hours=1),
            )
        )
    await session.commit()


async def test_bulletin_reports_yesterdays_sales_where_they_happened_and_is_daily(
    session, catalog, client
):
    await _sales(
        session,
        catalog["de_a"],
        [(6.5, 0, "EBAY_DE"), (4.2, 0, "EBAY_ES"), (3.9, 3, "EBAY_DE"), (4.0, 5, "EBAY_ES")],
    )
    auth = await _signup(client, "reader@example.org")

    item = await write_bulletin(session, now=NOW)
    await session.commit()

    assert item is not None and item.kind == "bulletin"
    assert "16" in item.title_es and "septiembre" in item.title_es.lower()
    body = item.body_es
    assert "Ventas destacadas" in body
    assert "6,50" in body and "eBay Alemania" in body
    assert "Schleswig-Holstein" in body
    assert "Cifra del día" in body
    # one per day: running again returns the same item and creates no second copy
    again = await write_bulletin(session, now=NOW + timedelta(hours=5))
    assert again is not None and again.id == item.id
    assert (
        len((await session.scalars(select(NewsItem).where(NewsItem.kind == "bulletin"))).all()) == 1
    )
    # readers get one notification; the news feed shows the bulletin first
    notes = (
        await session.scalars(select(Notification).where(Notification.kind == "bulletin"))
    ).all()
    assert len(notes) == 1
    feed = (await client.get("/news", headers=auth)).json()["items"]
    assert feed[0]["kind"] == "bulletin"


async def test_quiet_market_still_gets_a_short_bulletin_without_empty_sections(session, catalog):
    # a week after the fixture coins were added, with no sales at all
    item = await write_bulletin(session, now=datetime.now(UTC) + timedelta(days=7))
    assert item is not None
    assert "Ventas destacadas" not in item.body_es
    assert "tranquil" in item.body_es.lower()


async def test_chat_answers_what_happened_today_with_the_bulletin(session, catalog, client):
    await _sales(session, catalog["de_a"], [(6.5, 0, "EBAY_DE"), (4.2, 0, "EBAY_ES")])
    await write_bulletin(session, now=NOW)
    await session.commit()
    r = await client.post("/assistant/chat", json={"message": "¿qué ha pasado hoy en el mercado?"})
    assert r.status_code == 200, r.text
    assert r.json()["intent"] == "bulletin"
    assert "Ventas destacadas" in r.json()["text"]
