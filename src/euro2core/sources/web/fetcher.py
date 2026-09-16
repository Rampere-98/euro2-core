"""A polite page fetcher: honours robots.txt per host, spaces requests, and leaves a host
alone for a while after it refuses us (403/429 or a bot challenge). It never tries to get
around a block: what a site does not want to give a program, the app shows as a link."""

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger(__name__)

PAUSE_AFTER_REFUSAL = timedelta(hours=24)
MIN_GAP_SECONDS = 1.5
MAX_BODY = 2_000_000
CHALLENGE_MARKERS = ("captcha", "cf-challenge", "challenge-platform", "are you a human")


class HostRefused(Exception):
    """The host said no (robots, 403/429, challenge); do not ask again for a while."""


class PoliteFetcher:
    def __init__(self, user_agent: str, *, timeout: float = 20.0) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self._robots: dict[str, tuple[RobotFileParser | None, float]] = {}
        self._last_hit: dict[str, float] = {}
        self.paused_until: dict[str, datetime] = {}

    def is_paused(self, host: str, now: datetime | None = None) -> bool:
        until = self.paused_until.get(host)
        return until is not None and until > (now or datetime.now(UTC))

    def pause(self, host: str, reason: str) -> None:
        self.paused_until[host] = datetime.now(UTC) + PAUSE_AFTER_REFUSAL
        log.info("%s refused (%s); leaving it alone for a day", host, reason)

    async def allowed(self, client: httpx.AsyncClient, url: str) -> bool:
        parts = urlparse(url)
        host = parts.netloc.lower()
        cached = self._robots.get(host)
        if cached is None or time.monotonic() - cached[1] > 86_400:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                r = await client.get(f"{parts.scheme}://{parts.netloc}/robots.txt")
                if r.status_code == 200:
                    parser.parse(r.text.splitlines())
                elif r.status_code in (401, 403):
                    parser = None  # the site will not even show its rules: stay away
                else:
                    parser.parse([])  # no robots.txt: everything is allowed
            except httpx.HTTPError:
                parser.parse([])
            self._robots[host] = (parser, time.monotonic())
            cached = self._robots[host]
        parser = cached[0]
        return parser is not None and parser.can_fetch(self.user_agent, url)

    async def get(self, url: str) -> str:
        """Body of the page, or HostRefused. Callers catch HostRefused and move on."""
        host = urlparse(url).netloc.lower()
        if self.is_paused(host):
            raise HostRefused(f"{host} paused")
        async with httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=True, headers={"User-Agent": self.user_agent}
        ) as client:
            if not await self.allowed(client, url):
                self.pause(host, "robots.txt")
                raise HostRefused(f"{host} disallows {url} in robots.txt")
            gap = MIN_GAP_SECONDS - (time.monotonic() - self._last_hit.get(host, 0))
            if gap > 0:
                await asyncio.sleep(gap)
            self._last_hit[host] = time.monotonic()
            try:
                r = await client.get(url)
            except httpx.HTTPError as exc:
                raise HostRefused(f"{host}: {exc.__class__.__name__}") from exc
        if r.status_code in (401, 403, 429, 503):
            self.pause(host, f"HTTP {r.status_code}")
            raise HostRefused(f"{host} answered {r.status_code}")
        if r.status_code >= 400:
            raise HostRefused(f"{host} answered {r.status_code}")
        body = r.text[:MAX_BODY]
        if len(body) < 20_000 and any(m in body.lower() for m in CHALLENGE_MARKERS):
            self.pause(host, "bot challenge")
            raise HostRefused(f"{host} served a bot challenge")
        return body
