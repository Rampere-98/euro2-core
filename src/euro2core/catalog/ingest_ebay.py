import logging
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.catalog.seed import get_source
from euro2core.domain.enums import ObservationKind
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
    session: AsyncSession, listings: Iterable[Listing], *, source_code: str = "ebay"
) -> IngestListingsResult:
    source = await get_source(session, source_code)
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
                    ends_at=listing.end_date,
                )
            )
            result.stored += 1
        else:
            row.price = listing.price
            row.observed_at = listing.observed_at
            row.ends_at = listing.end_date
            row.title_raw = listing.title
            if listing.kind not in REALIZED:
                # active listings follow the catalog as it grows; a recorded sale never migrates
                row.issue_id = match.issue_id
                row.grade = match.grade
                row.match_confidence = match.confidence
            result.updated += 1
    await session.flush()
    return result


REALIZED = frozenset({ObservationKind.SOLD, ObservationKind.AUCTION_CLOSED})


async def close_auction(
    session: AsyncSession, open_row: MarketObservation, sale: Listing
) -> MarketObservation:
    """Record the realized sale of a tracked auction, inheriting the issue and grade that were
    resolved while it was open, then drop the open-bid row (a bid is not a price signal)."""
    closed = MarketObservation(
        issue_id=open_row.issue_id,
        source_id=open_row.source_id,
        marketplace=open_row.marketplace,
        observation_kind=ObservationKind.AUCTION_CLOSED,
        price=sale.price,
        currency=sale.currency,
        grade=open_row.grade,
        sheldon=open_row.sheldon,
        certified_by=open_row.certified_by,
        listing_id=open_row.listing_id,
        listing_url=open_row.listing_url,
        title_raw=open_row.title_raw,
        match_confidence=open_row.match_confidence,
        observed_at=sale.observed_at,
        ends_at=sale.end_date,
    )
    session.add(closed)
    await session.delete(open_row)
    await session.flush()
    return closed
