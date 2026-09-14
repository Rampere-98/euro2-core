import json
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select

from euro2core.domain.enums import SyncStatus
from euro2core.domain.models import CoinIssue, CoinType, SyncRun
from euro2core.scheduler.jobs import run_numista_catalog
from euro2core.sources.numista.client import NUMISTA_API_BASE

pytestmark = pytest.mark.integration

FIX = Path(__file__).parent.parent / "fixtures" / "numista"


def load(name: str):
    return json.loads((FIX / name).read_text("utf-8"))


def _mock_numista(types_by_issuer: dict[str, list[int]]):
    def search(request):
        issuer = request.url.params["issuer"]
        hits = [
            t
            for t in load("search_germany_2euro.json")["types"]
            if t["id"] in types_by_issuer.get(issuer, [])
        ]
        return httpx.Response(200, json={"count": len(hits), "types": hits})

    respx.get(f"{NUMISTA_API_BASE}/types").mock(side_effect=search)
    respx.get(f"{NUMISTA_API_BASE}/types/2169").mock(
        side_effect=lambda r: httpx.Response(
            200,
            json=load("type_2169_es.json" if r.url.params["lang"] == "es" else "type_2169.json"),
        )
    )
    respx.get(f"{NUMISTA_API_BASE}/types/2169/issues").mock(
        return_value=httpx.Response(200, json=load("type_2169_issues.json"))
    )
    respx.get(url__regex=r".*numista\.com/catalogue/photos/.*").mock(
        return_value=httpx.Response(404)
    )


@respx.mock
async def test_job_walks_issuers_and_records_progress(engine, tmp_path):
    _mock_numista({"germany": [2169]})

    run = await run_numista_catalog(
        engine,
        data_dir=tmp_path,
        api_key="k",
        user_agent="t",
        issuers=["germany", "spain"],
        langs=["en", "es"],
    )

    assert run.status == SyncStatus.SUCCEEDED
    assert run.stats["issuers_done"] == ["germany", "spain"]
    assert run.stats["types_seen"] == 1
    assert run.stats["issues_created"] == 15
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(CoinType))).scalar_one() == 1
        assert (await conn.execute(select(func.count()).select_from(CoinIssue))).scalar_one() == 15
        stored = (await conn.execute(select(SyncRun))).one()
        assert stored.job == "numista_catalog"
        assert stored.cursor is None  # only failed runs keep a cursor to resume from


@respx.mock
async def test_failure_keeps_cursor_so_the_next_run_resumes(engine, tmp_path):
    _mock_numista({"germany": [2169]})
    respx.get(f"{NUMISTA_API_BASE}/types").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "count": 1,
                    "types": [
                        t for t in load("search_germany_2euro.json")["types"] if t["id"] == 2169
                    ],
                },
            ),
            httpx.Response(500),
        ]
    )

    first = await run_numista_catalog(
        engine,
        data_dir=tmp_path,
        api_key="k",
        user_agent="t",
        issuers=["germany", "spain"],
        langs=["en"],
    )
    assert first.status == SyncStatus.FAILED
    assert first.cursor["issuers_done"] == ["germany"]

    _mock_numista({"germany": [2169]})
    second = await run_numista_catalog(
        engine,
        data_dir=tmp_path,
        api_key="k",
        user_agent="t",
        issuers=["germany", "spain"],
        langs=["en"],
    )
    assert second.status == SyncStatus.SUCCEEDED
    assert second.stats["issuers_skipped"] == ["germany"]
