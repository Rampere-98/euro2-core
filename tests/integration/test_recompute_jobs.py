from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from euro2core.catalog.seed import ensure_reference_data, get_source
from euro2core.domain.enums import CoinKind, Finish, Grade, ObservationKind, SyncStatus
from euro2core.domain.models import (
    CoinIssue,
    CoinType,
    DomainEvent,
    MarketObservation,
    PriceEstimate,
    RarityScore,
)
from euro2core.scheduler.jobs import run_recompute_prices, run_recompute_rarity

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


async def _seed(session) -> dict[str, CoinIssue]:
    await ensure_reference_data(session)
    ebay = await get_source(session, "ebay")
    ct = CoinType(kind=CoinKind.COMMEMORATIVE, country_code="DE", year=2006)
    vat = CoinType(kind=CoinKind.COMMEMORATIVE, country_code="VA", year=2006)
    session.add_all([ct, vat])
    await session.flush()
    common = CoinIssue(
        type_id=ct.id, year=2006, mint_mark="A", finish=Finish.CIRCULATION, mintage=6_000_000
    )
    rare = CoinIssue(type_id=vat.id, year=2006, mint_mark="R", finish=Finish.BU, mintage=100_000)
    unknown = CoinIssue(type_id=ct.id, year=2006, mint_mark="D", finish=Finish.PROOF)  # no mintage
    session.add_all([common, rare, unknown])
    await session.flush()

    def obs(issue, price, kind, days_ago, i):
        return MarketObservation(
            issue_id=issue.id,
            source_id=ebay.id,
            marketplace="EBAY_DE",
            observation_kind=kind,
            price=Decimal(str(price)),
            grade=Grade.BU if issue is rare else Grade.UNC,
            listing_id=f"{issue.mint_mark}-{kind.value}-{i}",
            listing_url="https://ebay.de/x",
            title_raw="x",
            match_confidence=0.95,
            observed_at=NOW - timedelta(days=days_ago),
        )

    for i, p in enumerate((3, 3.2, 3.5, 4, 3.8)):
        session.add(obs(common, p, ObservationKind.SOLD, 5 + i, i))
    for i, p in enumerate((150, 160, 170, 180, 900)):  # 900 is an outlier
        session.add(obs(rare, p, ObservationKind.AUCTION_CLOSED, 10 + i, i))
    for i in range(3):
        session.add(obs(rare, 200, ObservationKind.ASKING, 1, i))
    for i in range(40):
        session.add(obs(common, 5, ObservationKind.ASKING, 1, i))
    await session.commit()
    return {"common": common, "rare": rare, "unknown": unknown}


async def test_recompute_prices_writes_estimates_and_flags_outliers(engine, session):
    issues = await _seed(session)

    run = await run_recompute_prices(engine)

    assert run.status == SyncStatus.SUCCEEDED
    assert run.stats["issues_estimated"] == 2
    async with async_sessionmaker(engine)() as s:
        rare = (
            await s.scalars(
                select(PriceEstimate).where(
                    PriceEstimate.issue_id == issues["rare"].id, PriceEstimate.region == "global"
                )
            )
        ).one()
        assert rare.grade == Grade.BU
        assert rare.basis == "sold"
        assert rare.n_obs == 4
        assert rare.median == Decimal("165.00")
        outliers = (
            await s.scalars(
                select(MarketObservation).where(
                    MarketObservation.issue_id == issues["rare"].id, MarketObservation.is_outlier
                )
            )
        ).all()
        assert [float(o.price) for o in outliers] == [900.0]
        regional = (
            await s.scalars(
                select(PriceEstimate).where(
                    PriceEstimate.issue_id == issues["rare"].id, PriceEstimate.region == "EBAY_DE"
                )
            )
        ).one()
        assert regional.median == Decimal("165.00")


async def test_recompute_prices_is_idempotent_and_emits_spike_events(engine, session):
    issues = await _seed(session)
    await run_recompute_prices(engine)
    async with async_sessionmaker(engine)() as s:
        first = (await s.scalars(select(PriceEstimate))).all()
        ebay = await get_source(s, "ebay")
        for i in range(5):
            s.add(
                MarketObservation(
                    issue_id=issues["common"].id,
                    source_id=ebay.id,
                    marketplace="EBAY_ES",
                    observation_kind=ObservationKind.SOLD,
                    price=Decimal("9.00"),
                    grade=Grade.UNC,
                    listing_id=f"spike-{i}",
                    listing_url="https://ebay.es/x",
                    title_raw="x",
                    match_confidence=0.95,
                    observed_at=NOW - timedelta(days=1),
                )
            )
        await s.commit()
    await run_recompute_prices(engine)
    async with async_sessionmaker(engine)() as s:
        second = (await s.scalars(select(PriceEstimate))).all()
        assert len(second) >= len(first)  # rows updated in place, plus the new EBAY_ES region
        spikes = (
            await s.scalars(select(DomainEvent).where(DomainEvent.kind == "price_spike"))
        ).all()
        assert len(spikes) == 1
        assert spikes[0].entity_id == issues["common"].id


async def test_recompute_rarity_scores_issues_with_mintage(engine, session):
    issues = await _seed(session)
    await run_recompute_prices(engine)

    run = await run_recompute_rarity(engine)

    assert run.status == SyncStatus.SUCCEEDED
    assert run.stats["issues_scored"] == 2
    assert run.stats["issues_without_mintage"] == 1
    async with async_sessionmaker(engine)() as s:
        scores = {r.issue_id: r for r in (await s.scalars(select(RarityScore))).all()}
        assert issues["unknown"].id not in scores
        assert scores[issues["rare"].id].score > scores[issues["common"].id].score
        assert scores[issues["rare"].id].components["inputs"]["median_sale_price"] == 165.0
        assert scores[issues["common"].id].components["availability"] is not None

    again = await run_recompute_rarity(engine)
    assert again.status == SyncStatus.SUCCEEDED
    async with async_sessionmaker(engine)() as s:
        assert len((await s.scalars(select(RarityScore))).all()) == 2


async def test_rarity_is_relative_to_the_finish_class(engine, session):
    await ensure_reference_data(session)
    ct = CoinType(kind=CoinKind.COMMEMORATIVE, country_code="DE", year=2006)
    session.add(ct)
    await session.flush()
    # ten proofs between 5k and 50k, one circulation strike of 6M
    proofs = [
        CoinIssue(type_id=ct.id, year=2006, mint_mark=f"P{i}", finish=Finish.PROOF, mintage=m)
        for i, m in enumerate(range(5_000, 55_000, 5_000))
    ]
    circ = CoinIssue(
        type_id=ct.id, year=2006, mint_mark="A", finish=Finish.CIRCULATION, mintage=6_000_000
    )
    session.add_all([*proofs, circ])
    await session.commit()

    await run_recompute_rarity(engine)

    async with async_sessionmaker(engine)() as s:
        scores = {r.issue_id: r for r in (await s.scalars(select(RarityScore))).all()}
    proof_scores = sorted(scores[p.id].score for p in proofs)
    assert proof_scores[0] < 25 and proof_scores[-1] > 75  # spread across the range, not all 100
    assert (
        scores[circ.id].components["mintage_bounds"]
        != scores[proofs[0].id].components["mintage_bounds"]
    )


async def test_estimates_disappear_when_their_observations_age_out(engine, session):
    from sqlalchemy import update

    issues = await _seed(session)
    await run_recompute_prices(engine)
    async with async_sessionmaker(engine)() as s:
        assert len((await s.scalars(select(PriceEstimate))).all()) > 0
        await s.execute(update(MarketObservation).values(observed_at=NOW - timedelta(days=400)))
        await s.commit()

    await run_recompute_prices(engine)

    async with async_sessionmaker(engine)() as s:
        assert (await s.scalars(select(PriceEstimate))).all() == []
        assert issues["rare"].id is not None


async def test_availability_is_unknown_where_the_market_was_never_searched(engine, session):
    issues = await _seed(session)
    never_searched_type = CoinType(kind=CoinKind.COMMEMORATIVE, country_code="VA", year=2007)
    session.add(never_searched_type)
    await session.flush()
    never_searched = CoinIssue(
        type_id=never_searched_type.id, year=2007, mint_mark="R", finish=Finish.BU, mintage=85_000
    )
    session.add(never_searched)
    await session.commit()

    await run_recompute_rarity(engine)

    async with async_sessionmaker(engine)() as s:
        scores = {r.issue_id: r for r in (await s.scalars(select(RarityScore))).all()}
    assert scores[issues["common"].id].components["availability"] is not None
    # zero listings for a coin nobody looked for is missing data, not scarcity
    assert scores[never_searched.id].components["availability"] is None
