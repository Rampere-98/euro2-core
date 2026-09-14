from pathlib import Path

import httpx
import pytest
import respx

from euro2core.sources.ecb.source import ECB_SOURCE_CODE, EcbSource
from euro2core.sources.http_cache import HttpCache

FIXTURE = (Path(__file__).parent.parent / "fixtures" / "ecb" / "comm_2004.en.html").read_text(
    "utf-8"
)
URL_2004 = "https://www.ecb.europa.eu/euro/coins/comm/html/comm_2004.en.html"


@pytest.fixture
def source(tmp_path: Path) -> EcbSource:
    return EcbSource(cache=HttpCache(tmp_path / "cache" / ECB_SOURCE_CODE), user_agent="test-ua")


@respx.mock
async def test_fetch_year_parses_page_and_identifies_itself(source):
    route = respx.get(URL_2004).mock(
        return_value=httpx.Response(200, text=FIXTURE, headers={"ETag": '"abc"'})
    )
    entries = await source.fetch_year(2004)
    assert [e.country_code for e in entries] == ["VA", "IT", "SM", "FI", "LU", "GR"]
    assert route.calls.last.request.headers["User-Agent"] == "test-ua"


@respx.mock
async def test_second_fetch_revalidates_with_etag_and_reuses_cached_body(source):
    respx.get(URL_2004).mock(
        side_effect=[
            httpx.Response(200, text=FIXTURE, headers={"ETag": '"abc"'}),
            httpx.Response(304),
        ]
    )
    first = await source.fetch_year(2004)
    second = await source.fetch_year(2004)
    assert second == first
    calls = respx.calls
    assert len(calls) == 2
    assert calls[1].request.headers["If-None-Match"] == '"abc"'


@respx.mock
async def test_server_error_falls_back_to_cached_body(source):
    respx.get(URL_2004).mock(
        side_effect=[
            httpx.Response(200, text=FIXTURE, headers={"ETag": '"abc"'}),
            httpx.Response(503),
        ]
    )
    first = await source.fetch_year(2004)
    second = await source.fetch_year(2004)
    assert second == first


@respx.mock
async def test_server_error_without_cache_raises(source):
    respx.get(URL_2004).mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        await source.fetch_year(2004)


def test_cache_persists_body_and_metadata_on_disk(tmp_path: Path):
    cache = HttpCache(tmp_path)
    cache.put("https://x/y", "<html/>", etag='"e"', last_modified="Mon")
    hit = HttpCache(tmp_path).get("https://x/y")
    assert hit is not None
    assert hit.body == "<html/>"
    assert hit.etag == '"e"'
    assert hit.last_modified == "Mon"
