"""Attach the ECB's official national-side photo to every circulation coin type."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.catalog.ingest_ecb import ECB_IMAGE_AUTHOR, ECB_IMAGE_LICENSE
from euro2core.domain.enums import CoinKind, ImageSide
from euro2core.domain.models import CoinImage, CoinType
from euro2core.images.fetcher import ImageFetcher
from euro2core.sources.ecb.national import NationalSideImage, assign_images_to_years

log = logging.getLogger(__name__)


async def ingest_national_sides(
    session: AsyncSession,
    country_code: str,
    images: list[NationalSideImage],
    fetcher: ImageFetcher,
) -> int:
    """Give each circulation type of the country the design current in its first year.
    Returns the number of images stored; already-attached ones are skipped."""
    types = (
        await session.scalars(
            select(CoinType).where(
                CoinType.country_code == country_code, CoinType.kind == CoinKind.CIRCULATION
            )
        )
    ).all()
    if not types:
        return 0
    by_year = assign_images_to_years(images, sorted({t.year for t in types}))
    stored = 0
    for coin_type in types:
        url = by_year.get(coin_type.year)
        if url is None:
            continue
        existing = await session.scalar(
            select(CoinImage).where(CoinImage.type_id == coin_type.id, CoinImage.source_url == url)
        )
        if existing is not None:
            continue
        try:
            fetched = await fetcher.fetch(url, f"circulation/{country_code}")
        except Exception as exc:  # one broken photo must not stop the country
            log.warning("national side fetch failed for %s: %s", url, exc)
            continue
        session.add(
            CoinImage(
                type_id=coin_type.id,
                side=ImageSide.OBVERSE,
                local_path=str(fetched.local_path),
                source_url=url,
                license=ECB_IMAGE_LICENSE,
                author=ECB_IMAGE_AUTHOR,
                sha256=fetched.sha256,
            )
        )
        stored += 1
    return stored
