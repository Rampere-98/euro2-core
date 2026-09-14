"""Accounts and login tokens."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.models import User

_hasher = PasswordHasher()
ALGORITHM = "HS256"


class AuthError(Exception):
    pass


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


async def register(
    session: AsyncSession, *, email: str, password: str, display_name: str, country_code: str | None
) -> User:
    email = email.strip().lower()
    if len(password) < 8:
        raise AuthError("password must be at least 8 characters")
    exists = await session.scalar(select(User.id).where(func.lower(User.email) == email))
    if exists is not None:
        raise AuthError("email already registered")
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name.strip()[:60] or email.split("@")[0],
        country_code=country_code,
    )
    session.add(user)
    await session.flush()
    return user


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User:
    user = (
        await session.scalars(select(User).where(func.lower(User.email) == email.strip().lower()))
    ).first()
    if user is None or not verify_password(password, user.password_hash):
        raise AuthError("invalid email or password")
    return user


def _key(secret: str) -> bytes:
    # any configured string becomes a 32-byte HMAC key, as RFC 7518 requires for HS256
    return hashlib.sha256(secret.encode()).digest()


def issue_token(user: User, secret: str, hours: int) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user.id), "iat": now, "exp": now + timedelta(hours=hours)}
    return jwt.encode(payload, _key(secret), algorithm=ALGORITHM)


def user_id_from_token(token: str, secret: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, _key(secret), algorithms=[ALGORITHM])
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise AuthError("invalid or expired token") from exc
