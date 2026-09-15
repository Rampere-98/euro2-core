"""Helpers shared by ingestion and reconciliation for coin issues."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import CoinKind, Finish, Packaging
from euro2core.domain.models import CoinIssue, CoinType, MarketObservation

GERMAN_MINTS = ("A", "D", "F", "G", "J")  # Berlin, Munich, Stuttgart, Karlsruhe, Hamburg


async def ensure_placeholder_issue(session: AsyncSession, coin_type: CoinType) -> None:
    """The ECB describes emissions, not mint variants. Until Numista supplies them, a loose
    circulation issue lets listings and prices attach to the coin. German commemoratives are
    always struck by the five federal mints in equal shares, so those five variants are
    created from the ECB total alone — no third party needed."""
    has_issue = (
        await session.scalars(select(CoinIssue.id).where(CoinIssue.type_id == coin_type.id))
    ).first()
    if has_issue is not None:
        return
    if coin_type.country_code == "DE" and coin_type.kind == CoinKind.COMMEMORATIVE:
        share = coin_type.mintage_total // len(GERMAN_MINTS) if coin_type.mintage_total else None
        for mark in GERMAN_MINTS:
            session.add(
                CoinIssue(
                    type_id=coin_type.id,
                    year=coin_type.year,
                    mint_mark=mark,
                    finish=Finish.CIRCULATION,
                    packaging=Packaging.LOOSE,
                    mintage=share,
                )
            )
    else:
        session.add(
            CoinIssue(
                type_id=coin_type.id,
                year=coin_type.year,
                mint_mark="",
                finish=Finish.CIRCULATION,
                packaging=Packaging.LOOSE,
            )
        )
    await session.flush()


async def drop_unreferenced_placeholders(session: AsyncSession, coin_type: CoinType) -> None:
    """Real Numista variants supersede the ECB placeholder unless a market observation already
    hangs off it."""
    real = (
        await session.scalars(
            select(CoinIssue.id).where(
                CoinIssue.type_id == coin_type.id, CoinIssue.numista_issue_id.is_not(None)
            )
        )
    ).first()
    if real is None:
        return
    placeholders = (
        await session.scalars(
            select(CoinIssue).where(
                CoinIssue.type_id == coin_type.id,
                CoinIssue.numista_issue_id.is_(None),
                CoinIssue.mint_mark == "",
                CoinIssue.finish == Finish.CIRCULATION,
            )
        )
    ).all()
    for placeholder in placeholders:
        referenced = (
            await session.scalars(
                select(MarketObservation.id)
                .where(MarketObservation.issue_id == placeholder.id)
                .limit(1)
            )
        ).first()
        if referenced is None:
            await session.delete(placeholder)
    await session.flush()
