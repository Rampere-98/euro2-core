import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from euro2core.api.cors import DynamicCORSMiddleware
from euro2core.api.ratelimit import _rate_limit_handler, limiter
from euro2core.api.routers import (
    admin,
    assistant,
    auth,
    chat,
    community,
    events,
    health,
    identify,
    images,
    issues,
    marketplace,
    portfolio,
    search,
    sources,
    sync,
    types,
)
from euro2core.config import get_settings
from euro2core.db import get_engine
from euro2core.platform import logbuffer
from euro2core.scheduler.service import build_scheduler

log = logging.getLogger(__name__)

# Flutter web build (app/build/web) served at /app when present, so a single
# `euro2 serve` gives both the API and the UI on one origin.
WEB_BUILD_DIR = Path(__file__).resolve().parents[3] / "app" / "build" / "web"
# Public landing page (site/) served at the root when present; API routes take precedence.
SITE_DIR = Path(__file__).resolve().parents[3] / "site"


def create_app(engine: AsyncEngine | None = None, *, scheduler: bool = False) -> FastAPI:
    def bind(app: FastAPI, bound: AsyncEngine) -> None:
        app.state.engine = bound
        app.state.sessions = async_sessionmaker(bound, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logbuffer.install()  # last log lines readable from the admin panel
        if not hasattr(app.state, "engine"):
            bind(app, get_engine())
        app.state.scheduler = None
        if scheduler:
            app.state.scheduler = await build_scheduler(app.state.engine, get_settings())
            app.state.scheduler.start()
            log.info("scheduler started")
        try:
            yield
        finally:
            if app.state.scheduler is not None:
                app.state.scheduler.shutdown(wait=False)

    app = FastAPI(
        title="euro2-core",
        version="0.1.0",
        description="Autonomous data core for 2 euro coins: catalog, variants, prices, rarity.",
        lifespan=lifespan,
    )
    if engine is not None:
        bind(app, engine)
    # Allowed origins are edited in the app (Ajustes → Administración); empty = any.
    app.add_middleware(DynamicCORSMiddleware, sessions_getter=lambda: app.state.sessions)
    # Public server: keep abusive clients from exhausting the CPU-bound endpoints.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    for router in (
        health.router,
        types.router,
        issues.router,
        search.router,
        events.router,
        sources.router,
        sync.router,
        images.router,
        identify.router,
        auth.router,
        portfolio.router,
        marketplace.router,
        community.router,
        assistant.router,
        chat.router,
        admin.router,
    ):
        app.include_router(router)
    if WEB_BUILD_DIR.is_dir():
        app.mount("/app", StaticFiles(directory=WEB_BUILD_DIR, html=True), name="app")
    if SITE_DIR.is_dir():
        app.mount("/", StaticFiles(directory=SITE_DIR, html=True), name="site")
    return app
