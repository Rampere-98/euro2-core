import logging
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from euro2core.api.deps import SessionDep
from euro2core.api.schemas import Page, SyncRunOut
from euro2core.config import Settings, get_settings
from euro2core.domain.models import SyncRun
from euro2core.scheduler import jobs

log = logging.getLogger(__name__)
router = APIRouter(prefix="/sync", tags=["system"])

Job = Callable[..., Awaitable[SyncRun]]


async def _ecb(engine: AsyncEngine, settings: Settings) -> SyncRun:
    return await jobs.run_ecb_discover(
        engine, data_dir=settings.data_dir, user_agent=settings.user_agent
    )


async def _numista(engine: AsyncEngine, settings: Settings) -> SyncRun:
    return await jobs.run_numista_catalog(
        engine,
        data_dir=settings.data_dir,
        api_key=settings.numista_api_key,
        user_agent=settings.user_agent,
    )


JOBS: dict[str, Job] = {"ecb_discover": _ecb, "numista_catalog": _numista}


@router.get("/runs", response_model=Page[SyncRunOut])
async def list_runs(
    job: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = SessionDep,
) -> Page[SyncRunOut]:
    base = select(SyncRun)
    if job:
        base = base.where(SyncRun.job == job)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await session.scalars(base.order_by(SyncRun.started_at.desc()).limit(limit).offset(offset))
    ).all()
    return Page(
        items=[SyncRunOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.post("/{job}", status_code=202)
async def trigger_job(job: str, request: Request, background: BackgroundTasks) -> dict[str, str]:
    runner = JOBS.get(job)
    if runner is None:
        raise HTTPException(status_code=404, detail=f"unknown job; known: {sorted(JOBS)}")

    async def run() -> None:
        try:
            await runner(request.app.state.engine, settings=get_settings())
        except Exception:  # the job records its own failure; never crash the server
            log.exception("background job %s crashed", job)

    background.add_task(run)
    return {"job": job, "status": "scheduled"}
