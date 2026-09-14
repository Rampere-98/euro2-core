import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from euro2core.api.routers import (
    events,
    health,
    identify,
    images,
    issues,
    search,
    sources,
    sync,
    types,
)
from euro2core.config import get_settings
from euro2core.db import get_engine
from euro2core.scheduler.service import build_scheduler

log = logging.getLogger(__name__)


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
    ):
        app.include_router(router)
    return app
