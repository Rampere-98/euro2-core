from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.deps import get_session
from euro2core.config import get_settings
from euro2core.domain.enums import Plan, Role
from euro2core.domain.models import User
from euro2core.platform.auth import AuthError, user_id_from_token


async def optional_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        user_id = user_id_from_token(
            authorization.split(" ", 1)[1].strip(), get_settings().secret_key
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="unknown user")
    return user


async def current_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="login required")
    return user


async def pro_user(user: Annotated[User, Depends(current_user)]) -> User:
    if user.plan != Plan.PRO and user.role != Role.ADMIN:
        raise HTTPException(status_code=402, detail="this feature needs the Pro plan")
    return user


async def expert_user(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role not in (Role.EXPERT, Role.ADMIN):
        raise HTTPException(status_code=403, detail="experts only")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]
ProUser = Annotated[User, Depends(pro_user)]
ExpertUser = Annotated[User, Depends(expert_user)]
