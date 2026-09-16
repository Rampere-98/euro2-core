"""Per-IP limits for the endpoints that cost CPU or could be abused (registration, login,
photo identification, assistant). Generous for humans, tight for scripts."""

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from euro2core.config import get_settings


def client_ip(request: Request) -> str:
    """The visitor's address. Behind Cloudflare Tunnel (or any reverse proxy) every request
    arrives from the proxy, so with TRUST_PROXY=1 the address comes from the proxy's headers;
    without it those headers are ignored, since a direct client could forge them."""
    if get_settings().trust_proxy:
        cf = request.headers.get("cf-connecting-ip")
        if cf:
            return cf.strip()
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=client_ip)

IDENTIFY = "30/minute"
CHAT = "60/minute"
REGISTER = "10/hour"
LOGIN = "30/minute"
WEB_SEARCH = "6/minute"  # each one reads up to 16 pages from other people's sites


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"demasiadas peticiones: límite {exc.detail}"},
    )
