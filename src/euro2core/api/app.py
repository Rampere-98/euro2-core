from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from euro2core.api.routers import events, health, images, issues, search, sources, sync, types
from euro2core.db import get_engine


def create_app(engine: AsyncEngine | None = None) -> FastAPI:
    def bind(app: FastAPI, bound: AsyncEngine) -> None:
        app.state.engine = bound
        app.state.sessions = async_sessionmaker(bound, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not hasattr(app.state, "engine"):
            bind(app, get_engine())
        yield

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
    ):
        app.include_router(router)
    return app
