import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.deps import SessionDep
from euro2core.config import get_settings
from euro2core.domain.models import CoinImage

router = APIRouter(prefix="/images", tags=["catalog"])

# Thumbnails snap to a few widths: the app asks for what its list rows need (56-180 logical px
# at 1-3x) and the browser never decodes a 1000 px JPEG to draw a 56 px circle.
THUMB_BUCKETS = (128, 256, 512)
THUMB_CACHE = "public, max-age=31536000, immutable"


@router.get("/{image_id}")
async def get_image(
    image_id: uuid.UUID,
    w: int | None = Query(default=None, ge=1, description="thumbnail width (snapped to a bucket)"),
    session: AsyncSession = SessionDep,
) -> FileResponse:
    image = await session.get(CoinImage, image_id)
    if image is None or not image.local_path:
        raise HTTPException(status_code=404, detail="image not found")
    path = Path(image.local_path).resolve()
    images_root = get_settings().images_dir.resolve()
    # local_path is data written by ingestion; never serve anything outside the image store
    if not path.is_relative_to(images_root) or not path.is_file():
        raise HTTPException(status_code=404, detail="image not found")
    if w is None:
        return FileResponse(path)
    bucket = next((b for b in THUMB_BUCKETS if w <= b), THUMB_BUCKETS[-1])
    thumb = path.with_name(f"{path.stem}_w{bucket}.webp")
    if not thumb.is_file():
        await run_in_threadpool(_write_thumbnail, path, thumb, bucket)
    return FileResponse(thumb, media_type="image/webp", headers={"Cache-Control": THUMB_CACHE})


def _write_thumbnail(source: Path, target: Path, side: int) -> None:
    with Image.open(source) as img:
        out = img.convert("RGB")
        out.thumbnail((side, side), Image.LANCZOS)  # keeps the aspect; the client clips to a circle
        tmp = target.with_suffix(".tmp")
        out.save(tmp, format="WEBP", quality=82, method=4)
        tmp.replace(target)
