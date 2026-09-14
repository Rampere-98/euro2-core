import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from euro2core.catalog.ingest_ecb import ingest_ecb_entries
from euro2core.catalog.ingest_numista import ingest_numista_type
from euro2core.catalog.seed import ensure_reference_data
from euro2core.domain.enums import CoinKind, Finish, Packaging
from euro2core.domain.models import CoinImage, CoinIssue, CoinType, FactClaim, TextTranslation
from euro2core.sources.ecb.parser import parse_commemorative_page
from euro2core.sources.numista.parser import parse_issue, parse_type

pytestmark = pytest.mark.integration

FIX = Path(__file__).parent.parent / "fixtures"


def load(name: str):
    return json.loads((FIX / "numista" / name).read_text("utf-8"))


def ecb_entries(year: int):
    return parse_commemorative_page((FIX / "ecb" / f"comm_{year}.en.html").read_text("utf-8"), year)


class NoImages:
    async def fetch(self, url, folder):
        raise RuntimeError("images disabled in this test")


@pytest.fixture
async def seeded(session):
    await ensure_reference_data(session)
    await session.commit()
    return session


async def _count(session, model, *where) -> int:
    return (
        await session.execute(select(func.count()).select_from(model).where(*where))
    ).scalar_one()


async def test_commemorative_links_to_existing_ecb_type_and_creates_variants(seeded, tmp_path):
    session = seeded
    # ECB entry for Germany 2006 Schleswig-Holstein, crafted from the real 2006 feature text
    from euro2core.sources.ecb.parser import EcbEntry

    ecb = EcbEntry(
        year=2006,
        country_code="DE",
        country_name="Germany",
        feature="Schleswig-Holstein",
        description="The Holstentor",
        mintage=30_000_000,
        mintage_raw="30 million coins",
        issue_date_raw="February 2006",
    )
    await ingest_ecb_entries(session, [ecb], fetcher=None)
    await session.commit()

    numista_type = parse_type(load("type_2169.json"))
    numista_type_es = parse_type(load("type_2169_es.json"))
    issues = [parse_issue(i) for i in load("type_2169_issues.json")]
    result = await ingest_numista_type(
        session, numista_type, issues, translations=[numista_type_es], fetcher=None
    )
    await session.commit()

    assert result.linked_to_ecb is True
    assert await _count(session, CoinType) == 1
    coin_type = (await session.scalars(select(CoinType))).one()
    assert coin_type.numista_type_id == 2169
    assert coin_type.mintage_total == 30_000_000  # ECB (rank 100) still wins

    variants = (
        await session.scalars(select(CoinIssue).where(CoinIssue.type_id == coin_type.id))
    ).all()
    assert len(variants) == 15
    a_circ = next(v for v in variants if v.mint_mark == "A" and v.finish == Finish.CIRCULATION)
    assert a_circ.mintage == 6_000_000
    assert a_circ.packaging == Packaging.LOOSE
    assert a_circ.numista_issue_id == 9758

    # Numista's summed circulation mintage is recorded as a competing, losing claim
    mintage_claims = (
        await session.scalars(
            select(FactClaim).where(
                FactClaim.entity_id == coin_type.id, FactClaim.field == "mintage_total"
            )
        )
    ).all()
    assert {c.value for c in mintage_claims} == {30_000_000, 30_110_000}
    assert [c.value for c in mintage_claims if c.is_winner] == [30_000_000]

    es = (
        await session.scalars(
            select(TextTranslation).where(
                TextTranslation.entity_id == coin_type.id, TextTranslation.lang == "es"
            )
        )
    ).all()
    assert {t.field for t in es} >= {"description"}


async def test_circulation_type_without_ecb_entry_is_created_from_numista(seeded):
    session = seeded
    circulation = parse_type(
        {
            **load("type_2169.json"),
            "id": 6323,
            "title": "2 Euros (2nd map)",
            "object_type": {"id": 1, "name": "Standard circulation coins"},
            "min_year": 2008,
            "max_year": 2026,
            "series": None,
            "commemorated_topic": None,
        }
    )
    issues = [parse_issue(i) for i in load("type_6323_issues.json")]
    result = await ingest_numista_type(session, circulation, issues, translations=[], fetcher=None)
    await session.commit()

    assert result.linked_to_ecb is False
    coin_type = (await session.scalars(select(CoinType))).one()
    assert coin_type.kind == CoinKind.CIRCULATION
    assert coin_type.numista_type_id == 6323
    assert coin_type.year == 2008
    assert await _count(session, CoinIssue) == len(issues)


async def test_documented_error_becomes_error_type_pointing_at_its_base(seeded):
    session = seeded
    base = parse_type(load("type_2169.json"))
    await ingest_numista_type(session, base, [], translations=[], fetcher=None)
    mule = parse_type(
        {
            **load("type_327881.json"),
            "issuer": {"code": "allemagne", "name": "Germany"},
            "min_year": 2006,
            "max_year": 2006,
            "series": "German states",
            "commemorated_topic": "State of Schleswig-Holstein",
        }
    )
    result = await ingest_numista_type(session, mule, [], translations=[], fetcher=None)
    await session.commit()

    error_type = (
        await session.scalars(select(CoinType).where(CoinType.kind == CoinKind.ERROR))
    ).one()
    base_type = (
        await session.scalars(select(CoinType).where(CoinType.numista_type_id == 2169))
    ).one()
    assert error_type.base_type_id == base_type.id
    assert result.base_type_id == base_type.id


async def test_implausible_issue_year_falls_back_to_type_year_or_is_skipped(seeded):
    session = seeded
    t = parse_type(load("type_2169.json"))  # single-year type (2006)
    bad = parse_issue(
        {"id": 999001, "year": 0, "gregorian_year": 0, "mint_letter": "INCM", "mintage": 21000}
    )
    result = await ingest_numista_type(session, t, [bad], translations=[], fetcher=None)
    await session.commit()
    assert result.issues_created == 1
    issue = (
        await session.scalars(select(CoinIssue).where(CoinIssue.numista_issue_id == 999001))
    ).one()
    assert issue.year == 2006

    multi_year = parse_type(
        {**load("type_2169.json"), "id": 777, "min_year": 2008, "max_year": 2026}
    )
    bad2 = parse_issue({"id": 999002, "year": 0, "mint_letter": "A"})
    result = await ingest_numista_type(session, multi_year, [bad2], translations=[], fetcher=None)
    await session.commit()
    assert result.issues_created == 0
    assert result.issues_skipped == 1


async def test_re_ingest_is_idempotent(seeded):
    session = seeded
    t = parse_type(load("type_2169.json"))
    issues = [parse_issue(i) for i in load("type_2169_issues.json")]
    await ingest_numista_type(session, t, issues, translations=[], fetcher=None)
    await session.commit()
    before = (await _count(session, CoinIssue), await _count(session, FactClaim))
    await ingest_numista_type(session, t, issues, translations=[], fetcher=None)
    await session.commit()
    assert (await _count(session, CoinIssue), await _count(session, FactClaim)) == before


async def test_images_are_stored_with_numista_attribution(seeded, tmp_path):
    import httpx
    import respx

    from euro2core.images.fetcher import ImageFetcher

    session = seeded
    t = parse_type(load("type_2169.json"))
    with respx.mock:
        respx.get(url__regex=r".*numista.*").mock(
            return_value=httpx.Response(
                200,
                content=b"\x89PNG\r\n\x1a\n" + b"\0" * 8,
                headers={"Content-Type": "image/jpeg"},
            )
        )
        await ingest_numista_type(
            session, t, [], translations=[], fetcher=ImageFetcher(tmp_path, "t")
        )
    await session.commit()
    images = (await session.scalars(select(CoinImage))).all()
    assert {i.side.value for i in images} == {"obverse", "reverse"}
    assert all(i.author == "brismike" and i.license == "CC BY-NC" for i in images)
