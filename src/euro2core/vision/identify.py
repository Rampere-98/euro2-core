"""Identify a coin from a photo: CLIP retrieval over rotated catalog views, then SIFT+RANSAC
verification so the answer is the exact design, not just a similar-looking one."""

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.models import CoinImage, Identification, ImageEmbedding
from euro2core.vision.embedder import ClipEmbedder
from euro2core.vision.features import descriptors, inliers_from_descriptors
from euro2core.vision.preprocess import inner_core, prepare_coin_image

NEIGHBOURS = 96
RERANK_TYPES = 12
MIN_SIMILARITY = 0.55
HIGH_INLIERS, MEDIUM_INLIERS, MIN_INLIERS = 30, 14, 8
MARGIN_FOR_HIGH = 1.5


@dataclass(frozen=True)
class Candidate:
    type_id: uuid.UUID
    image_id: uuid.UUID
    score: float  # 0-1: geometric agreement when available, else embedding similarity
    confidence: str
    inliers: int
    similarity: float


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
    vector = embedder.embed_images([inner_core(crop.image)])[0].tolist()
    distance = ImageEmbedding.embedding.cosine_distance(vector)
    rows = (
        await session.execute(
            select(CoinImage.type_id, CoinImage.id, CoinImage.local_path, distance)
            .join(CoinImage, CoinImage.id == ImageEmbedding.image_id)
            .where(CoinImage.type_id.is_not(None))
            .order_by(distance)
            .limit(NEIGHBOURS)
        )
    ).all()
    # best embedding similarity per type, keeping the image that produced it
    shortlist: dict[uuid.UUID, tuple[uuid.UUID, str, float]] = {}
    for type_id, image_id, local_path, dist in rows:
        similarity = 1.0 - float(dist)
        if similarity < MIN_SIMILARITY or type_id in shortlist:
            continue
        shortlist[type_id] = (image_id, local_path, similarity)
        if len(shortlist) >= RERANK_TYPES:
            break

    kq, dq = descriptors(crop.image)
    verified: list[tuple[int, float, uuid.UUID, uuid.UUID]] = []
    for type_id, (image_id, local_path, similarity) in shortlist.items():
        try:
            kc, dc = descriptors(Image.open(local_path).convert("RGB"))
            inliers = inliers_from_descriptors(kq, dq, kc, dc)
        except OSError:
            inliers = 0
        verified.append((inliers, similarity, type_id, image_id))
    verified.sort(key=lambda v: (-v[0], -v[1]))
    candidates = _rank(verified)[:top_k]

    record = Identification(
        user_id=user_id,
        found_circle=crop.found_circle,
        top_type_id=candidates[0].type_id if candidates else None,
        top_score=candidates[0].score if candidates else None,
        candidates=[
            {"type_id": str(c.type_id), "score": c.score, "inliers": c.inliers} for c in candidates
        ],
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


def _rank(verified: list[tuple[int, float, uuid.UUID, uuid.UUID]]) -> list[Candidate]:
    if not verified:
        return []
    best_inliers = verified[0][0]
    runner_up = verified[1][0] if len(verified) > 1 else 0
    out: list[Candidate] = []
    for i, (inliers, similarity, type_id, image_id) in enumerate(verified):
        if inliers >= MIN_INLIERS:
            score = round(min(1.0, inliers / 60), 4)
            if (
                i == 0
                and inliers >= HIGH_INLIERS
                and inliers >= MARGIN_FOR_HIGH * max(runner_up, 1)
            ):
                confidence = "high"
            elif inliers >= MEDIUM_INLIERS:
                confidence = "medium"
            else:
                confidence = "low"
        else:
            # no geometric proof: fall back to the embedding, and say so with a low confidence
            score, confidence = round(similarity, 4), "low"
        out.append(Candidate(type_id, image_id, score, confidence, inliers, round(similarity, 4)))
    if best_inliers < MIN_INLIERS:
        out.sort(key=lambda c: -c.similarity)
    return out


async def confirm(session: AsyncSession, identification_id: uuid.UUID, type_id: uuid.UUID) -> bool:
    record = await session.get(Identification, identification_id)
    if record is None:
        return False
    record.confirmed_type_id = type_id
    await session.flush()
    return True
