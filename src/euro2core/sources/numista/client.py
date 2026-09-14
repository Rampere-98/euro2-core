import asyncio
import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from euro2core.sources.numista.parser import is_two_euro

NUMISTA_API_BASE = "https://api.numista.com/api/v3"
DEFAULT_CACHE_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_REQUESTS_PER_SECOND = 2.0
MAX_RETRIES = 3
SEARCH_PAGE_SIZE = 100

log = logging.getLogger(__name__)


class NumistaClient:
    def __init__(
        self,
        api_key: str,
        user_agent: str,
        cache_dir: Path,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("Numista API key is required (NUMISTA_API_KEY)")
        self._headers = {"Numista-API-Key": api_key, "User-Agent": user_agent}
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl_seconds
        self._min_interval = 1.0 / requests_per_second
        self._last_request = 0.0
        self.timeout = timeout

    async def get_type(self, type_id: int, lang: str = "en") -> dict[str, Any]:
        return await self._get(f"/types/{type_id}", {"lang": lang})

    async def get_issues(self, type_id: int, lang: str = "en") -> list[dict[str, Any]]:
        return await self._get(f"/types/{type_id}/issues", {"lang": lang})

    async def search_two_euro_types(self, issuer: str, lang: str = "en") -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        page = 1
        while True:
            data = await self._get(
                "/types",
                {
                    "q": "2 euro",
                    "issuer": issuer,
                    "category": "coin",
                    "lang": lang,
                    "count": SEARCH_PAGE_SIZE,
                    "page": page,
                },
            )
            batch = data.get("types", [])
            results.extend(t for t in batch if is_two_euro(t))
            if len(batch) < SEARCH_PAGE_SIZE or page * SEARCH_PAGE_SIZE >= data.get("count", 0):
                return results
            page += 1

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        cache_file = self._cache_path(path, params)
        cached = self._read_cache(cache_file)
        if cached is not None:
            return cached
        for attempt in range(MAX_RETRIES + 1):
            await self._throttle()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{NUMISTA_API_BASE}{path}", params=params, headers=self._headers
                )
            if response.status_code == 429 and attempt < MAX_RETRIES:
                delay = float(response.headers.get("Retry-After", 2 ** (attempt + 1)))
                log.warning("Numista rate limit hit, retrying in %.0fs", delay)
                await asyncio.sleep(delay)
                continue
            response.raise_for_status()
            data = response.json()
            self._write_cache(cache_file, data)
            return data
        raise RuntimeError("unreachable")

    async def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()

    def _cache_path(self, path: str, params: dict[str, Any]) -> Path:
        key = hashlib.sha1(f"{path}?{json.dumps(params, sort_keys=True)}".encode()).hexdigest()
        return self.cache_dir / f"{key}.json"

    def _read_cache(self, file: Path) -> Any | None:
        if not file.exists():
            return None
        age = datetime.now(UTC).timestamp() - file.stat().st_mtime
        if age > self.cache_ttl:
            return None
        return json.loads(file.read_text("utf-8"))

    def _write_cache(self, file: Path, data: Any) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
