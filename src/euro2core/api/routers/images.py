import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.deps import SessionDep
from euro2core.config import get_settings
from euro2core.domain.models import CoinImage

router = APIRouter(prefix="/images", tags=["catalog"])


@router.get("/{image_id}")
async def get_image(image_id: uuid.UUID, session: AsyncSession = SessionDep) -> FileResponse:
    image = await session.get(CoinImage, image_id)
    if image is None or not image.local_path:
        raise HTTPException(status_code=404, detail="image not found")
    path = Path(image.local_path).resolve()
    images_root = get_settings().images_dir.resolve()
    # local_path is data written by ingestion; never serve anything outside the image store
    if not path.is_relative_to(images_root) or not path.is_file():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(path)
