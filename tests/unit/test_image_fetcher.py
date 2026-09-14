import hashlib
from pathlib import Path

import httpx
import pytest
import respx

from euro2core.images.fetcher import ImageFetcher

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def fetcher(tmp_path: Path) -> ImageFetcher:
    return ImageFetcher(root=tmp_path / "images", user_agent="test-ua")


@respx.mock
async def test_downloads_into_a_folder_per_coin_and_records_hash(fetcher, tmp_path):
    respx.get("https://example.org/coins/Lithuania.jpg").mock(
        return_value=httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})
    )
    stored = await fetcher.fetch("https://example.org/coins/Lithuania.jpg", folder="2024/LT/straw")
    assert stored.local_path == tmp_path / "images" / "2024" / "LT" / "straw" / "Lithuania.jpg"
    assert stored.local_path.read_bytes() == PNG
    assert stored.sha256 == hashlib.sha256(PNG).hexdigest()
    assert stored.source_url == "https://example.org/coins/Lithuania.jpg"
    assert stored.content_type == "image/png"


@respx.mock
async def test_existing_file_with_same_bytes_is_not_downloaded_again(fetcher):
    route = respx.get("https://example.org/a.jpg").mock(
        return_value=httpx.Response(200, content=PNG, headers={"Content-Type": "image/jpeg"})
    )
    first = await fetcher.fetch("https://example.org/a.jpg", folder="x")
    second = await fetcher.fetch("https://example.org/a.jpg", folder="x")
    assert route.call_count == 1
    assert first.sha256 == second.sha256


@respx.mock
async def test_non_image_response_is_rejected(fetcher):
    respx.get("https://example.org/a.jpg").mock(
        return_value=httpx.Response(
            200, text="<html>blocked</html>", headers={"Content-Type": "text/html"}
        )
    )
    with pytest.raises(ValueError, match="not an image"):
        await fetcher.fetch("https://example.org/a.jpg", folder="x")


@respx.mock
async def test_http_error_propagates(fetcher):
    respx.get("https://example.org/a.jpg").mock(return_value=httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        await fetcher.fetch("https://example.org/a.jpg", folder="x")


def test_filename_is_derived_from_url_and_sanitized(fetcher):
    assert (
        fetcher.filename_for("https://x/comm_2024/San Marino1.jpg", "image/jpeg")
        == "San_Marino1.jpg"
    )
    assert (
        fetcher.filename_for("https://x/photos/abc.123-original.jpg?x=1", "image/jpeg")
        == "abc.123-original.jpg"
    )
    assert fetcher.filename_for("https://x/noext", "image/webp") == "noext.webp"
