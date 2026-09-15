import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.deps import SessionDep
from euro2core.api.routers.admin import AdminUser
from euro2core.api.schemas import Page, SyncRunOut
from euro2core.config import get_settings
from euro2core.domain.models import SyncRun
from euro2core.scheduler.jobs import is_running
from euro2core.scheduler.service import JOB_SPECS, JobFactory

log = logging.getLogger(__name__)
router = APIRouter(prefix="/sync", tags=["system"])

JOBS: dict[str, JobFactory] = {name: runner for name, _, runner in JOB_SPECS}


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
async def trigger_job(
    job: str, request: Request, background: BackgroundTasks, _: AdminUser
) -> dict[str, str]:
    runner = JOBS.get(job)
    if runner is None:
        raise HTTPException(status_code=404, detail=f"unknown job; known: {sorted(JOBS)}")
    if is_running(job):
        raise HTTPException(status_code=409, detail=f"{job} is already running")

    async def run() -> None:
        try:
            await runner(request.app.state.engine, settings=get_settings())
        except Exception:  # the job records its own failure; never crash the server
            log.exception("background job %s crashed", job)

    background.add_task(run)
    return {"job": job, "status": "scheduled"}
