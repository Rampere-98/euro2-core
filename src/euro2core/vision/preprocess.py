"""Turn an arbitrary user photo into a square, coin-centred 224x224 RGB image."""

import io
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

OUTPUT_SIZE = 224
MAX_ANALYSIS_SIDE = 800  # Hough on a downscaled copy keeps CPU time predictable


@dataclass(frozen=True)
class CoinCrop:
    image: Image.Image
    found_circle: bool
    center: tuple[int, int]
    radius: int


def prepare_coin_image(data: bytes) -> CoinCrop:
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("not a readable image") from exc
    circle = _find_coin(image)
    if circle is None:
        side = min(image.size)
        cx, cy, r = image.width // 2, image.height // 2, side // 2
        found = False
    else:
        cx, cy, r = circle
        found = True
    margin = int(r * 1.08)  # keep the rim, drop most of the background
    box = (cx - margin, cy - margin, cx + margin, cy + margin)
    crop = image.crop(box).resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.LANCZOS)
    return CoinCrop(image=crop, found_circle=found, center=(cx, cy), radius=r)


def _find_coin(image: Image.Image) -> tuple[int, int, int] | None:
    scale = min(1.0, MAX_ANALYSIS_SIDE / max(image.size))
    small = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
    gray = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2GRAY)
    gray = cv2.medianBlur(gray, 5)
    min_r = int(min(gray.shape) * 0.12)
    max_r = int(min(gray.shape) * 0.5)
    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=min_r,
        param1=120,
        param2=40,
        minRadius=min_r,
        maxRadius=max_r,
    )
    if circles is None:
        return None
    # the largest confident circle is the coin; a coin photo rarely has bigger round things
    x, y, r = max(circles[0], key=lambda c: c[2])
    return int(x / scale), int(y / scale), int(r / scale)
