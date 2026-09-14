"""CLIP embeddings for coin photos and text, shared by identification and semantic search."""

import logging
import threading
from collections.abc import Sequence

import numpy as np
import torch
from PIL import Image

MODEL_NAME = "ViT-B-32"
PRETRAINED = "laion2b_s34b_b79k"
EMBEDDING_DIM = 512  # must match coin_image.embedding vector(512)

log = logging.getLogger(__name__)


class ClipEmbedder:
    """Lazy, thread-safe wrapper: the model loads on first use and is shared afterwards."""

    def __init__(self, model_name: str = MODEL_NAME, pretrained: str = PRETRAINED) -> None:
        self.model_name = model_name
        self.pretrained = pretrained
        self._lock = threading.Lock()
        self._model = None
        self._preprocess = None
        self._tokenizer = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            import open_clip

            log.info("loading CLIP %s/%s on CPU", self.model_name, self.pretrained)
            model, _, preprocess = open_clip.create_model_and_transforms(
                self.model_name, pretrained=self.pretrained, device="cpu"
            )
            model.eval()
            self._tokenizer = open_clip.get_tokenizer(self.model_name)
            self._preprocess = preprocess
            self._model = model

    def embed_images(self, images: Sequence[Image.Image], batch_size: int = 16) -> np.ndarray:
        self._ensure_loaded()
        out: list[np.ndarray] = []
        with torch.inference_mode():
            for start in range(0, len(images), batch_size):
                batch = torch.stack(
                    [
                        self._preprocess(img.convert("RGB"))
                        for img in images[start : start + batch_size]
                    ]
                )
                features = self._model.encode_image(batch)
                features = features / features.norm(dim=-1, keepdim=True)
                out.append(features.cpu().numpy().astype(np.float32))
        return np.concatenate(out) if out else np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        self._ensure_loaded()
        with torch.inference_mode():
            tokens = self._tokenizer(list(texts))
            features = self._model.encode_text(tokens)
            features = features / features.norm(dim=-1, keepdim=True)
        return features.cpu().numpy().astype(np.float32)


_shared: ClipEmbedder | None = None


def get_embedder() -> ClipEmbedder:
    global _shared
    if _shared is None:
        _shared = ClipEmbedder()
    return _shared
