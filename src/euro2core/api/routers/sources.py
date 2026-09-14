from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.deps import SessionDep
from euro2core.api.schemas import SourceOut
from euro2core.domain.models import Source

router = APIRouter(tags=["system"])


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(session: AsyncSession = SessionDep) -> list[SourceOut]:
    rows = (await session.scalars(select(Source).order_by(Source.authority_rank.desc()))).all()
    return [SourceOut.model_validate(r) for r in rows]
