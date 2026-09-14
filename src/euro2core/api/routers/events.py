from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.deps import SessionDep
from euro2core.api.schemas import EventOut, Page
from euro2core.domain.models import DomainEvent

router = APIRouter(tags=["feed"])


@router.get("/events", response_model=Page[EventOut])
async def list_events(
    since: datetime | None = None,
    kind: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = SessionDep,
) -> Page[EventOut]:
    base = select(DomainEvent)
    if since:
        base = base.where(DomainEvent.created_at >= since)
    if kind:
        base = base.where(DomainEvent.kind == kind)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await session.scalars(
            base.order_by(DomainEvent.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return Page(
        items=[EventOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )
