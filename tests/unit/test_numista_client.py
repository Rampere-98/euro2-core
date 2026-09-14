import json
from pathlib import Path

import httpx
import pytest
import respx

from euro2core.sources.numista.client import NUMISTA_API_BASE, NumistaClient

FIXTURES = Path(__file__).parent.parent / "fixtures" / "numista"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text("utf-8"))


@pytest.fixture
def client(tmp_path: Path) -> NumistaClient:
    return NumistaClient(
        api_key="secret-key",
        user_agent="test-ua",
        cache_dir=tmp_path,
        cache_ttl_seconds=3600,
        requests_per_second=1000,
    )


@respx.mock
async def test_sends_api_key_header_and_user_agent(client):
    route = respx.get(f"{NUMISTA_API_BASE}/types/2169").mock(
        return_value=httpx.Response(200, json=fixture("type_2169.json"))
    )
    data = await client.get_type(2169, lang="en")
    assert data["id"] == 2169
    req = route.calls.last.request
    assert req.headers["Numista-API-Key"] == "secret-key"
    assert req.headers["User-Agent"] == "test-ua"
    assert req.url.params["lang"] == "en"


@respx.mock
async def test_identical_request_within_ttl_is_served_from_disk_cache(client):
    route = respx.get(f"{NUMISTA_API_BASE}/types/2169/issues").mock(
        return_value=httpx.Response(200, json=fixture("type_2169_issues.json"))
    )
    first = await client.get_issues(2169)
    second = await client.get_issues(2169)
    assert first == second
    assert route.call_count == 1


@respx.mock
async def test_different_lang_is_a_different_cache_entry(client):
    route = respx.get(f"{NUMISTA_API_BASE}/types/2169").mock(
        side_effect=[
            httpx.Response(200, json=fixture("type_2169.json")),
            httpx.Response(200, json=fixture("type_2169_es.json")),
        ]
    )
    await client.get_type(2169, lang="en")
    es = await client.get_type(2169, lang="es")
    assert route.call_count == 2
    assert "níquel" in es["composition"]["text"]


@respx.mock
async def test_search_two_euro_types_pages_and_filters(client):
    respx.get(f"{NUMISTA_API_BASE}/types").mock(
        return_value=httpx.Response(200, json=fixture("search_germany_2euro.json"))
    )
    types = await client.search_two_euro_types("germany", lang="en")
    assert len(types) == 38
    assert all(t["title"].startswith("2 Euro") for t in types)


@respx.mock
async def test_429_is_retried_after_the_advertised_delay(client, monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("euro2core.sources.numista.client.asyncio.sleep", fake_sleep)
    respx.get(f"{NUMISTA_API_BASE}/types/2169/issues").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json=fixture("type_2169_issues.json")),
        ]
    )
    data = await client.get_issues(2169)
    assert len(data) == 15
    assert 2.0 in sleeps


@respx.mock
async def test_client_error_is_not_cached_and_raises(client):
    route = respx.get(f"{NUMISTA_API_BASE}/types/999999").mock(
        return_value=httpx.Response(404, json={"error": "not found"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_type(999999, lang="en")
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_type(999999, lang="en")
    assert route.call_count == 2
