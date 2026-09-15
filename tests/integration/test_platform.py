import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from euro2core.api.app import create_app
from euro2core.catalog.ingest_ecb import ingest_ecb_entries
from euro2core.catalog.ingest_numista import ingest_numista_type
from euro2core.catalog.seed import ensure_reference_data
from euro2core.domain.enums import CoinKind, Grade, Role
from euro2core.domain.models import (
    CoinIssue,
    CoinType,
    CollectionItem,
    DomainEvent,
    PriceEstimate,
    RarityScore,
    User,
)
from euro2core.platform.news import publish_pending
from euro2core.sources.ecb.parser import EcbEntry
from euro2core.sources.numista.parser import parse_issue, parse_type

pytestmark = pytest.mark.integration

FIX = Path(__file__).parent.parent / "fixtures" / "numista"


def load(name: str):
    return json.loads((FIX / name).read_text("utf-8"))


@pytest.fixture
async def catalog(session):
    """Germany 2006 (15 Numista variants, ECB winner) + Vatican 2004 (ECB placeholder issue)."""
    await ensure_reference_data(session)
    await ingest_ecb_entries(
        session,
        [
            EcbEntry(
                2006,
                "DE",
                "Germany",
                "Schleswig-Holstein",
                "Holstentor",
                30_000_000,
                "",
                "Feb 2006",
            ),
            EcbEntry(
                2004,
                "VA",
                "Vatican",
                "75th anniversary of the Vatican City State",
                "",
                100_000,
                "",
                "",
            ),
        ],
        fetcher=None,
    )
    await ingest_numista_type(
        session,
        parse_type(load("type_2169.json")),
        [parse_issue(i) for i in load("type_2169_issues.json")],
        translations=[parse_type(load("type_2169_es.json"))],
        fetcher=None,
    )
    await session.flush()
    de_a = (
        await session.scalars(
            select(CoinIssue).where(CoinIssue.mint_mark == "A", CoinIssue.mintage == 6_000_000)
        )
    ).one()
    va = (
        await session.scalars(
            select(CoinIssue)
            .join(CoinType, CoinType.id == CoinIssue.type_id)
            .where(CoinType.country_code == "VA")
        )
    ).one()
    session.add(
        PriceEstimate(
            issue_id=va.id,
            grade=Grade.UNC,
            region="global",
            window_days=90,
            median=Decimal("45.00"),
            p25=Decimal("40.00"),
            p75=Decimal("50.00"),
            n_obs=6,
            confidence="medium",
            basis="sold",
            method_version="price-v1",
        )
    )
    session.add(
        RarityScore(
            issue_id=va.id,
            score=90.0,
            tier="exceptional",
            components={},
            method_version="rarity-v1",
        )
    )
    await session.commit()
    return {"de_a": de_a.id, "va": va.id, "de_type": de_a.type_id, "va_type": va.type_id}


@pytest.fixture
async def client(engine):
    app = create_app(engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _signup(client, email, name="Ana", country="ES") -> dict:
    r = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "secret-pass-1",
            "display_name": name,
            "country_code": country,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return {"Authorization": f"Bearer {body['access_token']}", "_id": body["user"]["id"]}


# ---------------------------------------------------------------- account


async def test_register_login_and_profile(client, catalog):
    auth = await _signup(client, "ana@example.org")
    me = await client.get("/me", headers=auth)
    assert me.status_code == 200 and me.json()["plan"] == "free"
    dup = await client.post(
        "/auth/register",
        json={"email": "ANA@example.org", "password": "secret-pass-1", "display_name": "x"},
    )
    assert dup.status_code == 409
    bad = await client.post(
        "/auth/login", json={"email": "ana@example.org", "password": "nope-nope"}
    )
    assert bad.status_code == 401
    ok = await client.post(
        "/auth/login", json={"email": "ana@example.org", "password": "secret-pass-1"}
    )
    assert ok.status_code == 200
    assert (await client.get("/me")).status_code == 401
    assert (await client.get("/me", headers={"Authorization": "Bearer garbage"})).status_code == 401
    renamed = await client.patch("/me", json={"display_name": "Ana R."}, headers=auth)
    assert renamed.json()["display_name"] == "Ana R."


# ---------------------------------------------------------------- portfolio


async def test_collection_valuation_is_honest_about_its_basis(client, catalog):
    auth = await _signup(client, "col@example.org")
    r1 = await client.post(
        "/me/collection",
        json={"issue_id": str(catalog["de_a"]), "grade": "unc", "acquired_price": "2.00"},
        headers=auth,
    )
    assert r1.status_code == 201, r1.text
    assert r1.json()["valuation"] == {
        "value": "2.00",
        "basis": "face_value",
        "grade": None,
        "n_obs": 0,
        "confidence": "none",
    }
    r2 = await client.post(
        "/me/collection", json={"issue_id": str(catalog["va"]), "grade": "unc"}, headers=auth
    )
    assert r2.json()["valuation"]["basis"] == "sold"
    assert r2.json()["valuation"]["value"] == "45.00"

    col = (await client.get("/me/collection", headers=auth)).json()
    assert col["net_worth"]["pieces"] == 2
    assert col["net_worth"]["value"] == "47.00"
    assert col["net_worth"]["cost"] == "2.00"
    assert col["net_worth"]["gain"] == "45.00"
    assert col["net_worth"]["value_by_basis"] == {"face_value": "2.00", "sold": "45.00"}

    item_id = r2.json()["id"]
    hist = (await client.get(f"/me/collection/{item_id}/history", headers=auth)).json()
    assert [e["kind"] for e in hist] == ["registered"]
    cert = (await client.get(f"/me/collection/{item_id}/certificate", headers=auth)).json()
    assert cert["signature"] and cert["digest"]
    check = await client.post(
        f"/certificates/{item_id}/verify",
        json={"digest": cert["digest"], "signature": cert["signature"]},
    )
    assert check.json() == {
        "signature_valid": True,
        "chain_unchanged": True,
        "current_digest": cert["digest"],
        "events": 1,
    }
    forged = await client.post(
        f"/certificates/{item_id}/verify", json={"digest": cert["digest"], "signature": "0" * 64}
    )
    assert forged.json()["signature_valid"] is False

    assert (await client.delete(f"/me/collection/{item_id}", headers=auth)).status_code == 204
    other = await _signup(client, "other@example.org")
    assert (
        await client.delete(f"/me/collection/{r1.json()['id']}", headers=other)
    ).status_code == 404


async def test_achievements_and_leaderboard(client, catalog):
    auth = await _signup(client, "ach@example.org", name="Luis")
    await client.post("/me/collection", json={"issue_id": str(catalog["va"])}, headers=auth)
    codes = {a["code"] for a in (await client.get("/me/achievements", headers=auth)).json()}
    assert "first_coin" in codes
    assert "rare_hunter" in codes  # the Vatican piece is exceptional
    assert "country_complete:VA" in codes  # the only Vatican emission in this catalog
    notes = (await client.get("/me/notifications", headers=auth)).json()
    assert any(n["kind"] == "achievement" for n in notes)
    assert all(n["read_at"] is None for n in notes)
    await client.post("/me/notifications/read", headers=auth)
    assert all(n["read_at"] for n in (await client.get("/me/notifications", headers=auth)).json())

    board = (await client.get("/leaderboard")).json()
    assert board[0]["display_name"] == "Luis" and board[0]["rank"] == 1
    assert board[0]["score"] > 1  # rarity bonus on top of the piece count


async def test_price_alerts_are_free_for_every_user(client, catalog):
    auth = await _signup(client, "alerts@example.org")
    body = {"issue_id": str(catalog["va"]), "direction": "above", "threshold": "40"}
    created = await client.post("/me/alerts", json=body, headers=auth)
    assert created.status_code == 201

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from euro2core.platform.alerts import check_alerts

    async with async_sessionmaker(client._transport.app.state.engine)() as s:
        stats = await check_alerts(s)
        await s.commit()
    assert stats["alerts_fired"] == 1
    notes = (await client.get("/me/notifications", headers=auth)).json()
    assert any(n["kind"] == "price_alert" and n["payload"]["basis"] == "sold" for n in notes)
    assert (await client.get("/me/alerts", headers=auth)).json()[0]["active"] is False


# ---------------------------------------------------------------- marketplace


async def _verified_item(session, user_id, issue_id) -> CollectionItem:
    item = CollectionItem(
        user_id=user_id, issue_id=issue_id, grade=Grade.UNC, verified_at=datetime.now(UTC)
    )
    session.add(item)
    await session.commit()
    return item


async def test_listing_offer_acceptance_transfers_the_piece_with_provenance(
    client, catalog, session
):
    seller = await _signup(client, "seller@example.org", name="Vendedor")
    buyer = await _signup(client, "buyer@example.org", name="Comprador")
    unverified = (
        await client.post("/me/collection", json={"issue_id": str(catalog["va"])}, headers=seller)
    ).json()
    refused = await client.post(
        "/market/listings", json={"item_id": unverified["id"], "price": "40"}, headers=seller
    )
    assert refused.status_code == 409  # must be verified with a photo first

    piece = await _verified_item(session, seller["_id"], catalog["va"])
    listed = await client.post(
        "/market/listings",
        json={"item_id": str(piece.id), "price": "42.50", "description": "BU, en cápsula"},
        headers=seller,
    )
    assert listed.status_code == 201, listed.text
    listing_id = listed.json()["id"]
    assert listed.json()["seller"]["reputation"]["completed_transactions"] == 0

    browse = (await client.get("/market/listings", params={"country": "VA"})).json()
    assert browse["total"] == 1 and browse["items"][0]["type"]["country_code"] == "VA"
    assert (await client.get("/market/listings", params={"country": "DE"})).json()["total"] == 0

    own = await client.post(
        f"/market/listings/{listing_id}/offers", json={"amount": "40"}, headers=seller
    )
    assert own.status_code == 409
    offer = await client.post(
        f"/market/listings/{listing_id}/offers",
        json={"amount": "40", "message": "¿40?"},
        headers=buyer,
    )
    assert offer.status_code == 201
    offer_id = offer.json()["id"]
    seller_notes = (await client.get("/me/notifications", headers=seller)).json()
    assert any(n["kind"] == "offer_received" for n in seller_notes)

    assert (
        await client.post(f"/market/offers/{offer_id}/accept", headers=buyer)
    ).status_code == 404
    accepted = await client.post(f"/market/offers/{offer_id}/accept", headers=seller)
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"

    buyer_col = (await client.get("/me/collection", headers=buyer)).json()
    assert [i["id"] for i in buyer_col["items"]] == [str(piece.id)]
    assert buyer_col["items"][0]["acquired_price"] == "40.00"
    hist = (await client.get(f"/me/collection/{piece.id}/history", headers=buyer)).json()
    assert [e["kind"] for e in hist] == ["sale"]
    assert hist[0]["from_user_id"] == seller["_id"] and hist[0]["to_user_id"] == buyer["_id"]
    assert (await client.get(f"/market/listings/{listing_id}")).json()["status"] == "sold"
    assert (await client.get("/me/collection", headers=seller)).json()["net_worth"]["pieces"] == 1

    rated = await client.post(f"/market/offers/{offer_id}/rate", json={"stars": 5}, headers=buyer)
    assert rated.status_code == 201
    again = await client.post(f"/market/offers/{offer_id}/rate", json={"stars": 4}, headers=buyer)
    assert again.status_code == 409
    rep = (await client.get(f"/users/{seller['_id']}/reputation")).json()
    assert rep == {"average_stars": 5.0, "ratings": 1, "completed_transactions": 1}


async def test_trade_swaps_pieces_both_ways(client, catalog, session):
    a = await _signup(client, "a@example.org")
    b = await _signup(client, "b@example.org")
    piece_a = await _verified_item(session, a["_id"], catalog["va"])
    piece_b = await _verified_item(session, b["_id"], catalog["de_a"])
    listing = (
        await client.post(
            "/market/listings", json={"item_id": str(piece_a.id), "accepts_trades": True}, headers=a
        )
    ).json()
    offer = await client.post(
        f"/market/listings/{listing['id']}/offers",
        json={"offered_item_ids": [str(piece_b.id)]},
        headers=b,
    )
    assert offer.status_code == 201, offer.text
    assert (
        await client.post(f"/market/offers/{offer.json()['id']}/accept", headers=a)
    ).status_code == 200
    a_items = {i["id"] for i in (await client.get("/me/collection", headers=a)).json()["items"]}
    b_items = {i["id"] for i in (await client.get("/me/collection", headers=b)).json()["items"]}
    assert a_items == {str(piece_b.id)} and b_items == {str(piece_a.id)}


async def test_free_plan_listing_limit(client, catalog, session):
    await _signup(client, "owner@example.org")  # the first account is the admin, exempt
    seller = await _signup(client, "limit@example.org")
    for _ in range(3):
        piece = await _verified_item(session, seller["_id"], catalog["de_a"])
        r = await client.post(
            "/market/listings", json={"item_id": str(piece.id), "price": "3"}, headers=seller
        )
        assert r.status_code == 201
    piece = await _verified_item(session, seller["_id"], catalog["de_a"])
    r = await client.post(
        "/market/listings", json={"item_id": str(piece.id), "price": "3"}, headers=seller
    )
    assert r.status_code == 402


# ---------------------------------------------------------------- community


async def test_expert_validation_creates_a_documented_error_type(client, catalog, session):
    await _signup(client, "owner@example.org")  # admin; the reporter must be a plain user
    reporter = await _signup(client, "rep@example.org")
    experts = [await _signup(client, f"exp{i}@example.org") for i in range(2)]
    for e in experts:
        user = await session.get(User, __import__("uuid").UUID(e["_id"]))
        user.role = Role.EXPERT
    await session.commit()

    report = await client.post(
        "/reports",
        data={
            "base_type_id": str(catalog["de_type"]),
            "title": "Schleswig-Holstein sin inscripción en el canto",
            "description": "Ejemplar con canto liso, sin EINIGKEIT UND RECHT UND FREIHEIT.",
        },
        headers=reporter,
    )
    assert report.status_code == 201, report.text
    report_id = report.json()["id"]
    assert (
        await client.post(f"/reports/{report_id}/vote", json={"approve": True}, headers=reporter)
    ).status_code == 403
    first = await client.post(
        f"/reports/{report_id}/vote", json={"approve": True}, headers=experts[0]
    )
    assert first.json()["status"] == "pending" and first.json()["approvals"] == 1
    second = await client.post(
        f"/reports/{report_id}/vote", json={"approve": True}, headers=experts[1]
    )
    assert second.json()["status"] == "validated"
    error_type = await session.get(
        CoinType, __import__("uuid").UUID(second.json()["created_type_id"])
    )
    assert error_type.kind == CoinKind.ERROR and error_type.base_type_id == catalog["de_type"]
    assert (await client.get("/reports", params={"status": "validated"})).json()[0][
        "id"
    ] == report_id
    notes = (await client.get("/me/notifications", headers=reporter)).json()
    assert any(n["kind"] == "report_validated" for n in notes)


async def test_news_feed_is_generated_from_events_in_both_languages(client, catalog, session):
    stats = await publish_pending(session)
    await session.commit()
    assert stats["published"] >= 2  # the two ECB discoveries at least
    es = (await client.get("/news", headers={"Accept-Language": "es"})).json()
    en = (await client.get("/news", headers={"Accept-Language": "en"})).json()
    assert any(n["title"].startswith("Nueva emisión: Alemania 2006") for n in es["items"])
    assert any(n["title"].startswith("New emission: Germany 2006") for n in en["items"])
    again = await publish_pending(session)
    assert again["published"] == 0
    events = (await session.scalars(select(DomainEvent))).all()
    assert len(events) >= stats["published"]


@pytest.mark.model
async def test_semantic_search_finds_by_meaning_in_spanish(client, catalog, session):
    from euro2core.platform.semantic import embed_types, get_text_embedder

    stats = await embed_types(session, get_text_embedder())
    await session.commit()
    assert stats["embedded"] == 2
    hits = (
        await client.get("/search/semantic", params={"q": "puerta medieval de una ciudad alemana"})
    ).json()
    assert hits[0]["type"]["country_code"] == "DE"
    hits = (
        await client.get("/search/semantic", params={"q": "aniversario del estado vaticano"})
    ).json()
    assert hits[0]["type"]["country_code"] == "VA"
