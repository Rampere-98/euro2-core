"""Exact design verification with local features: rotation-invariant, unlike a global embedding."""

import cv2
import numpy as np
from PIL import Image

from euro2core.vision.preprocess import inner_core

WORK_SIDE = 320
LOWE_RATIO = 0.75
RANSAC_REPROJ = 4.0
MIN_MATCHES = 8

_sift = cv2.SIFT_create(nfeatures=800)
_matcher = cv2.BFMatcher(cv2.NORM_L2)


def _gray(image: Image.Image) -> np.ndarray:
    img = inner_core(image).convert("L")
    scale = WORK_SIDE / max(img.size)
    if scale < 1:
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
    return np.asarray(img)


def descriptors(image: Image.Image) -> tuple[list, np.ndarray | None]:
    return _sift.detectAndCompute(_gray(image), None)


def geometric_inliers(query: Image.Image, candidate: Image.Image) -> int:
    """Number of SIFT matches consistent with one homography between the two images."""
    kq, dq = descriptors(query)
    kc, dc = descriptors(candidate)
    return inliers_from_descriptors(kq, dq, kc, dc)


def inliers_from_descriptors(kq, dq, kc, dc) -> int:
    if dq is None or dc is None or len(kq) < MIN_MATCHES or len(kc) < MIN_MATCHES:
        return 0
    pairs = _matcher.knnMatch(dq, dc, k=2)
    good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < LOWE_RATIO * n.distance]
    if len(good) < MIN_MATCHES:
        return 0
    src = np.float32([kq[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kc[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    _, mask = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_REPROJ)
    return int(mask.sum()) if mask is not None else 0
