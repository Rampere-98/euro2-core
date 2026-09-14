"""Helpers shared by ingestion and reconciliation for coin issues."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import Finish, Packaging
from euro2core.domain.models import CoinIssue, CoinType, MarketObservation


async def ensure_placeholder_issue(session: AsyncSession, coin_type: CoinType) -> None:
    """The ECB describes emissions, not mint variants. Until Numista supplies them, a single
    loose circulation issue lets listings and prices attach to the coin."""
    has_issue = (
        await session.scalars(select(CoinIssue.id).where(CoinIssue.type_id == coin_type.id))
    ).first()
    if has_issue is None:
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
