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


async def test_special_editions_point_to_the_plain_emission_they_colour(session):
    from euro2core.catalog.editions import link_editions_to_base
    from euro2core.domain.models import CoinImage

    await ensure_reference_data(session)
    await ingest_ecb_entries(
        session, [ecb("Olympic Games Paris 2024", year=2024, country="FR")], fetcher=None
    )
    base = (await session.scalars(select(CoinType))).one()
    session.add(
        CoinImage(
            type_id=base.id,
            side="obverse",
            local_path="x.jpg",
            source_url="https://ecb.example/fr2024.jpg",
            author="European Central Bank",
        )
    )
    for type_id, title in (
        (419643, "2 Euros (Olympic Games, Paris; Coloured)"),
        (419699, "2 Euros (Olympic Games, Paris)"),  # plain Numista record of the same coin
    ):
        await ingest_numista_type(
            session,
            parse_type(numista(type_id, title, "Paris Olympics", year=2024, country="FR")),
            [],
            translations=[],
            fetcher=None,
        )
    await session.commit()
    await link_by_elimination(session)  # plain record merges into the ECB emission
    await session.commit()

    stats = await link_editions_to_base(session)
    await session.commit()

    assert stats == {"linked": 1, "unmatched": 0}
    edition = (await session.scalars(select(CoinType).where(CoinType.ecb_ref.is_(None)))).one()
    assert edition.numista_type_id == 419643
    assert edition.base_type_id == base.id
    # idempotent
    assert await link_editions_to_base(session) == {"linked": 0, "unmatched": 0}


async def test_edition_without_a_plausible_base_stays_unlinked(session):
    from euro2core.catalog.editions import link_editions_to_base

    await ensure_reference_data(session)
    await ingest_ecb_entries(
        session, [ecb("Treaty of Rome", year=2015, country="FR")], fetcher=None
    )
    await ingest_numista_type(
        session,
        parse_type(
            numista(
                78890,
                "2 Euros (30 Years of European Union Flag; Coloured)",
                None,
                year=2015,
                country="FR",
            )
        ),
        [],
        translations=[],
        fetcher=None,
    )
    await session.commit()
    assert await link_editions_to_base(session) == {"linked": 0, "unmatched": 1}


async def test_merge_survives_a_numista_issue_that_equals_the_ecb_placeholder(session):
    from datetime import UTC, datetime
    from decimal import Decimal

    from euro2core.catalog.seed import get_source
    from euro2core.domain.enums import Grade, ObservationKind
    from euro2core.domain.models import MarketObservation

    await ensure_reference_data(session)
    await ingest_ecb_entries(
        session, [ecb("Ten years of the euro", year=2012, country="FR")], fetcher=None
    )
    placeholder = (await session.scalars(select(CoinIssue))).one()
    ebay = await get_source(session, "ebay")
    session.add(
        MarketObservation(
            issue_id=placeholder.id,
            source_id=ebay.id,
            marketplace="EBAY_FR",
            observation_kind=ObservationKind.SOLD,
            price=Decimal("3"),
            grade=Grade.UNC,
            listing_id="x1",
            listing_url="https://ebay.fr/itm/x1",
            title_raw="2 euro France 2012",
            match_confidence=0.9,
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    # Numista knows one loose circulation issue without mint mark: the same key as the placeholder
    await ingest_numista_type(
        session,
        parse_type(
            numista(
                30000,
                "2 Euros (Decade of Common Currency)",
                None,
                year=2012,
                country="FR",
            )
        ),
        [parse_issue({"id": 777, "year": 2012, "mintage": 10_000_000})],
        translations=[],
        fetcher=None,
    )
    await session.commit()

    stats = await link_by_elimination(session)
    await session.commit()

    assert stats["merged"] == 1
    issue = (await session.scalars(select(CoinIssue))).one()
    assert issue.numista_issue_id == 777
    obs = (await session.scalars(select(MarketObservation))).one()
    assert obs.issue_id == issue.id  # the observation followed the coin


async def test_second_numista_listing_of_a_linked_emission_points_to_it(session):
    from euro2core.catalog.editions import link_editions_to_base

    await ensure_reference_data(session)
    await ingest_ecb_entries(
        session,
        [ecb("French Presidency of the Council of the European Union", year=2008, country="FR")],
        fetcher=None,
    )
    for type_id in (183033, 3561):  # Numista lists the emission twice (different mints)
        await ingest_numista_type(
            session,
            parse_type(
                numista(
                    type_id,
                    "2 Euros (French Presidency of the European Union)",
                    None,
                    year=2008,
                    country="FR",
                )
            ),
            [],
            translations=[],
            fetcher=None,
        )
    await session.commit()
    ecb_type = (await session.scalars(select(CoinType).where(CoinType.ecb_ref.is_not(None)))).one()
    assert ecb_type.numista_type_id is not None  # the fuzzy link took the first listing
    leftover = (await session.scalars(select(CoinType).where(CoinType.ecb_ref.is_(None)))).one()

    assert await link_editions_to_base(session) == {"linked": 1, "unmatched": 0}
    assert leftover.base_type_id == ecb_type.id
