"""Identify a coin from a photo by nearest catalog images in embedding space."""

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.models import CoinImage, Identification
from euro2core.vision.embedder import ClipEmbedder
from euro2core.vision.preprocess import prepare_coin_image

NEIGHBOURS = 24
MIN_SCORE = 0.60  # below this the photo is probably not a catalogued 2 euro coin
CONFIDENCE = ((0.85, "high"), (0.75, "medium"), (0.0, "low"))


@dataclass(frozen=True)
class Candidate:
    type_id: uuid.UUID
    image_id: uuid.UUID
    score: float
    confidence: str


@dataclass
class IdentifyResult:
    identification_id: uuid.UUID
    found_circle: bool
    candidates: list[Candidate] = field(default_factory=list)


async def identify(
    session: AsyncSession,
    data: bytes,
    embedder: ClipEmbedder,
    *,
    top_k: int = 5,
    user_id: uuid.UUID | None = None,
    uploads_dir: Path | None = None,
) -> IdentifyResult:
    crop = prepare_coin_image(data)
    vector = embedder.embed_images([crop.image])[0].tolist()
    distance = CoinImage.embedding.cosine_distance(vector)
    rows = (
        await session.execute(
            select(CoinImage.type_id, CoinImage.id, distance)
            .where(CoinImage.embedding.is_not(None), CoinImage.type_id.is_not(None))
            .order_by(distance)
            .limit(NEIGHBOURS)
        )
    ).all()
    best: dict[uuid.UUID, Candidate] = {}
    for type_id, image_id, dist in rows:
        score = round(1.0 - float(dist), 4)
        if score < MIN_SCORE:
            continue
        if type_id not in best:
            best[type_id] = Candidate(type_id, image_id, score, _confidence(score))
    candidates = sorted(best.values(), key=lambda c: -c.score)[:top_k]

    record = Identification(
        user_id=user_id,
        found_circle=crop.found_circle,
        top_type_id=candidates[0].type_id if candidates else None,
        top_score=candidates[0].score if candidates else None,
        candidates=[{"type_id": str(c.type_id), "score": c.score} for c in candidates],
        embedding=vector,
    )
    session.add(record)
    await session.flush()
    if uploads_dir is not None:
        uploads_dir.mkdir(parents=True, exist_ok=True)
        path = uploads_dir / f"{record.id}.jpg"
        crop.image.save(path, format="JPEG", quality=90)
        record.image_path = str(path)
    return IdentifyResult(record.id, crop.found_circle, candidates)


async def confirm(session: AsyncSession, identification_id: uuid.UUID, type_id: uuid.UUID) -> bool:
    record = await session.get(Identification, identification_id)
    if record is None:
        return False
    record.confirmed_type_id = type_id
    await session.flush()
    return True


def _confidence(score: float) -> str:
    for threshold, label in CONFIDENCE:
        if score >= threshold:
            return label
    return "low"
