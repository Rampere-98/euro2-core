"""Turn an arbitrary user photo into a square, coin-centred 224x224 RGB image.

The coin is located automatically so users never have to crop by hand: first with the Hough
circle transform (crisp rims), then, if that finds nothing, by the largest round silhouette that
stands out from the background (soft or low-contrast rims). When neither works, the caller can
try a few centred crops at decreasing scales (`fallback_crops`) instead of matching the whole
frame, which is what a phone photo looks like when the coin is roughly centred."""

import io
import math
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

OUTPUT_SIZE = 224
DETAIL_SIZE = 448  # the same crop at higher resolution, for keypoint matching
MAX_ANALYSIS_SIDE = 800  # detection on a downscaled copy keeps CPU time predictable
# The outer ring (12 stars) is identical on every 2 euro coin; only the core carries the design.
CORE_RATIO = 0.74
NEUTRAL = (128, 128, 128)
RIM_MARGIN = 1.08  # keep the rim, drop most of the background
MIN_RADIUS_FRACTION, MAX_RADIUS_FRACTION = 0.12, 0.5
HOUGH_THRESHOLDS = (40, 32, 26)  # accumulator votes: strict first, then more forgiving
MIN_BLOB_FILL = 0.72  # a coin silhouette fills at least this much of its enclosing circle
FALLBACK_SCALES = (1.0, 0.8, 0.64, 0.5, 0.4)  # radius as a fraction of half the short side


@dataclass(frozen=True)
class CoinCrop:
    image: Image.Image  # 224x224, what the embedding model sees
    found_circle: bool
    center: tuple[int, int]
    radius: int
    detail: Image.Image | None = None  # 448x448, what the keypoint matcher sees


def decode_image(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        return ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("not a readable image") from exc


def prepare_coin_image(data: bytes, *, guided: bool = False) -> CoinCrop:
    """Locate the coin and crop it; `guided` means the client already framed it (manual crop)."""
    image = decode_image(data)
    cx, cy, side = image.width // 2, image.height // 2, min(image.size)
    if guided:
        return crop_around(image, cx, cy, int(side / 2 / RIM_MARGIN), True)
    circle = find_coin(image)
    if circle is None:
        return crop_around(image, cx, cy, side // 2, False)
    return crop_around(image, *circle, True)


def crop_around(image: Image.Image, cx: int, cy: int, r: int, found: bool) -> CoinCrop:
    margin = int(r * RIM_MARGIN)
    box = (cx - margin, cy - margin, cx + margin, cy + margin)
    region = image.crop(box)
    return CoinCrop(
        image=region.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.LANCZOS),
        found_circle=found,
        center=(cx, cy),
        radius=r,
        detail=region.resize((DETAIL_SIZE, DETAIL_SIZE), Image.LANCZOS),
    )


def fallback_crops(image: Image.Image) -> list[CoinCrop]:
    """Centred crops from the whole short side down to a tight one, for when no rim was found."""
    cx, cy, half = image.width // 2, image.height // 2, min(image.size) // 2
    return [crop_around(image, cx, cy, int(half * s), False) for s in FALLBACK_SCALES]


def find_coin(image: Image.Image, *, hough: bool = True) -> tuple[int, int, int] | None:
    """(cx, cy, r) of the coin in full-resolution pixels, or None when nothing round stands out."""
    scale = min(1.0, MAX_ANALYSIS_SIDE / max(image.size))
    small = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
    rgb = np.asarray(small)
    gray = cv2.medianBlur(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), 5)
    min_r = int(min(gray.shape) * MIN_RADIUS_FRACTION)
    max_r = int(min(gray.shape) * MAX_RADIUS_FRACTION)
    circle = _hough_circle(gray, min_r, max_r) if hough else None
    if circle is None:
        circle = _silhouette_circle(rgb, gray, min_r, max_r)
    if circle is None:
        return None
    x, y, r = circle
    return int(x / scale), int(y / scale), int(r / scale)


def _hough_circle(gray: np.ndarray, min_r: int, max_r: int) -> tuple[float, float, float] | None:
    for votes in HOUGH_THRESHOLDS:
        circles = cv2.HoughCircles(
            gray,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=min_r,
            param1=120,
            param2=votes,
            minRadius=min_r,
            maxRadius=max_r,
        )
        if circles is not None:
            # the largest confident circle is the coin; coin photos rarely have bigger round things
            x, y, r = max(circles[0], key=lambda c: c[2])
            return float(x), float(y), float(r)
    return None


def _silhouette_circle(
    rgb: np.ndarray, gray: np.ndarray, min_r: int, max_r: int
) -> tuple[float, float, float] | None:
    """Largest round blob that separates from the background in brightness, colour or edges."""
    h, w = gray.shape
    sat = cv2.medianBlur(cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[:, :, 1], 5)
    masks: list[np.ndarray] = []
    for channel in (gray, sat):
        _, mask = cv2.threshold(channel, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        masks += [mask, cv2.bitwise_not(mask)]
    edges = cv2.Canny(gray, 30, 90)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    masks.append(cv2.morphologyEx(cv2.dilate(edges, kernel), cv2.MORPH_CLOSE, kernel))

    best: tuple[float, tuple[float, float, float]] | None = None
    for mask in masks:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            (x, y), r = cv2.minEnclosingCircle(contour)
            if not (min_r <= r <= max_r) or not (0 <= x < w and 0 <= y < h):
                continue
            fill = cv2.contourArea(contour) / (math.pi * r * r)
            if fill < MIN_BLOB_FILL:
                continue
            score = fill * r
            if best is None or score > best[0]:
                best = (score, (x, y, r))
    return best[1] if best else None


def inner_core(image: Image.Image, ratio: float = CORE_RATIO) -> Image.Image:
    """Grey out everything outside the coin's inner core so shared ring features cannot match."""
    w, h = image.size
    cx, cy, r = w / 2, h / 2, min(w, h) / 2 * ratio
    yy, xx = np.ogrid[:h, :w]
    inside = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    out = np.asarray(image.convert("RGB")).copy()
    out[~inside] = NEUTRAL
    return Image.fromarray(out)
