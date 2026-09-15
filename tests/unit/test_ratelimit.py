import pytest
from starlette.requests import Request

from euro2core.api.ratelimit import client_ip
from euro2core.config import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _request(headers: dict[str, str], client=("10.0.0.7", 1234)) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": client,
    }
    return Request(scope)


def test_direct_connections_are_keyed_by_their_socket_address(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "0")
    assert client_ip(_request({"CF-Connecting-IP": "203.0.113.9"})) == "10.0.0.7"


def test_behind_cloudflare_the_visitor_ip_comes_from_the_tunnel_headers(monkeypatch):
    # every public request reaches the API from a Cloudflare address: without this, one visitor
    # hitting a limit would lock every other visitor out
    monkeypatch.setenv("TRUST_PROXY", "1")
    assert client_ip(_request({"CF-Connecting-IP": "203.0.113.9"})) == "203.0.113.9"
    assert client_ip(_request({"X-Forwarded-For": "198.51.100.4, 10.0.0.1"})) == "198.51.100.4"
    assert client_ip(_request({})) == "10.0.0.7"
