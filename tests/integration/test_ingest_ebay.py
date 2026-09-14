import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from euro2core.catalog.ingest_ebay import ingest_listings
from euro2core.catalog.ingest_ecb import ingest_ecb_entries
from euro2core.catalog.ingest_numista import ingest_numista_type
from euro2core.catalog.seed import ensure_reference_data
from euro2core.domain.enums import Finish, Grade, ObservationKind
from euro2core.domain.models import CoinIssue, MarketObservation
from euro2core.pricing.matcher import match_listing
from euro2core.sources.ebay.parser import Listing
from euro2core.sources.ecb.parser import EcbEntry
from euro2core.sources.numista.parser import parse_issue, parse_type

pytestmark = pytest.mark.integration

FIX = Path(__file__).parent.parent / "fixtures" / "numista"
NOW = datetime(2026, 9, 1, tzinfo=UTC)


def load(name: str):
    return json.loads((FIX / name).read_text("utf-8"))


def listing(
    title, price=3.5, kind=ObservationKind.ASKING, listing_id="v1|1|0", marketplace="EBAY_DE"
):
    return Listing(
        listing_id=listing_id,
        marketplace=marketplace,
        title=title,
        price=Decimal(str(price)),
        currency="EUR",
        kind=kind,
        url=f"https://www.ebay.de/itm/{listing_id}",
        observed_at=NOW,
        end_date=None,
        condition="Used",
    )


@pytest.fixture
async def germany_2006(session):
    """ECB + Numista for Schleswig-Holstein plus a second German 2006 type without variants."""
    await ensure_reference_data(session)
    for feature in ("Schleswig-Holstein", "Some other 2006 theme"):
        await ingest_ecb_entries(
            session,
            [
                EcbEntry(
                    year=2006,
                    country_code="DE",
                    country_name="Germany",
                    feature=feature,
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
        parse_type(load("type_2169.json")),
        [parse_issue(i) for i in load("type_2169_issues.json")],
        translations=[],
        fetcher=None,
    )
    await session.commit()
    return session


async def test_matches_german_listing_to_the_exact_mint_and_finish(germany_2006):
    session = germany_2006
    m = await match_listing(
        session, "2 Euro Deutschland 2006 Schleswig-Holstein Holstentor A Stempelglanz"
    )
    assert m is not None
    issue = await session.get(CoinIssue, m.issue_id)
    assert issue.mint_mark == "A"
    assert issue.finish == Finish.BU
    assert m.confidence >= 0.85
    assert m.grade == Grade.BU


async def test_listing_without_mint_mark_matches_but_below_the_scoring_threshold(germany_2006):
    m = await match_listing(germany_2006, "2 Euro Alemania 2006 Schleswig-Holstein circulada")
    assert m is not None
    assert m.confidence < 0.85
    assert m.grade == Grade.CIRCULATED


async def test_lot_and_unrelated_listings_do_not_match(germany_2006):
    assert (
        await match_listing(germany_2006, "Lote 5 monedas 2 euros Alemania 2006 A D F G J") is None
    )
    assert await match_listing(germany_2006, "2 Euro France 2015 drapeau") is None
    assert await match_listing(germany_2006, "Moneda de 50 centimos 2006") is None


async def test_ingest_listings_upserts_observations_with_confidence_and_grade(germany_2006):
    session = germany_2006
    result = await ingest_listings(
        session,
        [
            listing(
                "2 Euro Deutschland 2006 Schleswig-Holstein A Stempelglanz", 12.0, listing_id="a"
            ),
            listing("2 Euro Deutschland 2006 Schleswig-Holstein J PP", 25.0, listing_id="b"),
            listing("2 Euro Alemania 2006 Schleswig-Holstein circulada", 3.0, listing_id="c"),
            listing("Lote 5 monedas 2 euros Alemania 2006", 15.0, listing_id="d"),
            listing(
                "2 Euro Deutschland 2006 Schleswig-Holstein A Stempelglanz", 12.5, listing_id="a"
            ),
        ],
    )
    await session.commit()

    assert result.stored == 3
    assert result.updated == 1
    assert result.discarded == 1
    rows = {r.listing_id: r for r in (await session.scalars(select(MarketObservation))).all()}
    assert set(rows) == {"a", "b", "c"}
    assert rows["a"].price == Decimal("12.50")  # same listing seen again: price refreshed
    assert rows["a"].grade == Grade.BU and rows["a"].match_confidence >= 0.85
    assert rows["b"].grade == Grade.PROOF
    assert rows["c"].match_confidence < 0.85


async def test_closed_auction_with_bids_becomes_a_realized_sale(germany_2006):
    session = germany_2006
    open_auction = listing(
        "2 Euro Deutschland 2006 Schleswig-Holstein A",
        4.0,
        kind=ObservationKind.AUCTION_OPEN,
        listing_id="x",
    )
    await ingest_listings(session, [open_auction])
    await session.commit()
    closed = listing(
        "2 Euro Deutschland 2006 Schleswig-Holstein A",
        6.5,
        kind=ObservationKind.AUCTION_CLOSED,
        listing_id="x",
    )
    await ingest_listings(session, [closed])
    await session.commit()
    rows = (
        await session.scalars(select(MarketObservation).where(MarketObservation.listing_id == "x"))
    ).all()
    kinds = {r.observation_kind: r for r in rows}
    assert set(kinds) == {ObservationKind.AUCTION_OPEN, ObservationKind.AUCTION_CLOSED}
    assert kinds[ObservationKind.AUCTION_CLOSED].price == Decimal("6.50")
