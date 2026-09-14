"""Embed catalog images into pgvector so photos can be matched against them."""

import logging
from pathlib import Path

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.models import CoinImage, ImageEmbedding
from euro2core.vision.embedder import ClipEmbedder
from euro2core.vision.preprocess import inner_core, prepare_coin_image

log = logging.getLogger(__name__)
BATCH = 8
ROTATIONS = tuple(range(0, 360, 30))  # coins are photographed at any orientation


async def embed_missing_images(session: AsyncSession, embedder: ClipEmbedder) -> dict[str, int]:
    indexed = select(ImageEmbedding.image_id).where(ImageEmbedding.rotation == 0)
    rows = (
        await session.scalars(
            select(CoinImage).where(CoinImage.local_path.is_not(None), CoinImage.id.not_in(indexed))
        )
    ).all()
    stats = {"embedded": 0, "unreadable": 0}
    for start in range(0, len(rows), BATCH):
        batch = rows[start : start + BATCH]
        views: list[Image.Image] = []
        owners: list[tuple[CoinImage, int]] = []
        for row in batch:
            try:
                base = inner_core(prepare_coin_image(Path(row.local_path).read_bytes()).image)
            except (OSError, ValueError) as exc:
                stats["unreadable"] += 1
                log.warning("cannot embed %s: %s", row.local_path, exc)
                continue
            for angle in ROTATIONS:
                views.append(base if angle == 0 else base.rotate(angle, expand=False))
                owners.append((row, angle))
        if not views:
            continue
        vectors = embedder.embed_images(views)
        for (row, angle), vector in zip(owners, vectors, strict=True):
            session.add(ImageEmbedding(image_id=row.id, rotation=angle, embedding=vector.tolist()))
            if angle == 0:
                row.embedding = vector.tolist()
        stats["embedded"] += len({id(r) for r, _ in owners})
        await session.flush()
    return stats
