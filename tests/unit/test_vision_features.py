import io
from pathlib import Path

from PIL import Image

from euro2core.vision.features import geometric_inliers

FIX = Path(__file__).parent.parent / "fixtures" / "images"


def _degraded(img: Image.Image, angle: float) -> Image.Image:
    shot = img.rotate(angle, expand=False).resize((200, 200))
    buf = io.BytesIO()
    shot.save(buf, format="JPEG", quality=55)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def test_same_design_rotated_and_degraded_has_many_geometric_inliers():
    original = Image.open(FIX / "de_2006_schleswig_holstein.jpg").convert("RGB")
    same = geometric_inliers(_degraded(original, 37), original)
    other = geometric_inliers(
        _degraded(original, 37), Image.open(FIX / "va_2004_founding.jpg").convert("RGB")
    )
    assert same >= 20
    assert other < same / 3


def test_featureless_image_yields_zero_not_an_error():
    blank = Image.new("RGB", (224, 224), (200, 200, 200))
    assert geometric_inliers(blank, blank) == 0
