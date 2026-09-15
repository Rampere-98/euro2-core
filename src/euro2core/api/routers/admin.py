"""Everything the owner configures from the app (Ajustes → Administración): API keys and
server settings, scheduler jobs, users, logs, statistics, maintenance, backups, updates."""

import asyncio
import logging
import os
import shutil
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.auth_deps import current_user
from euro2core.api.deps import SessionDep
from euro2core.config import get_settings
from euro2core.domain.enums import Plan, Role
from euro2core.domain.models import (
    CoinImage,
    CoinIssue,
    CoinType,
    CollectionItem,
    JobConfig,
    MarketObservation,
    Source,
    SyncRun,
    User,
)
from euro2core.platform import logbuffer
from euro2core.platform.auth import AuthError, user_id_from_token
from euro2core.platform.credentials import credentials
from euro2core.platform.settings_store import SPEC_BY_KEY, SettingsStore
from euro2core.scheduler.jobs import is_running
from euro2core.scheduler.service import JOB_LABELS_ES, JOB_NEEDS, JOB_SPECS

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])
VERSION = "0.2.0"


async def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="admins only")
    return user


AdminUser = Annotated[User, Depends(admin_user)]


def _store(session: AsyncSession) -> SettingsStore:
    return SettingsStore(session, get_settings().secret_key)


def _env_view() -> dict[str, Any]:
    s = get_settings()
    return {
        "numista_api_key": s.numista_api_key,
        "ebay_client_id": s.ebay_client_id,
        "ebay_client_secret": s.ebay_client_secret,
        "user_agent": s.user_agent,
        "public_origins": s.public_origins,
    }


# ------------------------------------------------------------------ settings


@router.get("/settings")
async def get_settings_view(_: AdminUser, session: AsyncSession = SessionDep) -> list[dict]:
    return await _store(session).view(_env_view())


class SettingsIn(BaseModel):
    values: dict[str, Any]


@router.put("/settings")
async def put_settings(
    body: SettingsIn, _: AdminUser, session: AsyncSession = SessionDep
) -> list[dict]:
    store = _store(session)
    for key, value in body.values.items():
        if key not in SPEC_BY_KEY:
            raise HTTPException(status_code=422, detail=f"unknown setting {key}")
        if value is None or value == "":
            await store.delete(key)  # back to .env / default
        else:
            await store.set(key, value)
    await session.commit()
    return await store.view(_env_view())


class TestIn(BaseModel):
    source: str = Field(pattern="^(numista|ebay)$")


@router.post("/settings/test")
async def test_source(body: TestIn, _: AdminUser, session: AsyncSession = SessionDep) -> dict:
    """One real call with the stored credentials, so the admin knows a key works."""
    creds = await credentials(session)
    try:
        if body.source == "numista":
            if not creds.has_numista:
                return {"ok": False, "detail": "no hay clave de Numista"}
            from euro2core.sources.numista.client import NumistaClient

            client = NumistaClient(
                api_key=creds.numista_api_key,
                user_agent=creds.user_agent,
                cache_dir=get_settings().data_dir / "cache" / "numista-test",
                cache_ttl_seconds=0,
            )
            data = await client.get_type(2169, lang="en")
            return {"ok": True, "detail": f"Numista responde: {data.get('title', 'ok')}"}
        if not creds.has_ebay:
            return {"ok": False, "detail": "faltan Client ID / Client Secret de eBay"}
        from euro2core.sources.ebay.client import EbayClient

        client = EbayClient(
            client_id=creds.ebay_client_id,
            client_secret=creds.ebay_client_secret,
            user_agent=creds.user_agent,
        )
        await client._access_token()
        return {"ok": True, "detail": "eBay emite token OAuth: claves válidas"}
    except Exception as exc:  # the admin needs the message, not a 500
        return {"ok": False, "detail": str(exc)[:300]}


# ------------------------------------------------------------------ jobs


class JobPatch(BaseModel):
    enabled: bool | None = None
    interval_hours: float | None = Field(default=None, gt=0, le=24 * 30)


async def _job_rows(session: AsyncSession) -> list[dict]:
    configs = {c.job: c for c in (await session.scalars(select(JobConfig))).all()}
    creds = await credentials(session)
    out = []
    for job, interval, _ in JOB_SPECS:
        cfg = configs.get(job)
        last = (
            await session.scalars(
                select(SyncRun)
                .where(SyncRun.job == job)
                .order_by(SyncRun.started_at.desc())
                .limit(1)
            )
        ).first()
        needs = JOB_NEEDS.get(job)
        has_keys = {"numista": creds.has_numista, "ebay": creds.has_ebay}.get(needs, True)
        out.append(
            {
                "job": job,
                "label": JOB_LABELS_ES.get(job, job),
                "enabled": cfg.enabled if cfg else True,
                "interval_hours": cfg.interval_hours if cfg else interval.total_seconds() / 3600,
                "needs": needs,
                "has_credentials": has_keys,
                "running": is_running(job),
                "last_status": last.status.value if last else None,
                "last_started_at": last.started_at if last else None,
                "last_finished_at": last.finished_at if last else None,
                "last_stats": last.stats if last else None,
                "last_error": (last.error or "")[:400] if last else None,
            }
        )
    return out


@router.get("/jobs")
async def list_jobs(_: AdminUser, session: AsyncSession = SessionDep) -> list[dict]:
    return await _job_rows(session)


@router.patch("/jobs/{job}")
async def patch_job(
    job: str, body: JobPatch, _: AdminUser, request: Request, session: AsyncSession = SessionDep
) -> dict:
    spec = next((s for s in JOB_SPECS if s[0] == job), None)
    if spec is None:
        raise HTTPException(status_code=404, detail="unknown job")
    cfg = await session.get(JobConfig, job)
    if cfg is None:
        cfg = JobConfig(job=job, enabled=True, interval_hours=spec[1].total_seconds() / 3600)
        session.add(cfg)
    if body.enabled is not None:
        cfg.enabled = body.enabled
    if body.interval_hours is not None:
        cfg.interval_hours = body.interval_hours
    await session.commit()
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:  # apply live, no restart
        existing = scheduler.get_job(job)
        if existing is not None:
            if cfg.enabled:
                scheduler.reschedule_job(job, trigger="interval", hours=cfg.interval_hours)
                scheduler.resume_job(job)
            else:
                scheduler.pause_job(job)
    return next(r for r in await _job_rows(session) if r["job"] == job)


@router.post("/jobs/{job}/run", status_code=202)
async def run_job(
    job: str, _: AdminUser, request: Request, background: BackgroundTasks
) -> dict[str, str]:
    runner = next((r for name, _, r in JOB_SPECS if name == job), None)
    if runner is None:
        raise HTTPException(status_code=404, detail="unknown job")
    if is_running(job):
        raise HTTPException(status_code=409, detail=f"{job} is already running")

    async def run() -> None:
        try:
            await runner(request.app.state.engine, get_settings())
        except Exception:
            log.exception("admin-triggered job %s crashed", job)

    background.add_task(run)
    return {"job": job, "status": "scheduled"}


# ------------------------------------------------------------------ users


class UserPatch(BaseModel):
    role: Role | None = None
    plan: Plan | None = None


def _user_row(u: User) -> dict:
    return {
        "id": str(u.id),
        "email": u.email,
        "display_name": u.display_name,
        "country_code": u.country_code,
        "role": u.role.value,
        "plan": u.plan.value,
        "created_at": u.created_at,
    }


@router.get("/users")
async def list_users(
    _: AdminUser,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = SessionDep,
) -> list[dict]:
    stmt = select(User).order_by(User.created_at.desc()).limit(limit)
    if q:
        stmt = stmt.where(
            func.lower(User.email).contains(q.lower())
            | func.lower(User.display_name).contains(q.lower())
        )
    return [_user_row(u) for u in (await session.scalars(stmt)).all()]


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: uuid.UUID, body: UserPatch, me: AdminUser, session: AsyncSession = SessionDep
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if body.role is not None:
        if user.id == me.id and body.role != Role.ADMIN:
            raise HTTPException(status_code=409, detail="you cannot demote yourself")
        user.role = body.role
    if body.plan is not None:
        user.plan = body.plan
    await session.commit()
    return _user_row(user)


# ------------------------------------------------------------------ logs, stats, version


@router.get("/logs")
async def get_logs(_: AdminUser, lines: int = Query(default=200, ge=10, le=500)) -> list[str]:
    return logbuffer.tail(lines)


@router.get("/stats")
async def get_stats(_: AdminUser, session: AsyncSession = SessionDep) -> dict[str, Any]:
    async def count(stmt):
        return await session.scalar(select(func.count()).select_from(stmt.subquery()))

    by_source = dict(
        (
            await session.execute(
                select(Source.code, func.count())
                .join(MarketObservation, MarketObservation.source_id == Source.id)
                .group_by(Source.code)
            )
        ).all()
    )
    return {
        "types": await count(select(CoinType)),
        "issues": await count(select(CoinIssue)),
        "images_local": await count(select(CoinImage).where(CoinImage.local_path.is_not(None))),
        "users": await count(select(User)),
        "collection_items": await count(select(CollectionItem)),
        "observations_by_source": by_source,
        "version": VERSION,
        "time": datetime.now(UTC),
    }


GITHUB_MAIN = "https://api.github.com/repos/Rampere-98/euro2-core/commits/main"


@router.get("/version")
async def get_version(_: AdminUser) -> dict[str, Any]:
    """Commit this image was built from versus the latest commit on GitHub main (the image
    workflow publishes every push, so a newer commit means a newer image within minutes)."""
    running = os.environ.get("EURO2_IMAGE_SHA", "")
    updater = bool(os.environ.get("EURO2_UPDATER_URL"))
    if not running or running == "dev":  # not a published container image
        return {
            "version": VERSION,
            "image_commit": None,
            "latest_commit": None,
            "update_available": False,
            "updater": updater,
        }
    latest = None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(GITHUB_MAIN, headers={"Accept": "application/vnd.github+json"})
            if r.status_code == 200:
                latest = r.json().get("sha")
    except Exception as exc:
        log.info("GitHub unavailable: %s", exc)
    return {
        "version": VERSION,
        "image_commit": running[:12],
        "latest_commit": latest[:12] if latest else None,
        "update_available": bool(latest and not latest.startswith(running[:12])),
        "updater": updater,
    }


@router.post("/update", status_code=202)
async def request_update(_: AdminUser) -> dict[str, str]:
    """Ask the updater sidecar (docker-compose.prod.yml) to pull and restart the API."""
    url = os.environ.get("EURO2_UPDATER_URL")
    if not url:
        raise HTTPException(status_code=501, detail="updater not configured on this server")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{url}/update")
        r.raise_for_status()
    return {"status": "updating"}


# ------------------------------------------------------------------ maintenance & backup


@router.get("/backup")
async def download_backup(
    request: Request,
    session: AsyncSession = SessionDep,
    token: str | None = Query(default=None, description="bearer token, for browser downloads"),
) -> Response:
    """pg_dump of the whole database, streamed to the admin's device. A browser download
    cannot set headers, so the token may come as a query parameter."""
    raw = token or (request.headers.get("authorization") or "").split(" ")[-1]
    try:
        user = await session.get(User, user_id_from_token(raw, get_settings().secret_key))
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if user is None or user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="admins only")
    pg_dump = shutil.which("pg_dump")
    if pg_dump is None:
        raise HTTPException(status_code=501, detail="pg_dump is not installed on this server")
    url = str(get_settings().database_url).replace("postgresql+asyncpg://", "postgresql://")
    proc = await asyncio.create_subprocess_exec(
        pg_dump, "--format=custom", "--no-owner", url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=err.decode(errors="replace")[:400])
    name = f"euro2-{datetime.now(UTC):%Y%m%d-%H%M}.dump"
    return Response(
        out,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
