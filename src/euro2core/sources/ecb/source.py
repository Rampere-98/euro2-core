from datetime import UTC, datetime

from euro2core.sources.ecb.parser import ECB_COMM_BASE, EcbEntry, parse_commemorative_page
from euro2core.sources.http_cache import HttpCache
from euro2core.sources.http_client import CachingFetcher

ECB_SOURCE_CODE = "ecb"
ECB_AUTHORITY_RANK = 100
FIRST_COMMEMORATIVE_YEAR = 2004


class EcbSource:
    code = ECB_SOURCE_CODE
    authority_rank = ECB_AUTHORITY_RANK

    def __init__(self, cache: HttpCache, user_agent: str) -> None:
        self.fetcher = CachingFetcher(cache, user_agent)

    @staticmethod
    def page_url(year: int, lang: str = "en") -> str:
        return f"{ECB_COMM_BASE}comm_{year}.{lang}.html"

    @staticmethod
    def years(until: int | None = None) -> range:
        return range(FIRST_COMMEMORATIVE_YEAR, (until or datetime.now(UTC).year) + 1)

    async def fetch_year(self, year: int) -> list[EcbEntry]:
        html = await self.fetcher.get_text(self.page_url(year))
        return parse_commemorative_page(html, year)
