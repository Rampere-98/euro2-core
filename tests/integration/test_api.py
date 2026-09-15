import io
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


async def _admin(client) -> dict:
    """The first account registered on a server is its administrator."""
    r = await client.post(
        "/auth/register",
        json={"email": "owner@example.org", "password": "secret-pass-1", "display_name": "Owner"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["user"]["role"] == "admin"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_trigger_sync_job_is_admin_only(client, catalog, monkeypatch):
    calls = []

    async def fake_job(engine, **kwargs):
        calls.append(kwargs)
        return SyncRun(job="ecb_discover", status="succeeded", stats={})

    monkeypatch.setattr("euro2core.api.routers.sync.JOBS", {"ecb_discover": fake_job})
    assert (await client.post("/sync/ecb_discover")).status_code == 401
    admin = await _admin(client)
    second = await client.post(
        "/auth/register",
        json={"email": "u2@example.org", "password": "secret-pass-1", "display_name": "U"},
    )
    user = {"Authorization": f"Bearer {second.json()['access_token']}"}
    assert second.json()["user"]["role"] == "user"
    assert (await client.post("/sync/ecb_discover", headers=user)).status_code == 403
    r = await client.post("/sync/ecb_discover", headers=admin)
    assert r.status_code == 202
    assert r.json()["job"] == "ecb_discover"
    assert (await client.post("/sync/nope", headers=admin)).status_code == 404


async def test_trigger_sync_is_refused_while_the_job_runs(client, catalog, monkeypatch):
    monkeypatch.setattr("euro2core.api.routers.sync.is_running", lambda job: True)
    admin = await _admin(client)
    assert (await client.post("/sync/ecb_discover", headers=admin)).status_code == 409


async def test_image_endpoint_handles_reference_only_and_escaped_paths(client, catalog, session):
    from euro2core.domain.enums import ImageSide
    from euro2core.domain.models import CoinImage

    reference_only = CoinImage(
        type_id=catalog["type_id"],
        side=ImageSide.REVERSE,
        source_url="https://en.numista.com/x.jpg",
        local_path=None,
    )
    outside = CoinImage(
        type_id=catalog["type_id"],
        side=ImageSide.EDGE,
        source_url="https://example.org/y.jpg",
        local_path=str(Path(__file__).resolve()),  # a real file, but not under data/images
        sha256="0" * 64,
    )
    session.add_all([reference_only, outside])
    await session.commit()
    assert (await client.get(f"/images/{reference_only.id}")).status_code == 404
    assert (await client.get(f"/images/{outside.id}")).status_code == 404
    detail = (await client.get(f"/types/{catalog['type_id']}")).json()
    urls = {i["side"]: i["url"] for i in detail["images"]}
    assert urls["reverse"] is None


async def test_has_conflict_ignores_formatting_differences(client, catalog, session):
    from euro2core.catalog.claims import record_claim
    from euro2core.catalog.seed import get_source

    numista = await get_source(session, "numista")
    # same figure as the ECB winner, written with thousands separators: not a conflict
    await record_claim(
        session,
        entity="coin_type",
        entity_id=catalog["type_id"],
        field="issue_date_raw",
        value="February 2006",
        source=numista,
    )
    await session.commit()
    facts = (await client.get(f"/types/{catalog['type_id']}")).json()["facts"]
    assert facts["issue_date_raw"]["has_conflict"] is False
    assert facts["mintage_total"]["has_conflict"] is True  # 30,000,000 vs 30,110,000 still is


async def test_search_treats_sql_wildcards_literally(client, catalog):
    assert (await client.get("/search", params={"q": "%_%"})).json()["total"] == 0
    assert (await client.get("/search", params={"q": "schleswig"})).json()["total"] == 1


async def test_special_edition_without_photo_shows_its_base_design_labelled(
    client, catalog, session
):
    from euro2core.domain.enums import CoinKind, ImageSide, VerificationStatus
    from euro2core.domain.models import CoinImage, CoinType

    session.add(
        CoinImage(
            type_id=catalog["type_id"],
            side=ImageSide.OBVERSE,
            source_url="https://ecb.example/de2006.jpg",
            local_path="de2006.jpg",
            sha256="1" * 64,
            author="European Central Bank",
        )
    )
    edition = CoinType(
        kind=CoinKind.COMMEMORATIVE,
        country_code="DE",
        year=2006,
        numista_type_id=999001,
        base_type_id=catalog["type_id"],
        verification_status=VerificationStatus.DOCUMENTED,
    )
    session.add(edition)
    await session.commit()

    detail = (await client.get(f"/types/{edition.id}")).json()
    assert len(detail["images"]) == 1
    assert detail["images"][0]["source_url"] == "https://ecb.example/de2006.jpg"
    assert detail["images"][0]["borrowed"] is True
    assert detail["base_type_id"] == str(catalog["type_id"])
    listed = (await client.get("/types", params={"country": "DE", "year": 2006})).json()
    by_id = {t["id"]: t for t in listed["items"]}
    assert by_id[str(edition.id)]["image"]["borrowed"] is True
    assert by_id[str(catalog["type_id"])]["image"]["borrowed"] is False


async def test_list_shows_a_value_hint_and_filters_and_sorts_by_price(client, catalog, session):
    from euro2core.pricing.recompute import recompute_model_estimates

    await recompute_model_estimates(session)  # every variant without sales gets a model band
    await session.commit()
    listed = (await client.get("/types", params={"country": "DE", "year": 2006})).json()
    de = next(t for t in listed["items"] if t["id"] == str(catalog["type_id"]))
    assert de["value"]["basis"] == "sold"  # the fixture has three real sales on mint A
    assert de["value"]["median"] == "3.50"
    cheap = (await client.get("/types", params={"max_value": "1"})).json()
    assert cheap["total"] == 0
    pricey = (await client.get("/types", params={"min_value": "3", "sort": "value_desc"})).json()
    assert pricey["total"] >= 1 and pricey["items"][0]["value"] is not None


async def test_image_endpoint_serves_cached_webp_thumbnails(
    client, catalog, session, tmp_path, monkeypatch
):
    from PIL import Image

    from euro2core.config import get_settings
    from euro2core.domain.enums import ImageSide
    from euro2core.domain.models import CoinImage

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    original = images_dir / "coin.jpg"
    Image.new("RGB", (900, 900), (200, 170, 60)).save(original, format="JPEG")
    photo = CoinImage(
        type_id=catalog["type_id"],
        side=ImageSide.OBVERSE,
        source_url="https://example.org/coin.jpg",
        local_path=str(original),
        sha256="1" * 64,
    )
    session.add(photo)
    await session.commit()

    full = await client.get(f"/images/{photo.id}")
    assert full.status_code == 200
    assert Image.open(io.BytesIO(full.content)).size == (900, 900)

    # sizes snap to a few buckets so the cache stays small; the file is reused next time
    small = await client.get(f"/images/{photo.id}", params={"w": 70})
    assert small.status_code == 200
    assert small.headers["content-type"] == "image/webp"
    assert "immutable" in small.headers["cache-control"]
    assert Image.open(io.BytesIO(small.content)).size == (128, 128)
    assert (images_dir / "coin_w128.webp").is_file()
    again = await client.get(f"/images/{photo.id}", params={"w": 128})
    assert again.content == small.content
    # never upscale beyond the largest bucket
    big = await client.get(f"/images/{photo.id}", params={"w": 4000})
    assert Image.open(io.BytesIO(big.content)).size == (512, 512)


async def test_type_issues_come_with_estimates_and_rarity_in_one_call(client, catalog):
    # the coin page needs every variant's prices and rarity: one request, not one per variant
    r = await client.get(f"/types/{catalog['type_id']}/issues")
    assert r.status_code == 200
    issues = r.json()
    assert len(issues) == (await client.get(f"/types/{catalog['type_id']}")).json()["issue_count"]
    a = next(i for i in issues if i["mint_mark"] == "A" and i["mintage"] == 6_000_000)
    assert a["estimates"] and a["rarity"] is not None
    assert {i["id"] for i in issues} == {
        (await client.get(f"/issues/{i['id']}")).json()["id"] for i in issues
    }
    assert (await client.get(f"/types/{uuid.uuid4()}/issues")).status_code == 404
