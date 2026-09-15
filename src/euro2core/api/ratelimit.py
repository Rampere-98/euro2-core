"""Per-IP limits for the endpoints that cost CPU or could be abused (registration, login,
photo identification, assistant). Generous for humans, tight for scripts."""

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

IDENTIFY = "30/minute"
CHAT = "60/minute"
REGISTER = "10/hour"
LOGIN = "30/minute"


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"demasiadas peticiones: límite {exc.detail}"},
    )
