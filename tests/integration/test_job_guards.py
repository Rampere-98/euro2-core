import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from euro2core.domain.enums import SyncStatus
from euro2core.domain.models import CoinType, SyncRun
from euro2core.scheduler.jobs import (
    JobAlreadyRunning,
    run_ebay_market,
    run_ecb_discover,
    run_numista_catalog,
)
from euro2core.sources.ebay.client import BROWSE_BASE, TOKEN_URL
from euro2core.sources.numista.client import NUMISTA_API_BASE

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ecb"
ECB = "https://www.ecb.europa.eu/euro/coins/comm/html/"


@respx.mock
async def test_same_job_twice_at_once_serialises_and_never_duplicates(engine, tmp_path):
    respx.get(f"{ECB}comm_2004.en.html").mock(
        return_value=httpx.Response(200, text=(FIXTURES / "comm_2004.en.html").read_text("utf-8"))
    )
    respx.get(url__regex=r".*\.jpg$").mock(return_value=httpx.Response(503))
    respx.get(url__regex=r".*/coins/html/[a-z]{2}\.en\.html$").mock(
        return_value=httpx.Response(404)
    )

    a, b = await asyncio.gather(
        run_ecb_discover(engine, data_dir=tmp_path, years=[2004], user_agent="t"),
        run_ecb_discover(engine, data_dir=tmp_path, years=[2004], user_agent="t"),
    )

    assert {a.status, b.status} == {SyncStatus.SUCCEEDED}
    assert a.stats["types_created"] + b.stats["types_created"] == 6
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(CoinType))).scalar_one() == 6


@respx.mock
async def test_orphaned_running_run_is_closed_and_its_cursor_resumed(engine, tmp_path):
    async with async_sessionmaker(engine)() as s:
        s.add(
            SyncRun(
                job="numista_catalog",
                status=SyncStatus.RUNNING,
                cursor={"issuers_done": ["germany"]},
                started_at=datetime.now(UTC) - timedelta(hours=3),
            )
        )
        await s.commit()
    respx.get(f"{NUMISTA_API_BASE}/types").mock(
        return_value=httpx.Response(200, json={"count": 0, "types": []})
    )

    run = await run_numista_catalog(
        engine, data_dir=tmp_path, api_key="k", user_agent="t", issuers=["germany", "spain"]
    )

    assert run.status == SyncStatus.SUCCEEDED
    assert run.stats["issuers_skipped"] == ["germany"]
    async with async_sessionmaker(engine)() as s:
        orphan = (
            await s.scalars(
                select(SyncRun).where(SyncRun.id != run.id, SyncRun.job == "numista_catalog")
            )
        ).one()
        assert orphan.status == SyncStatus.FAILED
        assert orphan.finished_at is not None


@respx.mock
async def test_cursor_is_checkpointed_while_the_job_runs(engine, tmp_path):
    seen: list[dict | None] = []

    async def search(request):
        async with async_sessionmaker(engine)() as s:
            running = (
                await s.scalars(select(SyncRun).where(SyncRun.status == SyncStatus.RUNNING))
            ).first()
            seen.append(dict(running.cursor) if running and running.cursor else None)
        return httpx.Response(200, json={"count": 0, "types": []})

    respx.get(f"{NUMISTA_API_BASE}/types").mock(side_effect=search)
    await run_numista_catalog(
        engine, data_dir=tmp_path, api_key="k", user_agent="t", issuers=["germany", "spain"]
    )
    # when the second issuer is searched, the first is already persisted in the running row
    assert seen[1] == {"issuers_done": ["germany"]}


@respx.mock
async def test_ebay_budget_counts_calls_already_spent_today(engine, tmp_path):
    async with async_sessionmaker(engine)() as s:
        s.add(
            SyncRun(
                job="ebay_market",
                status=SyncStatus.FAILED,
                stats={"queries": 4},
                finished_at=datetime.now(UTC) - timedelta(minutes=10),
            )
        )
        await s.commit()
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
    )
    respx.get(f"{BROWSE_BASE}/item_summary/search").mock(
        return_value=httpx.Response(200, json={"total": 0, "itemSummaries": []})
    )
    async with async_sessionmaker(engine)() as s:
        from euro2core.catalog.seed import ensure_reference_data
        from euro2core.domain.enums import CoinKind, Finish
        from euro2core.domain.models import CoinIssue

        await ensure_reference_data(s)
        for year in (2004, 2005, 2006):
            ct = CoinType(kind=CoinKind.COMMEMORATIVE, country_code="DE", year=year)
            s.add(ct)
            await s.flush()
            s.add(CoinIssue(type_id=ct.id, year=year, mint_mark="A", finish=Finish.CIRCULATION))
        await s.commit()

    run = await run_ebay_market(
        engine,
        client_id="a",
        client_secret="b",
        user_agent="t",
        marketplaces=["EBAY_DE"],
        daily_budget=5,
    )

    assert run.status == SyncStatus.FAILED
    assert "budget" in run.error
    assert run.stats["queries"] == 1  # 4 spent earlier today + 1 now = 5 = budget


def test_job_already_running_is_an_explicit_error_type():
    assert issubclass(JobAlreadyRunning, RuntimeError)
