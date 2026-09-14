from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.deps import SessionDep

router = APIRouter(tags=["system"])


@router.get("/health")
async def health(session: AsyncSession = SessionDep) -> dict[str, str]:
    try:
        await session.execute(text("select 1"))
        database = "ok"
    except Exception:  # surface any connectivity problem as a status, not a 500
        database = "unreachable"
    return {"status": "ok" if database == "ok" else "degraded", "database": database}
