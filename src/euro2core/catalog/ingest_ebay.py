import logging
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.catalog.seed import get_source
from euro2core.domain.models import MarketObservation
from euro2core.pricing.matcher import match_listing
from euro2core.sources.ebay.parser import Listing

log = logging.getLogger(__name__)


@dataclass
class IngestListingsResult:
    stored: int = 0
    updated: int = 0
    discarded: int = 0


async def ingest_listings(
    session: AsyncSession, listings: Iterable[Listing]
) -> IngestListingsResult:
    source = await get_source(session, "ebay")
    result = IngestListingsResult()
    for listing in listings:
        match = await match_listing(session, listing.title)
        if match is None:
            result.discarded += 1
            continue
        row = (
            await session.scalars(
                select(MarketObservation).where(
                    MarketObservation.marketplace == listing.marketplace,
                    MarketObservation.listing_id == listing.listing_id,
                    MarketObservation.observation_kind == listing.kind,
                )
            )
        ).first()
        if row is None:
            session.add(
                MarketObservation(
                    issue_id=match.issue_id,
                    source_id=source.id,
                    marketplace=listing.marketplace,
                    observation_kind=listing.kind,
                    price=listing.price,
                    currency=listing.currency,
                    grade=match.grade,
                    sheldon=match.sheldon,
                    certified_by=match.certified_by,
                    listing_id=listing.listing_id,
                    listing_url=listing.url,
                    title_raw=listing.title,
                    match_confidence=match.confidence,
                    observed_at=listing.observed_at,
                )
            )
            result.stored += 1
        else:
            row.issue_id = match.issue_id
            row.price = listing.price
            row.grade = match.grade
            row.match_confidence = match.confidence
            row.observed_at = listing.observed_at
            row.title_raw = listing.title
            result.updated += 1
    await session.flush()
    return result
