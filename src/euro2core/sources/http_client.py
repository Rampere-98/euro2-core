import logging

import httpx

from euro2core.sources.http_cache import HttpCache

log = logging.getLogger(__name__)


class CachingFetcher:
    """GET with conditional revalidation; serves the cached body when the origin fails."""

    def __init__(self, cache: HttpCache, user_agent: str, timeout: float = 30.0) -> None:
        self.cache = cache
        self.user_agent = user_agent
        self.timeout = timeout

    async def get_text(self, url: str) -> str:
        cached = self.cache.get(url)
        headers = {"User-Agent": self.user_agent}
        if cached:
            if cached.etag:
                headers["If-None-Match"] = cached.etag
            if cached.last_modified:
                headers["If-Modified-Since"] = cached.last_modified
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
        if response.status_code == 304 and cached:
            return cached.body
        if response.is_server_error and cached:
            log.warning("%s -> %s, serving cached copy", url, response.status_code)
            return cached.body
        response.raise_for_status()
        self.cache.put(
            url,
            response.text,
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
        )
        return response.text
