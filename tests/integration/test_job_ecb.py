from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select

from euro2core.domain.enums import SyncStatus
from euro2core.domain.models import CoinType, SyncRun
from euro2core.scheduler.jobs import run_ecb_discover

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ecb"
ECB = "https://www.ecb.europa.eu/euro/coins/comm/html/"


def _page(year: int) -> str:
    return (FIXTURES / f"comm_{year}.en.html").read_text("utf-8")


@respx.mock
async def test_job_ingests_every_year_and_records_a_successful_run(engine, tmp_path):
    respx.get(f"{ECB}comm_2004.en.html").mock(return_value=httpx.Response(200, text=_page(2004)))
    respx.get(f"{ECB}comm_2007.en.html").mock(return_value=httpx.Response(200, text=_page(2007)))
    respx.get(url__regex=r".*\.jpg$").mock(return_value=httpx.Response(503))

    run = await run_ecb_discover(engine, data_dir=tmp_path, years=[2004, 2007], user_agent="t")

    assert run.status == SyncStatus.SUCCEEDED
    assert run.stats["types_created"] == 6 + 20
    assert run.stats["years"] == [2004, 2007]
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(CoinType))).scalar_one() == 26
        stored = (await conn.execute(select(SyncRun))).one()
        assert stored.job == "ecb_discover"
        assert stored.finished_at is not None


@respx.mock
async def test_missing_future_year_page_is_skipped_not_fatal(engine, tmp_path):
    respx.get(f"{ECB}comm_2004.en.html").mock(return_value=httpx.Response(200, text=_page(2004)))
    respx.get(f"{ECB}comm_2027.en.html").mock(return_value=httpx.Response(404))
    respx.get(url__regex=r".*\.jpg$").mock(return_value=httpx.Response(503))

    run = await run_ecb_discover(engine, data_dir=tmp_path, years=[2004, 2027], user_agent="t")

    assert run.status == SyncStatus.SUCCEEDED
    assert run.stats["years_missing"] == [2027]
    assert run.stats["types_created"] == 6


@respx.mock
async def test_restructured_page_is_flagged_instead_of_silently_emptying_the_year(engine, tmp_path):
    respx.get(f"{ECB}comm_2004.en.html").mock(
        side_effect=[
            httpx.Response(200, text=_page(2004)),
            httpx.Response(200, text="<html><body><h1>New layout</h1></body></html>"),
        ]
    )
    respx.get(url__regex=r".*\.jpg$").mock(return_value=httpx.Response(503))
    first = await run_ecb_discover(engine, data_dir=tmp_path, years=[2004], user_agent="t")
    assert first.stats["types_created"] == 6

    # the cache must not mask the change: a fresh body is fetched because the ETag differs
    second = await run_ecb_discover(engine, data_dir=tmp_path, years=[2004], user_agent="t")

    assert second.status == SyncStatus.SUCCEEDED
    assert second.stats["years_empty"] == [2004]
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(CoinType))).scalar_one() == 6


@respx.mock
async def test_unexpected_failure_marks_the_run_failed_and_keeps_earlier_years(engine, tmp_path):
    respx.get(f"{ECB}comm_2004.en.html").mock(return_value=httpx.Response(200, text=_page(2004)))
    respx.get(f"{ECB}comm_2007.en.html").mock(side_effect=httpx.ConnectError("boom"))
    respx.get(url__regex=r".*\.jpg$").mock(return_value=httpx.Response(503))

    run = await run_ecb_discover(engine, data_dir=tmp_path, years=[2004, 2007], user_agent="t")

    assert run.status == SyncStatus.FAILED
    assert "boom" in run.error
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(CoinType))).scalar_one() == 6
