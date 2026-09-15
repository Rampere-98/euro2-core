import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.deps import LangDep, SessionDep
from euro2core.api.queries import summaries_for
from euro2core.api.ratelimit import IDENTIFY, limiter
from euro2core.api.schemas import TypeSummary
from euro2core.config import get_settings
from euro2core.domain.models import CoinType, Identification
from euro2core.vision.embedder import get_embedder
from euro2core.vision.identify import confirm, identify

router = APIRouter(prefix="/identify", tags=["vision"])

MAX_UPLOAD_BYTES = 12 * 1024 * 1024


class CandidateOut(BaseModel):
    type: TypeSummary
    image_id: uuid.UUID
    score: float
    confidence: str


class IdentifyOut(BaseModel):
    identification_id: uuid.UUID
    found_circle: bool
    crop_url: str | None  # the square the matcher actually looked at, for the user to check
    candidates: list[CandidateOut]


class ConfirmIn(BaseModel):
    type_id: uuid.UUID


@router.post("", response_model=IdentifyOut)
@limiter.limit(IDENTIFY)
async def identify_photo(
    request: Request,
    file: Annotated[UploadFile, File()],
    top_k: int = Query(default=5, ge=1, le=10),
    guided: bool = Query(default=False, description="the photo is already cropped to the coin"),
    session: AsyncSession = SessionDep,
    lang: str = LangDep,
) -> IdentifyOut:
    """Identify a 2 euro coin from a photo (JPEG/PNG/WebP, up to 12 MB). The coin is located
    automatically; pass `guided=true` when the client already framed it."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="image larger than 12 MB")
    try:
        result = await identify(
            session,
            data,
            get_embedder(),
            top_k=top_k,
            guided=guided,
            uploads_dir=get_settings().data_dir / "uploads",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    types = {
        t.id: t
        for t in [await session.get(CoinType, c.type_id) for c in result.candidates]
        if t is not None
    }
    summaries = {s.id: s for s in await summaries_for(session, list(types.values()), lang)}
    return IdentifyOut(
        identification_id=result.identification_id,
        found_circle=result.found_circle,
        crop_url=f"/identify/{result.identification_id}/crop",
        candidates=[
            CandidateOut(
                type=summaries[c.type_id],
                image_id=c.image_id,
                score=c.score,
                confidence=c.confidence,
            )
            for c in result.candidates
            if c.type_id in summaries
        ],
    )


@router.get("/{identification_id}/crop", response_class=FileResponse)
async def identification_crop(
    identification_id: uuid.UUID, session: AsyncSession = SessionDep
) -> FileResponse:
    """The 224x224 crop the matcher used, so users can see what was scanned."""
    record = await session.get(Identification, identification_id)
    if record is None or not record.image_path or not Path(record.image_path).is_file():
        raise HTTPException(status_code=404, detail="crop not found")
    return FileResponse(record.image_path, media_type="image/jpeg")


@router.post("/{identification_id}/confirm", status_code=204)
async def confirm_identification(
    identification_id: uuid.UUID, body: ConfirmIn, session: AsyncSession = SessionDep
) -> None:
    """Tell the system which coin it really was; confirmations feed future model training."""
    if await session.get(CoinType, body.type_id) is None:
        raise HTTPException(status_code=404, detail="type not found")
    if not await confirm(session, identification_id, body.type_id):
        raise HTTPException(status_code=404, detail="identification not found")
    await session.commit()
