import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from euro2core.catalog.ingest_numista import ingest_numista_type
from euro2core.catalog.seed import ensure_reference_data
from euro2core.domain.enums import Grade, SyncStatus
from euro2core.domain.models import CoinIssue, PriceEstimate
from euro2core.scheduler.jobs import run_numista_prices, run_recompute_prices
from euro2core.sources.numista.client import NUMISTA_API_BASE
from euro2core.sources.numista.parser import parse_issue, parse_type
from euro2core.sources.numista.prices import parse_prices

pytestmark = pytest.mark.integration

FIX = Path(__file__).parent.parent / "fixtures" / "numista"
PRICES = {
    "currency": "EUR",
    "prices": [
        {"grade": "g", "price": 2},
        {"grade": "vf", "price": 2},
        {"grade": "xf", "price": 2.5},
        {"grade": "au", "price": 3.4},
        {"grade": "unc", "price": 4.2},
        {"grade": "bu", "price": 9},
        {"grade": "pf", "price": 30},
    ],
}


def test_numista_grades_map_to_catalog_grades():
    mapped = parse_prices(PRICES)
    assert mapped == {
        Grade.CIRCULATED: Decimal("2.50"),
        Grade.UNC: Decimal("4.20"),
        Grade.BU: Decimal("9.00"),
        Grade.PROOF: Decimal("30.00"),
    }
    assert parse_prices({"currency": "USD", "prices": [{"grade": "unc", "price": 5}]}) == {}


@pytest.fixture
async def numista_catalog(session):
    await ensure_reference_data(session)
    await ingest_numista_type(
        session,
        parse_type(json.loads((FIX / "type_2169.json").read_text("utf-8"))),
        [parse_issue(i) for i in json.loads((FIX / "type_2169_issues.json").read_text("utf-8"))],
        translations=[],
        fetcher=None,
    )
    await session.commit()


@respx.mock
async def test_catalog_prices_become_labelled_estimates_and_survive_recompute(
    engine, numista_catalog, tmp_path
):
    respx.get(url__regex=rf"{NUMISTA_API_BASE}/types/2169/issues/\d+/prices").mock(
        return_value=httpx.Response(200, json=PRICES)
    )
    run = await run_numista_prices(
        engine, data_dir=tmp_path, api_key="k", user_agent="t", max_calls=100
    )
    assert run.status == SyncStatus.SUCCEEDED, run.error
    assert run.stats["issues_priced"] == 15
    async with async_sessionmaker(engine)() as s:
        rows = (await s.scalars(select(PriceEstimate))).all()
        assert len(rows) == 15 * 4
        assert {r.basis for r in rows} == {"catalog"}
        assert all(r.region == "global" and r.confidence == "catalog" for r in rows)
    # a prices recompute (no market observations here) must leave catalog values alone
    await run_recompute_prices(engine)
    async with async_sessionmaker(engine)() as s:
        assert len((await s.scalars(select(PriceEstimate))).all()) == 60

    again = await run_numista_prices(
        engine, data_dir=tmp_path, api_key="k", user_agent="t", max_calls=100
    )
    assert again.stats["issues_priced"] == 0  # fresh enough, not re-fetched


@respx.mock
async def test_call_budget_stops_the_run_with_a_cursor(engine, numista_catalog, tmp_path):
    respx.get(url__regex=rf"{NUMISTA_API_BASE}/types/2169/issues/\d+/prices").mock(
        return_value=httpx.Response(200, json=PRICES)
    )
    run = await run_numista_prices(
        engine, data_dir=tmp_path, api_key="k", user_agent="t", max_calls=4
    )
    assert run.status == SyncStatus.SUCCEEDED
    assert run.stats["issues_priced"] == 4 and run.stats["budget_exhausted"] is True
    async with async_sessionmaker(engine)() as s:
        priced = await s.scalar(select(CoinIssue.id).limit(1))
        assert priced is not None
