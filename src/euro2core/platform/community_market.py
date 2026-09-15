"""The app's own market data, independent of any third party.

Every purchase a collector records (price + date) and every sale closed between collectors
becomes a `market_observation` with source `euro2`. External APIs (eBay, Numista) only speed
things up; with use, the community trail alone sustains values, deals and the chart.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import Grade, ObservationKind, SourceKind
from euro2core.domain.models import (
    CoinIssue,
    CollectionItem,
    Listing,
    MarketObservation,
    Source,
    TextTranslation,
)

SOURCE_CODE = "euro2"
SOURCE_RANK = 30  # above eBay noise, below catalog authorities
MARKET_USER = "EURO2_USER"  # purchases collectors report on their own pieces
MARKET_PEER = "EURO2"  # listings and sales inside the app's marketplace
FACE_VALUE = Decimal("2.00")


async def community_source(session: AsyncSession) -> Source:
    source = (await session.scalars(select(Source).where(Source.code == SOURCE_CODE))).first()
    if source is None:
        source = Source(
            code=SOURCE_CODE,
            name="Euro2 collectors",
            authority_rank=SOURCE_RANK,
            kind=SourceKind.MARKET,
            base_url="euro2://",
        )
        session.add(source)
        await session.flush()
    return source


async def _title_for_issue(session: AsyncSession, issue_id: uuid.UUID) -> str:
    issue = await session.get(CoinIssue, issue_id)
    text = await session.scalar(
        select(TextTranslation.text).where(
            TextTranslation.entity == "coin_type",
            TextTranslation.entity_id == issue.type_id,
            TextTranslation.field == "title",
            TextTranslation.lang == "en",
        )
    )
    return f"{text or '2 euro'} {issue.year} {issue.mint_mark} {issue.finish.value}".strip()


def listing_url(listing_id: uuid.UUID) -> str:
    return f"euro2://listing/{listing_id}"


async def record_purchase(session: AsyncSession, item: CollectionItem) -> MarketObservation | None:
    """A collector adding a piece with what they paid is a realized price nobody else sees.
    Below face value it is a gift or a find, not a market price, and is skipped."""
    if item.acquired_price is None or item.acquired_price < FACE_VALUE:
        return None
    source = await community_source(session)
    row = MarketObservation(
        issue_id=item.issue_id,
        source_id=source.id,
        marketplace=MARKET_USER,
        observation_kind=ObservationKind.SOLD,
        price=item.acquired_price,
        grade=item.grade or Grade.UNKNOWN,
        sheldon=item.sheldon,
        listing_id=f"purchase:{item.id}",
        listing_url=f"euro2://piece/{item.id}",
        title_raw=await _title_for_issue(session, item.issue_id),
        match_confidence=1.0,  # the collector picked the exact issue
        observed_at=item.acquired_at or datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return row


async def record_listing(session: AsyncSession, listing: Listing, item: CollectionItem) -> None:
    """An active peer listing with a price is an asking observation the assistant can rank."""
    if listing.price is None:
        return
    source = await community_source(session)
    session.add(
        MarketObservation(
            issue_id=item.issue_id,
            source_id=source.id,
            marketplace=MARKET_PEER,
            observation_kind=ObservationKind.ASKING,
            price=listing.price,
            grade=item.grade or Grade.UNKNOWN,
            listing_id=str(listing.id),
            listing_url=listing_url(listing.id),
            title_raw=await _title_for_issue(session, item.issue_id),
            match_confidence=1.0,
            observed_at=listing.created_at or datetime.now(UTC),
        )
    )
    await session.flush()


async def close_listing(
    session: AsyncSession, listing: Listing, item: CollectionItem, *, sold_for: Decimal | None
) -> None:
    """Withdrawn: the ask disappears. Sold: it becomes a realized sale."""
    ask = (
        await session.scalars(
            select(MarketObservation).where(
                MarketObservation.marketplace == MARKET_PEER,
                MarketObservation.listing_id == str(listing.id),
                MarketObservation.observation_kind == ObservationKind.ASKING,
            )
        )
    ).first()
    if ask is not None:
        await session.delete(ask)
    if sold_for is not None and sold_for >= FACE_VALUE:
        source = await community_source(session)
        session.add(
            MarketObservation(
                issue_id=item.issue_id,
                source_id=source.id,
                marketplace=MARKET_PEER,
                observation_kind=ObservationKind.SOLD,
                price=sold_for,
                grade=item.grade or Grade.UNKNOWN,
                listing_id=str(listing.id),
                listing_url=listing_url(listing.id),
                title_raw=await _title_for_issue(session, item.issue_id),
                match_confidence=1.0,
                observed_at=datetime.now(UTC),
            )
        )
    await session.flush()
