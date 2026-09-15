"""CORS whose allowed origins come from the admin panel (or .env) and can change at runtime:
the list is re-read from the database at most once a minute. Empty list = any origin, which
is what a development server wants."""

import time

from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send

from euro2core.platform.credentials import credentials

REFRESH_SECONDS = 60
ALLOW_METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
ALLOW_HEADERS = "Authorization, Content-Type, Accept-Language"


class DynamicCORSMiddleware:
    def __init__(self, app: ASGIApp, sessions_getter) -> None:
        self.app = app
        self.sessions_getter = sessions_getter  # returns the app's async_sessionmaker
        self._origins: list[str] = []
        self._loaded_at = 0.0

    async def _origins_now(self) -> list[str]:
        if time.monotonic() - self._loaded_at > REFRESH_SECONDS:
            sessions: async_sessionmaker = self.sessions_getter()
            try:
                async with sessions() as session:
                    self._origins = (await credentials(session)).public_origins
            except Exception:  # database hiccup: keep the last list
                pass
            self._loaded_at = time.monotonic()
        return self._origins

    def _allowed(self, origin: str | None, origins: list[str]) -> str | None:
        if origin is None:
            return None
        if not origins:
            return "*"
        return origin if origin in origins else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        allow = self._allowed(origin, await self._origins_now()) if origin else None

        if scope["method"] == "OPTIONS" and "access-control-request-method" in headers:
            status = 200 if allow else 403
            response_headers = [(b"content-length", b"0")]
            if allow:
                response_headers += [
                    (b"access-control-allow-origin", allow.encode()),
                    (b"access-control-allow-methods", ALLOW_METHODS.encode()),
                    (b"access-control-allow-headers", ALLOW_HEADERS.encode()),
                    (b"access-control-max-age", b"600"),
                    (b"vary", b"Origin"),
                ]
            await send(
                {"type": "http.response.start", "status": status, "headers": response_headers}
            )
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_cors(message):
            if message["type"] == "http.response.start" and allow:
                h = MutableHeaders(scope=message)
                h["access-control-allow-origin"] = allow
                h["access-control-expose-headers"] = "Content-Disposition"
                h.append("vary", "Origin")
            await send(message)

        await self.app(scope, receive, send_with_cors)
