"""Search the open web for a coin on sale and turn what shops publish into market observations.

For a coin: a couple of search queries -> result pages -> product pages -> price, currency,
availability -> the same listing pipeline eBay data goes through (title matching, reliability
scoring, fair-value band). Sites are remembered in `market_site` so the admin panel can switch
one off and the reader leaves refusing hosts alone for a day. No API keys anywhere."""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.catalog.ingest_ebay import IngestListingsResult, ingest_listings
from euro2core.domain.enums import ObservationKind
from euro2core.domain.models import CoinType, MarketSite
from euro2core.sources.ebay.parser import Listing
from euro2core.sources.web.discovery import search_result_urls, search_url
from euro2core.sources.web.fetcher import HostRefused, PoliteFetcher
from euro2core.sources.web.product import ProductPage, parse_product
from euro2core.sources.web.queries import shop_queries

log = logging.getLogger(__name__)

MARKETPLACE = "WEB"
SOURCE = "web"
QUERIES_PER_COIN = 2
PAGES_PER_QUERY = 8


@dataclass
class WebSearchResult:
    queries: int = 0
    pages: int = 0
    products: list[ProductPage] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    ingest: IngestListingsResult | None = None


def listing_from_product(page: ProductPage, *, observed_at: datetime) -> Listing:
    """A shop page is an ask; a sold-out one is the best 'sold at' signal a shop gives."""
    kind = ObservationKind.SOLD if page.availability == "sold_out" else ObservationKind.ASKING
    return Listing(
        listing_id=hashlib.sha1(page.url.encode()).hexdigest()[:40],
        marketplace=MARKETPLACE,
        title=page.title,
        price=page.price,
        currency=page.currency,
        kind=kind,
        url=page.url,
        observed_at=observed_at,
        end_date=observed_at if kind == ObservationKind.SOLD else None,
        condition=page.condition,
    )


def host_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


async def _site(session: AsyncSession, host: str) -> MarketSite:
    site = await session.get(MarketSite, host)
    if site is None:
        site = MarketSite(host=host, enabled=True)
        session.add(site)
        await session.flush()
    return site


async def search_coin(
    session: AsyncSession,
    fetcher: PoliteFetcher,
    coin_type: CoinType,
    title: str | None,
    *,
    now: datetime | None = None,
    max_pages: int = QUERIES_PER_COIN * PAGES_PER_QUERY,
) -> WebSearchResult:
    """Discover, read and store what the web sells for one design. Commits nothing."""
    now = now or datetime.now(UTC)
    result = WebSearchResult()
    seen: set[str] = set()
    for query in shop_queries(
        country_code=coin_type.country_code, year=coin_type.year, title=title
    )[:QUERIES_PER_COIN]:
        try:
            html = await fetcher.get(search_url(query))
        except HostRefused as exc:
            result.refused.append(str(exc))
            break
        result.queries += 1
        for url in search_result_urls(html)[:PAGES_PER_QUERY]:
            if url in seen or result.pages >= max_pages:
                continue
            seen.add(url)
            host = host_of(url)
            site = await _site(session, host)
            if not site.enabled or (site.paused_until and site.paused_until > now):
                continue
            try:
                page_html = await fetcher.get(url)
            except HostRefused as exc:
                site.last_error = str(exc)[:300]
                if fetcher.is_paused(urlparse(url).netloc.lower()):
                    site.paused_until = now + timedelta(hours=24)
                result.refused.append(str(exc))
                continue
            result.pages += 1
            site.pages_read += 1
            site.last_ok_at = now
            site.last_error = None
            product = parse_product(page_html, url)
            if product is None:
                continue
            site.listings_found += 1
            if site.name is None:
                site.name = host
            result.products.append(product)
    listings = [listing_from_product(p, observed_at=now) for p in result.products]
    result.ingest = await ingest_listings(session, listings, source_code=SOURCE)
    return result


async def sites(session: AsyncSession) -> list[MarketSite]:
    return list(
        (await session.scalars(select(MarketSite).order_by(MarketSite.listings_found.desc()))).all()
    )
