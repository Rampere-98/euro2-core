import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.deps import SessionDep
from euro2core.domain.models import CoinImage

router = APIRouter(prefix="/images", tags=["catalog"])


@router.get("/{image_id}")
async def get_image(image_id: uuid.UUID, session: AsyncSession = SessionDep) -> FileResponse:
    image = await session.get(CoinImage, image_id)
    if image is None or not Path(image.local_path).is_file():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(image.local_path)
