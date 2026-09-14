"""Embed catalog images into pgvector so photos can be matched against them."""

import logging
from pathlib import Path

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.models import CoinImage
from euro2core.vision.embedder import ClipEmbedder
from euro2core.vision.preprocess import prepare_coin_image

log = logging.getLogger(__name__)
BATCH = 32


async def embed_missing_images(session: AsyncSession, embedder: ClipEmbedder) -> dict[str, int]:
    rows = (
        await session.scalars(
            select(CoinImage).where(
                CoinImage.local_path.is_not(None), CoinImage.embedding.is_(None)
            )
        )
    ).all()
    stats = {"embedded": 0, "unreadable": 0}
    for start in range(0, len(rows), BATCH):
        batch = rows[start : start + BATCH]
        images: list[Image.Image] = []
        kept: list[CoinImage] = []
        for row in batch:
            try:
                data = Path(row.local_path).read_bytes()
                images.append(prepare_coin_image(data).image)
                kept.append(row)
            except (OSError, ValueError) as exc:
                stats["unreadable"] += 1
                log.warning("cannot embed %s: %s", row.local_path, exc)
        if not kept:
            continue
        vectors = embedder.embed_images(images)
        for row, vector in zip(kept, vectors, strict=True):
            row.embedding = vector.tolist()
        stats["embedded"] += len(kept)
        await session.flush()
    return stats
