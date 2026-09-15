import json
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
from euro2core.sources.ecb.parser import EcbEntry, parse_commemorative_page

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
async def test_an_image_the_ecb_reuses_for_two_coins_is_attached_to_both(
    session, entries_2004, fetcher
):
    respx.get(url__regex=r".*\.jpg$").mock(
        return_value=httpx.Response(200, content=PNG, headers={"Content-Type": "image/jpeg"})
    )
    shared = "https://www.ecb.europa.eu/euro/coins/comm/html/comm_2004/shared.jpg"
    first, second = entries_2004[0], entries_2004[1]
    entries = [replace(first, image_urls=[shared]), replace(second, image_urls=[shared])]
    await ensure_reference_data(session)
    await ingest_ecb_entries(session, entries, fetcher)
    await session.commit()
    rows = (await session.scalars(select(CoinImage).where(CoinImage.source_url == shared))).all()
    assert len(rows) == 2
    assert len({r.type_id for r in rows}) == 2
    assert all(r.local_path for r in rows)


@respx.mock
async def test_image_download_failure_does_not_abort_the_ingest(session, entries_2004, fetcher):
    respx.get(url__regex=r".*\.jpg$").mock(return_value=httpx.Response(503))
    await ensure_reference_data(session)
    stats = await ingest_ecb_entries(session, entries_2004, fetcher)
    await session.commit()
    assert stats.types_created == 6
    assert stats.images_failed == 6
    assert await _count(session, CoinImage) == 0


async def test_ecb_only_types_get_a_placeholder_issue_that_numista_replaces(session, entries_2004):
    from euro2core.catalog.ingest_numista import ingest_numista_type
    from euro2core.domain.models import CoinIssue
    from euro2core.sources.numista.parser import parse_issue, parse_type

    await ensure_reference_data(session)
    await ingest_ecb_entries(session, entries_2004, fetcher=None)
    await session.commit()
    issues = (await session.scalars(select(CoinIssue))).all()
    assert len(issues) == 6  # one loose circulation issue per emission, so prices can attach
    assert all(i.mint_mark == "" and i.numista_issue_id is None for i in issues)

    # Numista knows the Vatican 2004 coin as a single Rome-mint issue: the placeholder is reused
    vatican = next(
        t for t in (await session.scalars(select(CoinType))).all() if t.country_code == "VA"
    )
    numista_type = parse_type(
        {
            **json.loads((FIXTURES.parent / "numista" / "type_5082.json").read_text("utf-8")),
            "id": 5080,
            "title": "2 Euros - John Paul II (State anniversary)",
            "min_year": 2004,
            "max_year": 2004,
            "commemorated_topic": "75th anniversary of the Vatican City State",
        }
    )
    await ingest_numista_type(
        session,
        numista_type,
        [parse_issue({"id": 26000, "year": 2004, "mint_letter": "R", "mintage": 85_000})],
        translations=[],
        fetcher=None,
    )
    await session.commit()
    vatican_issues = (
        await session.scalars(select(CoinIssue).where(CoinIssue.type_id == vatican.id))
    ).all()
    assert [(i.mint_mark, i.numista_issue_id, i.mintage) for i in vatican_issues] == [
        ("R", 26000, 85_000)
    ]


async def test_german_emissions_get_their_five_mints_from_the_ecb_total_alone(session):
    from euro2core.catalog.issues import GERMAN_MINTS
    from euro2core.domain.models import CoinIssue

    await ensure_reference_data(session)
    entry = EcbEntry(
        year=2026,
        country_code="DE",
        country_name="Germany",
        feature="Thuringia",
        description="Wartburg castle.",
        mintage=30_000_000,
        mintage_raw="30 million coins",
        issue_date_raw="January 2026",
    )
    await ingest_ecb_entries(session, [entry], fetcher=None)
    await session.commit()
    coin_type = (await session.scalars(select(CoinType).where(CoinType.country_code == "DE"))).one()
    issues = (
        await session.scalars(select(CoinIssue).where(CoinIssue.type_id == coin_type.id))
    ).all()
    assert sorted(i.mint_mark for i in issues) == list(GERMAN_MINTS)
    assert {i.mintage for i in issues} == {6_000_000}
