from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from euro2core.vision.embedder import EMBEDDING_DIM, ClipEmbedder

FIX = Path(__file__).parent.parent / "fixtures" / "images"

pytestmark = pytest.mark.model  # downloads ~600 MB of weights on first run


@pytest.fixture(scope="module")
def embedder() -> ClipEmbedder:
    return ClipEmbedder()


def test_image_embeddings_are_unit_vectors_of_the_catalog_dimension(embedder):
    images = [
        Image.open(FIX / name)
        for name in ("de_2006_schleswig_holstein.jpg", "va_2004_founding.jpg")
    ]
    vectors = embedder.embed_images(images)
    assert vectors.shape == (2, EMBEDDING_DIM)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-3)


def test_same_coin_photographed_differently_is_closer_than_another_coin(embedder):
    original = Image.open(FIX / "de_2006_schleswig_holstein.jpg")
    other = Image.open(FIX / "va_2004_founding.jpg")
    # a phone shot: smaller, slightly rotated, warmer
    variant = original.rotate(12, expand=False).resize((160, 160))
    variant = Image.merge(
        "RGB", (variant.split()[0].point(lambda v: min(255, v + 25)), *variant.split()[1:])
    )
    vecs = embedder.embed_images([original, variant, other])
    same = float(vecs[0] @ vecs[1])
    different = float(vecs[0] @ vecs[2])
    assert same > different
    assert same > 0.8


def test_text_embeddings_share_the_space(embedder):
    text = embedder.embed_texts(["a photo of a 2 euro coin"])
    assert text.shape == (1, EMBEDDING_DIM)
