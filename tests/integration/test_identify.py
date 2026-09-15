import io
import uuid
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from euro2core.catalog.ingest_ecb import ingest_ecb_entries
from euro2core.catalog.seed import ensure_reference_data
from euro2core.domain.enums import ImageSide
from euro2core.domain.models import CoinImage, CoinType, Identification
from euro2core.sources.ecb.parser import EcbEntry
from euro2core.vision.embedder import ClipEmbedder
from euro2core.vision.identify import confirm, identify
from euro2core.vision.index import embed_missing_images

pytestmark = [pytest.mark.integration, pytest.mark.model]

FIX = Path(__file__).parent.parent / "fixtures" / "images"
COINS = {
    "de_2006_schleswig_holstein.jpg": ("DE", 2006, "Schleswig-Holstein"),
    "va_2004_founding.jpg": ("VA", 2004, "75th anniversary of the Vatican City State"),
    "lt_2024_straw_gardens.jpg": ("LT", 2024, "Lithuanian tradition of straw gardens"),
}


@pytest.fixture(scope="module")
def embedder():
    return ClipEmbedder()


@pytest.fixture
async def indexed(session, embedder):
    await ensure_reference_data(session)
    for name, (cc, year, feature) in COINS.items():
        await ingest_ecb_entries(
            session,
            [EcbEntry(year, cc, cc, feature, "", None, "", "", [f"https://x/{name}"])],
            fetcher=None,
        )
        ct = (
            await session.scalars(
                select(CoinType).where(CoinType.country_code == cc, CoinType.year == year)
            )
        ).one()
        session.add(
            CoinImage(
                type_id=ct.id,
                side=ImageSide.OBVERSE,
                local_path=str(FIX / name),
                source_url=f"https://x/{name}",
                sha256="0" * 64,
            )
        )
    await session.commit()
    stats = await embed_missing_images(session, embedder)
    await session.commit()
    assert stats == {"embedded": 3, "unreadable": 0}
    return session


async def test_a_phone_style_photo_identifies_the_right_coin(indexed, embedder, tmp_path):
    original = Image.open(FIX / "va_2004_founding.jpg")
    shot = original.rotate(-9, expand=False).resize((190, 190))
    buf = io.BytesIO()
    shot.save(buf, format="JPEG", quality=70)

    result = await identify(indexed, buf.getvalue(), embedder, uploads_dir=tmp_path)

    assert result.candidates, "no candidate returned"
    top = result.candidates[0]
    top_type = await indexed.get(CoinType, top.type_id)
    assert top_type.country_code == "VA"
    assert top.confidence in ("high", "medium")
    record = await indexed.get(Identification, result.identification_id)
    assert record.top_type_id == top.type_id
    assert Path(record.image_path).is_file()
    assert len(record.embedding) == 512


async def test_identify_does_not_embed_the_same_image_twice(indexed, embedder):
    stats = await embed_missing_images(indexed, embedder)
    assert stats["embedded"] == 0


async def test_user_confirmation_is_stored_for_future_training(indexed, embedder):
    data = (FIX / "de_2006_schleswig_holstein.jpg").read_bytes()
    result = await identify(indexed, data, embedder)
    other = (await indexed.scalars(select(CoinType).where(CoinType.country_code == "LT"))).one()
    assert await confirm(indexed, result.identification_id, other.id) is True
    await indexed.commit()
    record = await indexed.get(Identification, result.identification_id)
    assert record.confirmed_type_id == other.id


async def test_identify_endpoint_returns_localized_candidates_and_accepts_confirmation(
    indexed, embedder, tmp_path, monkeypatch
):
    from httpx import ASGITransport, AsyncClient

    from euro2core.api.app import create_app

    monkeypatch.setattr("euro2core.api.routers.identify.get_embedder", lambda: embedder)
    app = create_app(engine=indexed.bind)
    data = (FIX / "lt_2024_straw_gardens.jpg").read_bytes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/identify", files={"file": ("coin.jpg", data, "image/jpeg")})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["candidates"][0]["type"]["country_code"] == "LT"
        assert body["candidates"][0]["confidence"] == "high"
        chosen = body["candidates"][0]["type"]["id"]
        r2 = await client.post(
            f"/identify/{body['identification_id']}/confirm", json={"type_id": chosen}
        )
        assert r2.status_code == 204
        bad = await client.post("/identify", files={"file": ("x.txt", b"nope", "text/plain")})
        assert bad.status_code == 422


async def test_off_centre_photo_without_a_detectable_rim_is_found_by_multi_crop(
    indexed, embedder, tmp_path, monkeypatch
):
    # the coin sits in a busy frame and the rim detector gives up: the identifier must try
    # tighter centre crops instead of matching the whole frame
    monkeypatch.setattr("euro2core.vision.identify.find_coin", lambda *a, **k: None)
    coin = Image.open(FIX / "lt_2024_straw_gardens.jpg").resize((300, 300))
    frame = Image.new("RGB", (900, 600), (70, 60, 50))
    frame.paste(coin, (300, 150))  # centred, but only half the short side
    buf = io.BytesIO()
    frame.save(buf, format="JPEG", quality=85)

    result = await identify(indexed, buf.getvalue(), embedder, uploads_dir=tmp_path)

    assert result.found_circle is False
    top = result.candidates[0]
    assert (await indexed.get(CoinType, top.type_id)).country_code == "LT"
    assert top.confidence in ("high", "medium")
    record = await indexed.get(Identification, result.identification_id)
    assert Path(record.image_path).is_file()
    # the stored crop is the one that matched, i.e. the tight one around the coin
    assert Image.open(record.image_path).size == (224, 224)


async def test_identify_endpoint_serves_the_crop_it_used(indexed, embedder, tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from euro2core.api.app import create_app

    monkeypatch.setattr("euro2core.api.routers.identify.get_embedder", lambda: embedder)
    monkeypatch.setattr(
        "euro2core.api.routers.identify.get_settings",
        lambda: type("S", (), {"data_dir": tmp_path})(),
    )
    app = create_app(engine=indexed.bind)
    data = (FIX / "va_2004_founding.jpg").read_bytes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/identify", params={"guided": "true"}, files={"file": ("coin.jpg", data, "image/jpeg")}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["found_circle"] is True
        assert body["crop_url"] == f"/identify/{body['identification_id']}/crop"
        crop = await client.get(body["crop_url"])
        assert crop.status_code == 200
        assert crop.headers["content-type"] == "image/jpeg"
        assert Image.open(io.BytesIO(crop.content)).size == (224, 224)
        missing = await client.get(f"/identify/{uuid.uuid4()}/crop")
        assert missing.status_code == 404
