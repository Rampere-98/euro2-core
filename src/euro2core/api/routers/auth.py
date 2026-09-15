import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.auth_deps import CurrentUser
from euro2core.api.deps import SessionDep
from euro2core.api.ratelimit import LOGIN, REGISTER, limiter
from euro2core.config import get_settings
from euro2core.domain.enums import Plan
from euro2core.domain.models import User
from euro2core.platform.auth import AuthError, authenticate, issue_token, register
from euro2core.platform.credentials import credentials

router = APIRouter(tags=["account"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=60)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    plan: Plan
    role: str
    country_code: str | None
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=60)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)


def _token_for(user) -> TokenOut:
    settings = get_settings()
    return TokenOut(
        access_token=issue_token(user, settings.secret_key, settings.token_hours),
        user=UserOut.model_validate(user),
    )


@router.post("/auth/register", response_model=TokenOut, status_code=201)
@limiter.limit(REGISTER)
async def register_account(
    request: Request, body: RegisterIn, session: AsyncSession = SessionDep
) -> TokenOut:
    creds = await credentials(session)
    if not creds.registration_open and await session.scalar(select(func.count()).select_from(User)):
        raise HTTPException(status_code=403, detail="registration is closed")
    try:
        user = await register(
            session,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            country_code=body.country_code.upper() if body.country_code else None,
        )
    except AuthError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return _token_for(user)


@router.post("/auth/login", response_model=TokenOut)
@limiter.limit(LOGIN)
async def login(request: Request, body: LoginIn, session: AsyncSession = SessionDep) -> TokenOut:
    try:
        user = await authenticate(session, email=body.email, password=body.password)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return _token_for(user)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
async def update_profile(
    body: ProfileIn, user: CurrentUser, session: AsyncSession = SessionDep
) -> UserOut:
    if body.display_name:
        user.display_name = body.display_name
    if body.country_code:
        user.country_code = body.country_code.upper()
    await session.commit()
    return UserOut.model_validate(user)


@router.post("/me/plan/pro", response_model=UserOut)
async def upgrade_to_pro(user: CurrentUser, session: AsyncSession = SessionDep) -> UserOut:
    """Activate the Pro plan. Payment is not wired yet: this is where the store receipt would be
    verified before flipping the plan."""
    user.plan = Plan.PRO
    await session.commit()
    return UserOut.model_validate(user)
