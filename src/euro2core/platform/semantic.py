"""Multilingual semantic search over coin types (title + descriptions)."""

import hashlib
import logging
import threading
import uuid
from collections.abc import Sequence

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.models import CoinType, TextTranslation, TypeEmbedding

MODEL_NAME = "intfloat/multilingual-e5-small"
DIM = 384
log = logging.getLogger(__name__)


class TextEmbedder:
    """multilingual-e5-small through transformers + torch (mean pooling, L2 normalised)."""

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        self.model_name = model_name
        self._model = None
        self._tokenizer = None
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from transformers import AutoModel, AutoTokenizer

                    log.info("loading text embedder %s", self.model_name)
                    self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                    model = AutoModel.from_pretrained(self.model_name)
                    model.eval()
                    self._model = model

    def _encode(self, texts: Sequence[str], batch_size: int = 32) -> np.ndarray:
        import torch

        self._ensure()
        out: list[np.ndarray] = []
        with torch.inference_mode():
            for start in range(0, len(texts), batch_size):
                batch = self._tokenizer(
                    list(texts[start : start + batch_size]),
                    max_length=512,
                    padding=True,
                    truncation=True,
                    return_tensors="pt",
                )
                hidden = self._model(**batch).last_hidden_state
                mask = batch["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
                out.append(pooled.cpu().numpy().astype(np.float32))
        return np.concatenate(out) if out else np.zeros((0, DIM), dtype=np.float32)

    def embed_passages(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode([f"passage: {t}" for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode([f"query: {text}"])[0]


_shared: TextEmbedder | None = None


def get_text_embedder() -> TextEmbedder:
    global _shared
    if _shared is None:
        _shared = TextEmbedder()
    return _shared


async def _documents(session: AsyncSession) -> dict[uuid.UUID, str]:
    rows = (
        await session.execute(
            select(
                CoinType.id,
                CoinType.country_code,
                CoinType.year,
                TextTranslation.field,
                TextTranslation.lang,
                TextTranslation.text,
            ).join(
                TextTranslation,
                (TextTranslation.entity == "coin_type")
                & (TextTranslation.entity_id == CoinType.id),
            )
        )
    ).all()
    parts: dict[uuid.UUID, dict[str, str]] = {}
    meta: dict[uuid.UUID, str] = {}
    for type_id, cc, year, field, lang, text in rows:
        parts.setdefault(type_id, {})[f"{field}:{lang}"] = text
        meta[type_id] = f"{cc} {year}"
    docs: dict[uuid.UUID, str] = {}
    for type_id, fields in parts.items():
        pieces = [meta[type_id]]
        for key in ("title:en", "title:es", "description:es", "description:en"):
            if key in fields:
                pieces.append(fields[key][:600])
        docs[type_id] = " | ".join(pieces)
    return docs


async def embed_types(session: AsyncSession, embedder: TextEmbedder) -> dict[str, int]:
    docs = await _documents(session)
    existing = {e.type_id: e for e in (await session.scalars(select(TypeEmbedding))).all()}
    todo: list[tuple[uuid.UUID, str, str]] = []
    for type_id, text in docs.items():
        digest = hashlib.sha256(text.encode()).hexdigest()
        current = existing.get(type_id)
        if current is None or current.text_hash != digest:
            todo.append((type_id, text, digest))
    stats = {"embedded": 0, "unchanged": len(docs) - len(todo)}
    for start in range(0, len(todo), 64):
        chunk = todo[start : start + 64]
        vectors = embedder.embed_passages([t for _, t, _ in chunk])
        for (type_id, _, digest), vector in zip(chunk, vectors, strict=True):
            row = existing.get(type_id)
            if row is None:
                session.add(
                    TypeEmbedding(type_id=type_id, text_hash=digest, embedding=vector.tolist())
                )
            else:
                row.text_hash = digest
                row.embedding = vector.tolist()
        stats["embedded"] += len(chunk)
        await session.flush()
    return stats


async def semantic_search(
    session: AsyncSession, embedder: TextEmbedder, query: str, limit: int = 20
) -> list[tuple[CoinType, float]]:
    vector = embedder.embed_query(query).tolist()
    distance = TypeEmbedding.embedding.cosine_distance(vector)
    rows = (
        await session.execute(
            select(CoinType, distance)
            .join(TypeEmbedding, TypeEmbedding.type_id == CoinType.id)
            .order_by(distance)
            .limit(limit)
        )
    ).all()
    return [(ct, round(1.0 - float(d), 4)) for ct, d in rows]
