"""The app's own assistant: answers from the catalog and market, fully local."""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.auth_deps import OptionalUser
from euro2core.api.deps import SessionDep
from euro2core.platform.chat import answer
from euro2core.platform.semantic import get_text_embedder

router = APIRouter(tags=["assistant"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    type_id: uuid.UUID | None = None  # coin the user is looking at, if any
    lang: str | None = Field(default=None, pattern="^(es|en)$")


class ChatOut(BaseModel):
    text: str
    intent: str
    lang: str
    type_ids: list[uuid.UUID]
    suggestions: list[str]
    links: list[dict[str, str]]


@router.post("/assistant/chat", response_model=ChatOut)
async def chat(body: ChatIn, user: OptionalUser, session: AsyncSession = SessionDep) -> ChatOut:
    try:
        embedder = get_text_embedder()
    except Exception:  # model not downloaded yet: rules and title search still work
        embedder = None
    reply = await answer(
        session, body.message, embedder=embedder, user=user, type_id=body.type_id, lang=body.lang
    )
    return ChatOut(**reply.__dict__)
