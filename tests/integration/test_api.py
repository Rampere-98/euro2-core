import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from euro2core.api.app import create_app
from euro2core.catalog.ingest_ecb import ingest_ecb_entries
from euro2core.catalog.ingest_numista import ingest_numista_type
from euro2core.catalog.seed import ensure_reference_data, get_source
from euro2core.domain.enums import Grade, ObservationKind
from euro2core.domain.models import (
    CoinIssue,
    MarketObservation,
    PriceEstimate,
    RarityScore,
    SyncRun,
)
from euro2core.sources.ecb.parser import EcbEntry
from euro2core.sources.numista.parser import parse_issue, parse_type

pytestmark = pytest.mark.integration

FIX = Path(__file__).parent.parent / "fixtures" / "numista"


def load(name: str):
    return json.loads((FIX / name).read_text("utf-8"))


@pytest.fixture
async def catalog(session, engine):
    """Germany 2006 Schleswig-Holstein from ECB + Numista, one estimate, one rarity score."""
    await ensure_reference_data(session)
    ecb = EcbEntry(
        year=2006,
        country_code="DE",
        country_name="Germany",
        feature="Schleswig-Holstein",
        description="The Holstentor, the gate symbolising the town of Lübeck.",
        mintage=30_000_000,
        mintage_raw="30 million coins",
        issue_date_raw="February 2006",
    )
    await ingest_ecb_entries(session, [ecb], fetcher=None)
    await ingest_numista_type(
        session,
        parse_type(load("type_2169.json")),
        [parse_issue(i) for i in load("type_2169_issues.json")],
        translations=[parse_type(load("type_2169_es.json"))],
        fetcher=None,
    )
    await session.flush()
    issue = (
        await session.scalars(
            select(CoinIssue).where(CoinIssue.mint_mark == "A", CoinIssue.mintage == 6_000_000)
        )
    ).one()
    ebay = await get_source(session, "ebay")
    for i, price in enumerate((3.0, 3.5, 4.0)):
        session.add(
            MarketObservation(
                issue_id=issue.id,
                source_id=ebay.id,
                marketplace="EBAY_DE",
                observation_kind=ObservationKind.SOLD,
                price=Decimal(str(price)),
                grade=Grade.UNC,
                listing_id=f"l{i}",
                listing_url=f"https://ebay.de/itm/{i}",
                title_raw="2 Euro Deutschland 2006 A Schleswig-Holstein",
                match_confidence=0.95,
                observed_at=datetime(2026, 6, 1, tzinfo=UTC),
            )
        )
    session.add(
        PriceEstimate(
            issue_id=issue.id,
            grade=Grade.UNC,
            region="global",
            window_days=90,
            median=Decimal("3.50"),
            p25=Decimal("3.00"),
            p75=Decimal("4.00"),
            n_obs=3,
            confidence="low",
            basis="sold",
            method_version="price-v1",
        )
    )
    session.add(
        RarityScore(
            issue_id=issue.id,
            score=12.5,
            tier="common",
            components={"mintage": 12.5},
            method_version="rarity-v1",
        )
    )
    session.add(SyncRun(job="ecb_discover", status="succeeded", stats={"types_created": 1}))
    await session.commit()
    return {"issue_id": issue.id, "type_id": issue.type_id}


@pytest.fixture
async def client(engine):
    app = create_app(engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["database"] == "ok"


async def test_list_types_filters_and_localizes(client, catalog):
    r = await client.get("/types", params={"country": "DE", "year": 2006})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == str(catalog["type_id"])
    assert item["kind"] == "commemorative"
    assert item["title"] == "Schleswig-Holstein"
    assert item["mintage_total"] == 30_000_000
    assert item["issue_count"] == 15

    assert (await client.get("/types", params={"country": "FR"})).json()["total"] == 0


async def test_type_detail_exposes_facts_with_provenance_and_conflicts(client, catalog):
    r = await client.get(f"/types/{catalog['type_id']}", headers={"Accept-Language": "es"})
    assert r.status_code == 200
    body = r.json()
    assert "níquel" in body["composition"] or "Holstentor" in body["description"]
    mintage = body["facts"]["mintage_total"]
    assert mintage["value"] == 30_000_000
    assert mintage["source"] == "ecb"
    assert mintage["has_conflict"] is True
    assert [a["value"] for a in mintage["alternatives"]] == [30_110_000]
    assert len(body["issues"]) == 15
    assert {i["mint_mark"] for i in body["issues"]} == set("ADFGJ")


async def test_type_detail_404_for_unknown_id(client, catalog):
    assert (await client.get(f"/types/{uuid.uuid4()}")).status_code == 404


async def test_issue_detail_has_estimates_rarity_and_observations(client, catalog):
    r = await client.get(f"/issues/{catalog['issue_id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["mint_mark"] == "A"
    assert body["finish"] == "circulation"
    assert body["mintage"] == 6_000_000
    assert body["type"]["title"] == "Schleswig-Holstein"
    est = body["estimates"][0]
    assert est == {
        "grade": "unc",
        "region": "global",
        "window_days": 90,
        "median": "3.50",
        "p25": "3.00",
        "p75": "4.00",
        "n_obs": 3,
        "confidence": "low",
        "basis": "sold",
        "method_version": "price-v1",
    }
    assert body["rarity"]["tier"] == "common"

    obs = (await client.get(f"/issues/{catalog['issue_id']}/observations")).json()
    assert obs["total"] == 3
    assert obs["items"][0]["marketplace"] == "EBAY_DE"


async def test_search_is_accent_insensitive(client, catalog):
    r = await client.get("/search", params={"q": "lubeck"})
    assert r.status_code == 200
    assert [t["title"] for t in r.json()["items"]] == ["Schleswig-Holstein"]


async def test_events_sources_and_sync_runs(client, catalog):
    events = (await client.get("/events")).json()
    assert any(e["kind"] == "new_type_discovered" for e in events["items"])

    sources = (await client.get("/sources")).json()
    ranks = {s["code"]: s["authority_rank"] for s in sources}
    assert ranks["ecb"] == 100 and ranks["numista"] == 50 and ranks["ebay"] == 10

    runs = (await client.get("/sync/runs")).json()
    assert runs["items"][0]["job"] == "ecb_discover"


async def test_trigger_sync_job_is_recorded(client, catalog, monkeypatch):
    calls = []

    async def fake_job(engine, **kwargs):
        calls.append(kwargs)
        return SyncRun(job="ecb_discover", status="succeeded", stats={})

    monkeypatch.setattr("euro2core.api.routers.sync.JOBS", {"ecb_discover": fake_job})
    r = await client.post("/sync/ecb_discover")
    assert r.status_code == 202
    assert r.json()["job"] == "ecb_discover"
    assert (await client.post("/sync/nope")).status_code == 404
