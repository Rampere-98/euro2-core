from collections.abc import AsyncIterator

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

SUPPORTED_LANGS = ("en", "es")
DEFAULT_LANG = "en"


def get_engine_dep(request: Request) -> AsyncEngine:
    return request.app.state.engine


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.sessions
    async with factory() as session:
        yield session


def get_lang(accept_language: str | None = Header(default=None)) -> str:
    """Pick the first supported language from Accept-Language, honouring q-weights."""
    if not accept_language:
        return DEFAULT_LANG
    ranked: list[tuple[float, str]] = []
    for part in accept_language.split(","):
        tag, _, params = part.strip().partition(";")
        q = 1.0
        if params.strip().startswith("q="):
            try:
                q = float(params.strip()[2:])
            except ValueError:
                q = 0.0
        ranked.append((q, tag.strip().lower()[:2]))
    for _, lang in sorted(ranked, key=lambda x: -x[0]):
        if lang in SUPPORTED_LANGS:
            return lang
    return DEFAULT_LANG


SessionDep = Depends(get_session)
LangDep = Depends(get_lang)
