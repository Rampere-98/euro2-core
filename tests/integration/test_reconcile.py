import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from euro2core.catalog.ingest_ecb import ingest_ecb_entries
from euro2core.catalog.ingest_numista import ingest_numista_type
from euro2core.catalog.reconcile import link_by_elimination
from euro2core.catalog.seed import ensure_reference_data
from euro2core.domain.enums import CoinKind
from euro2core.domain.models import CoinIssue, CoinType, FactClaim, TextTranslation
from euro2core.sources.ecb.parser import EcbEntry
from euro2core.sources.numista.parser import classify_kind, parse_issue, parse_type

pytestmark = pytest.mark.integration

FIX = Path(__file__).parent.parent / "fixtures" / "numista"


def load(name: str):
    return json.loads((FIX / name).read_text("utf-8"))


def ecb(feature: str, year=2011, country="DE", mintage=30_000_000) -> EcbEntry:
    return EcbEntry(
        year=year,
        country_code=country,
        country_name=country,
        feature=feature,
        description="",
        mintage=mintage,
        mintage_raw=str(mintage),
        issue_date_raw="",
    )


ISSUERS = {"DE": "allemagne", "BE": "belgique", "FR": "france"}


def numista(type_id: int, title: str, topic: str | None, year=2011, country="DE") -> dict:
    return {
        **load("type_2169.json"),
        "id": type_id,
        "title": title,
        "commemorated_topic": topic,
        "min_year": year,
        "max_year": year,
        "issuer": {"code": ISSUERS[country], "name": country},
        "url": f"https://en.numista.com/{type_id}",
    }


async def _count(session, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_single_leftovers_per_country_year_are_merged(session):
    await ensure_reference_data(session)
    await ingest_ecb_entries(session, [ecb("North Rhine-Westphalia")], fetcher=None)
    issues = [
        parse_issue({**i, "id": i["id"] + 900000, "year": 2011, "gregorian_year": 2011})
        for i in load("type_2169_issues.json")
    ]
    await ingest_numista_type(
        session,
        parse_type(
            numista(18666, '2 Euros (Bundesländer - "Nordrhein-Westfalen")', "State of NRW")
        ),
        issues,
        translations=[],
        fetcher=None,
    )
    await session.commit()
    assert await _count(session, CoinType) == 2  # fuzzy link failed: two types for one coin

    stats = await link_by_elimination(session)
    await session.commit()

    assert stats["merged"] == 1
    assert await _count(session, CoinType) == 1
    coin_type = (await session.scalars(select(CoinType))).one()
    assert coin_type.ecb_ref is not None and coin_type.numista_type_id == 18666
    assert coin_type.mintage_total == 30_000_000  # ECB claim still wins after the merge
    issue_types = set((await session.scalars(select(CoinIssue.type_id))).all())
    assert issue_types == {coin_type.id}
    assert await _count(session, CoinIssue) == 15
    claim_targets = set(
        (
            await session.scalars(
                select(FactClaim.entity_id).where(FactClaim.entity == "coin_type")
            )
        ).all()
    )
    assert claim_targets == {coin_type.id}
    titles = (
        await session.scalars(
            select(TextTranslation.text).where(
                TextTranslation.entity_id == coin_type.id, TextTranslation.field == "title"
            )
        )
    ).all()
    assert titles == ["North Rhine-Westphalia"]  # ECB title kept, Numista's not duplicated


async def test_ambiguous_leftovers_are_left_alone(session):
    await ensure_reference_data(session)
    await ingest_ecb_entries(session, [ecb("Coin A"), ecb("Coin B")], fetcher=None)
    await ingest_numista_type(
        session,
        parse_type(numista(1, "2 Euros (Something X)", None)),
        [],
        translations=[],
        fetcher=None,
    )
    await session.commit()
    stats = await link_by_elimination(session)
    assert stats["merged"] == 0
    assert stats["ambiguous"] == 1
    assert await _count(session, CoinType) == 3


async def test_equal_sized_groups_are_paired_by_similarity(session):
    await ensure_reference_data(session)
    await ingest_ecb_entries(
        session,
        [
            ecb("Olympic Games", year=2016, country="BE"),
            ecb("International Missing Children's Day", year=2016, country="BE"),
        ],
        fetcher=None,
    )
    for type_id, title in (
        (10, "2 Euros - Philippe (Summer Olympics 2016 in Rio de Janeiro)"),
        (11, "2 Euros - Philippe (Child Focus)"),
    ):
        await ingest_numista_type(
            session,
            parse_type(numista(type_id, title, None, year=2016, country="BE")),
            [],
            translations=[],
            fetcher=None,
        )
    await session.commit()

    stats = await link_by_elimination(session)
    await session.commit()

    assert stats["merged"] == 2
    types = (await session.scalars(select(CoinType))).all()
    assert len(types) == 2
    by_numista = {t.numista_type_id: t for t in types}
    titles = {
        t.numista_type_id: (
            await session.scalars(
                select(TextTranslation.text).where(
                    TextTranslation.entity_id == t.id, TextTranslation.field == "title"
                )
            )
        ).one()
        for t in types
    }
    assert titles[10] == "Olympic Games"
    assert titles[11] == "International Missing Children's Day"
    assert all(t.ecb_ref for t in by_numista.values())


async def test_coloured_and_hologram_editions_stay_standalone(session):
    await ensure_reference_data(session)
    await ingest_ecb_entries(
        session, [ecb("World AIDS Day", year=2014, country="FR")], fetcher=None
    )
    for type_id, title in (
        (20, "2 Euros (World AIDS Day; Coloured)"),
        (21, "2 Euros (Journée mondiale du SIDA)"),
    ):
        await ingest_numista_type(
            session,
            parse_type(numista(type_id, title, None, year=2014, country="FR")),
            [],
            translations=[],
            fetcher=None,
        )
    await session.commit()

    stats = await link_by_elimination(session)
    await session.commit()

    assert stats["merged"] == 1
    types = {t.numista_type_id: t for t in (await session.scalars(select(CoinType))).all()}
    assert types[21].ecb_ref is not None  # the plain edition is the ECB emission
    assert types[20].ecb_ref is None  # the coloured edition remains its own type


async def test_leftover_numista_type_without_ecb_counterpart_is_kept(session):
    await ensure_reference_data(session)
    await ingest_numista_type(
        session,
        parse_type(numista(2, "2 Euros (Only on Numista)", None)),
        [],
        translations=[],
        fetcher=None,
    )
    await session.commit()
    stats = await link_by_elimination(session)
    assert stats["merged"] == 0
    assert await _count(session, CoinType) == 1


@pytest.mark.parametrize(
    ("title", "object_type", "kind"),
    [
        ("2 Euros - Albert II (1st map)", "Non-circulating coins", CoinKind.CIRCULATION),
        ("2 Euros - Henri I (2nd map)", "Standard circulation coins", CoinKind.CIRCULATION),
        ("2 Euros - Albert II (Swiss Guard)", "Non-circulating coins", CoinKind.COMMEMORATIVE),
    ],
)
def test_map_variants_are_circulation_designs(title, object_type, kind):
    assert classify_kind(title, object_type) == kind
