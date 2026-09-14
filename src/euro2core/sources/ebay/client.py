import asyncio
import base64
import logging
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_BASE = "https://api.ebay.com/buy/browse/v1"
SCOPE = "https://api.ebay.com/oauth/api_scope"
# Category filtering is opt-in: verify the marketplace's "World coins" id with a real keyset
# first, because an unknown id silently returns zero results.
COINS_CATEGORY_ID: str | None = None
DEFAULT_DAILY_BUDGET = 4500  # eBay grants 5,000 Browse calls/day to a new keyset
DEFAULT_PAGE_SIZE = 200

log = logging.getLogger(__name__)


class EbayClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        requests_per_second: float = 2.0,
        daily_budget: int = DEFAULT_DAILY_BUDGET,
        timeout: float = 30.0,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("eBay client id and secret are required (EBAY_CLIENT_ID/SECRET)")
        self._basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self.user_agent = user_agent
        self._min_interval = 1.0 / requests_per_second
        self._last_request = 0.0
        self.daily_budget = daily_budget
        self._calls_today = 0
        self._budget_day: date = datetime.now(UTC).date()
        self.timeout = timeout
        self._token: str | None = None
        self._token_expires_at = datetime.min.replace(tzinfo=UTC)

    async def search(
        self,
        q: str,
        *,
        marketplace: str,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_items: int = 1000,
        category_ids: str | None = COINS_CATEGORY_ID,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            params: dict[str, Any] = {
                "q": q,
                "limit": page_size,
                "offset": offset,
                "filter": "buyingOptions:{FIXED_PRICE|AUCTION},priceCurrency:EUR",
            }
            if category_ids:
                params["category_ids"] = category_ids
            data = await self._get("/item_summary/search", params, marketplace)
            batch = data.get("itemSummaries") or []
            items.extend(batch)
            total = int(data.get("total") or 0)
            offset += len(batch)
            if not batch or offset >= total or offset >= max_items:
                return items

    async def get_item(self, item_id: str, *, marketplace: str) -> dict[str, Any]:
        return await self._get(f"/item/{quote(item_id, safe='')}", {}, marketplace)

    async def _get(self, path: str, params: dict[str, Any], marketplace: str) -> Any:
        self._spend_budget()
        for attempt in range(2):
            await self._throttle()
            token = await self._access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": marketplace,
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            }
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{BROWSE_BASE}{path}", params=params, headers=headers)
            if response.status_code == 401 and attempt == 0:
                self._token = None
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError("unreachable")

    async def _access_token(self) -> str:
        if self._token and datetime.now(UTC) < self._token_expires_at:
            return self._token
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                TOKEN_URL,
                headers={
                    "Authorization": f"Basic {self._basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": self.user_agent,
                },
                data={"grant_type": "client_credentials", "scope": SCOPE},
            )
        response.raise_for_status()
        payload = response.json()
        self._token = payload["access_token"]
        # refresh a minute early so a request never carries a token about to expire
        self._token_expires_at = datetime.now(UTC) + timedelta(
            seconds=int(payload.get("expires_in", 7200)) - 60
        )
        return self._token

    def charge(self, calls: int) -> None:
        """Account for calls made earlier today by other client instances."""
        self._calls_today += max(0, calls)

    def _spend_budget(self) -> None:
        today = datetime.now(UTC).date()
        if today != self._budget_day:
            self._budget_day, self._calls_today = today, 0
        if self._calls_today >= self.daily_budget:
            raise RuntimeError(f"eBay daily call budget ({self.daily_budget}) exhausted")
        self._calls_today += 1

    async def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()
