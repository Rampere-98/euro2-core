from dataclasses import replace
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select

from euro2core.catalog.ingest_ecb import ingest_ecb_entries
from euro2core.catalog.seed import ensure_reference_data
from euro2core.domain.enums import CoinKind
from euro2core.domain.models import (
    CoinImage,
    CoinType,
    DomainEvent,
    FactClaim,
    Source,
    TextTranslation,
)
from euro2core.images.fetcher import ImageFetcher
from euro2core.sources.ecb.parser import parse_commemorative_page

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ecb"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def entries_2004():
    return parse_commemorative_page((FIXTURES / "comm_2004.en.html").read_text("utf-8"), 2004)


@pytest.fixture
def entries_2007():
    return parse_commemorative_page((FIXTURES / "comm_2007.en.html").read_text("utf-8"), 2007)


@pytest.fixture
def fetcher(tmp_path):
    return ImageFetcher(root=tmp_path / "img", user_agent="test")


async def _count(session, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_seeds_countries_and_ranked_sources(session):
    await ensure_reference_data(session)
    await session.commit()
    ecb = (await session.scalars(select(Source).where(Source.code == "ecb"))).one()
    assert ecb.authority_rank == 100
    codes = set((await session.scalars(select(Source.code))).all())
    assert codes >= {"ecb", "numista", "ebay"}


@respx.mock
async def test_first_ingest_creates_types_claims_translations_and_events(
    session, entries_2004, fetcher
):
    respx.get(url__regex=r".*\.jpg$").mock(
        return_value=httpx.Response(200, content=PNG, headers={"Content-Type": "image/jpeg"})
    )
    await ensure_reference_data(session)
    stats = await ingest_ecb_entries(session, entries_2004, fetcher)
    await session.commit()

    assert stats.types_created == 6
    assert await _count(session, CoinType) == 6
    vatican = (await session.scalars(select(CoinType).where(CoinType.country_code == "VA"))).one()
    assert vatican.kind == CoinKind.COMMEMORATIVE
    assert vatican.year == 2004
    assert vatican.mintage_total == 100_000
    assert vatican.ecb_ref.startswith("2004/VA/")

    title = (
        await session.scalars(
            select(TextTranslation).where(
                TextTranslation.entity_id == vatican.id,
                TextTranslation.field == "title",
                TextTranslation.lang == "en",
            )
        )
    ).one()
    assert "75th anniversary" in title.text

    winners = (
        await session.scalars(
            select(FactClaim).where(FactClaim.entity_id == vatican.id, FactClaim.is_winner)
        )
    ).all()
    assert {c.field for c in winners} >= {"kind", "mintage_total", "title", "issue_date_raw"}

    events = (await session.scalars(select(DomainEvent))).all()
    assert sum(e.kind == "new_type_discovered" for e in events) == 6

    images = (await session.scalars(select(CoinImage))).all()
    assert len(images) == 6
    assert all(img.author == "European Central Bank" for img in images)
    assert all(Path(img.local_path).exists() for img in images)


@respx.mock
async def test_second_identical_ingest_is_a_no_op(session, entries_2004, fetcher):
    respx.get(url__regex=r".*\.jpg$").mock(
        return_value=httpx.Response(200, content=PNG, headers={"Content-Type": "image/jpeg"})
    )
    await ensure_reference_data(session)
    await ingest_ecb_entries(session, entries_2004, fetcher)
    await session.commit()
    claims_before = await _count(session, FactClaim)
    events_before = await _count(session, DomainEvent)

    stats = await ingest_ecb_entries(session, entries_2004, fetcher)
    await session.commit()

    assert stats.types_created == 0
    assert await _count(session, CoinType) == 6
    assert await _count(session, FactClaim) == claims_before
    assert await _count(session, DomainEvent) == events_before


@respx.mock
async def test_revised_mintage_from_the_same_source_wins_and_emits_an_event(
    session, entries_2004, fetcher
):
    respx.get(url__regex=r".*\.jpg$").mock(
        return_value=httpx.Response(200, content=PNG, headers={"Content-Type": "image/jpeg"})
    )
    await ensure_reference_data(session)
    await ingest_ecb_entries(session, entries_2004, fetcher)
    await session.commit()

    revised = [replace(e, mintage=120_000) if e.country_code == "VA" else e for e in entries_2004]
    await ingest_ecb_entries(session, revised, fetcher)
    await session.commit()

    vatican = (await session.scalars(select(CoinType).where(CoinType.country_code == "VA"))).one()
    assert vatican.mintage_total == 120_000
    claims = (
        await session.scalars(
            select(FactClaim).where(
                FactClaim.entity_id == vatican.id, FactClaim.field == "mintage_total"
            )
        )
    ).all()
    assert len(claims) == 2
    assert [c.value for c in claims if c.is_winner] == [120_000]
    revisions = (
        await session.scalars(select(DomainEvent).where(DomainEvent.kind == "fact_revised"))
    ).all()
    assert len(revisions) == 1
    assert revisions[0].payload["field"] == "mintage_total"
    assert revisions[0].payload["previous"] == 100_000


@respx.mock
async def test_joint_issue_creates_one_type_per_country_sharing_the_group(
    session, entries_2007, fetcher
):
    respx.get(url__regex=r".*\.jpg$").mock(
        return_value=httpx.Response(200, content=PNG, headers={"Content-Type": "image/jpeg"})
    )
    await ensure_reference_data(session)
    await ingest_ecb_entries(session, entries_2007, fetcher)
    await session.commit()

    joint = (
        await session.scalars(
            select(CoinType).where(CoinType.joint_issue_group == "2007-treaty-of-rome")
        )
    ).all()
    assert len(joint) == 13
    assert all(t.mintage_total is None for t in joint)


@respx.mock
async def test_image_download_failure_does_not_abort_the_ingest(session, entries_2004, fetcher):
    respx.get(url__regex=r".*\.jpg$").mock(return_value=httpx.Response(503))
    await ensure_reference_data(session)
    stats = await ingest_ecb_entries(session, entries_2004, fetcher)
    await session.commit()
    assert stats.types_created == 6
    assert stats.images_failed == 6
    assert await _count(session, CoinImage) == 0
