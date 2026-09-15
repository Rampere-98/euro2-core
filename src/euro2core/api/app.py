import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from euro2core.api.routers import (
    assistant,
    auth,
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
from euro2core.scheduler.service import build_scheduler

log = logging.getLogger(__name__)

# Flutter web build (app/build/web) served at /app when present, so a single
# `euro2 serve` gives both the API and the UI on one origin.
WEB_BUILD_DIR = Path(__file__).resolve().parents[3] / "app" / "build" / "web"


def create_app(engine: AsyncEngine | None = None, *, scheduler: bool = False) -> FastAPI:
    def bind(app: FastAPI, bound: AsyncEngine) -> None:
        app.state.engine = bound
        app.state.sessions = async_sessionmaker(bound, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
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
    # Native builds (Android/iOS) and `flutter run -d chrome` call the API cross-origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
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
    ):
        app.include_router(router)
    if WEB_BUILD_DIR.is_dir():
        app.mount("/app", StaticFiles(directory=WEB_BUILD_DIR, html=True), name="app")
    return app
