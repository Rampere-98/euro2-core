"""A collection: pieces, provenance events and live net worth."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import Grade
from euro2core.domain.models import CoinIssue, CollectionItem, PieceEvent, User
from euro2core.platform.valuation import Valuation, valuations_for


class PortfolioError(Exception):
    pass


@dataclass
class ValuedItem:
    item: CollectionItem
    valuation: Valuation


async def add_item(
    session: AsyncSession,
    user: User,
    *,
    issue_id: uuid.UUID,
    grade: Grade = Grade.UNKNOWN,
    sheldon: int | None = None,
    acquired_price: Decimal | None = None,
    acquired_at: datetime | None = None,
    notes: str | None = None,
) -> CollectionItem:
    if await session.get(CoinIssue, issue_id) is None:
        raise PortfolioError("issue not found")
    item = CollectionItem(
        user_id=user.id,
        issue_id=issue_id,
        grade=grade,
        sheldon=sheldon,
        acquired_price=acquired_price,
        acquired_at=acquired_at,
        notes=notes,
    )
    session.add(item)
    await session.flush()
    session.add(
        PieceEvent(item_id=item.id, kind="registered", to_user_id=user.id, price=acquired_price)
    )
    await session.flush()
    return item


async def remove_item(session: AsyncSession, user: User, item_id: uuid.UUID) -> bool:
    item = await session.get(CollectionItem, item_id)
    if item is None or item.user_id != user.id:
        return False
    await session.delete(item)
    await session.flush()
    return True


async def list_items(session: AsyncSession, user_id: uuid.UUID) -> list[ValuedItem]:
    items = (
        await session.scalars(
            select(CollectionItem)
            .where(CollectionItem.user_id == user_id)
            .order_by(CollectionItem.created_at.desc())
        )
    ).all()
    values = await valuations_for(session, [(i.issue_id, i.grade) for i in items])
    return [ValuedItem(i, values[(i.issue_id, i.grade)]) for i in items]


def net_worth(items: list[ValuedItem]) -> dict[str, Any]:
    total = sum((v.valuation.value for v in items), Decimal("0"))
    cost = sum((v.item.acquired_price or Decimal("0") for v in items), Decimal("0"))
    by_basis: dict[str, Decimal] = {}
    for v in items:
        by_basis[v.valuation.basis] = by_basis.get(v.valuation.basis, Decimal("0")) + (
            v.valuation.value
        )
    return {
        "pieces": len(items),
        "value": total,
        "cost": cost,
        "gain": total - cost,
        "value_by_basis": by_basis,
        "computed_at": datetime.now(UTC),
    }


async def transfer_item(
    session: AsyncSession,
    item: CollectionItem,
    *,
    to_user: User,
    kind: str,
    price: Decimal | None,
    details: dict[str, Any] | None = None,
) -> None:
    from_user_id = item.user_id
    item.user_id = to_user.id
    item.acquired_price = price
    item.acquired_at = datetime.now(UTC)
    session.add(
        PieceEvent(
            item_id=item.id,
            kind=kind,
            from_user_id=from_user_id,
            to_user_id=to_user.id,
            price=price,
            details=details,
        )
    )
    await session.flush()


async def history(session: AsyncSession, item_id: uuid.UUID) -> list[PieceEvent]:
    return list(
        (
            await session.scalars(
                select(PieceEvent).where(PieceEvent.item_id == item_id).order_by(PieceEvent.at)
            )
        ).all()
    )
