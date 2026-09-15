import io

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from euro2core.vision.preprocess import (
    CoinCrop,
    fallback_crops,
    find_coin,
    prepare_coin_image,
)


def _coin_image(size=(640, 480), center=(420, 260), radius=120, blur=0) -> Image.Image:
    img = Image.new("RGB", size, (40, 90, 40))  # green tablecloth
    draw = ImageDraw.Draw(img)
    x, y = center
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(200, 170, 60))
    draw.ellipse(
        (x - radius * 0.6, y - radius * 0.6, x + radius * 0.6, y + radius * 0.6),
        fill=(160, 160, 160),
    )
    return img.filter(ImageFilter.GaussianBlur(blur)) if blur else img


def _photo_with_coin(**kw) -> bytes:
    buf = io.BytesIO()
    _coin_image(**kw).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_coin_is_located_and_cropped_to_a_square_around_it():
    crop = prepare_coin_image(_photo_with_coin())
    assert isinstance(crop, CoinCrop)
    assert crop.found_circle is True
    assert crop.image.size == (224, 224)
    # the crop is centred on the coin: the middle pixel is the silver core, the corners are cloth
    px = np.asarray(crop.image)
    assert px[112, 112].tolist() == pytest.approx([160, 160, 160], abs=25)
    assert px[4, 4][1] > px[4, 4][0]  # green background at the corner


def test_a_soft_edged_coin_is_still_located():
    # phone photos are rarely razor sharp: the edge detector must cope with a blurred rim
    crop = prepare_coin_image(_photo_with_coin(blur=6))
    assert crop.found_circle is True
    assert crop.center == pytest.approx((420, 260), abs=12)
    assert crop.radius == pytest.approx(120, abs=15)


def test_contour_fallback_locates_a_coin_that_hough_misses():
    # a heavily blurred rim defeats the Hough transform; the contour pass still finds the blob
    img = _coin_image(blur=6)
    assert find_coin(img, hough=False) == pytest.approx((420, 260, 120), abs=15)


def test_no_circle_is_invented_on_a_blank_image():
    assert find_coin(Image.new("RGB", (800, 400), (255, 255, 255))) is None


def test_image_without_a_coin_falls_back_to_a_centre_square():
    img = Image.new("RGB", (800, 400), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    crop = prepare_coin_image(buf.getvalue())
    assert crop.found_circle is False
    assert crop.image.size == (224, 224)


def test_guided_crop_trusts_the_client_and_uses_the_whole_frame():
    # the app already framed the coin (manual crop): no detection, no second guessing
    img = Image.new("RGB", (500, 500), (10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    crop = prepare_coin_image(buf.getvalue(), guided=True)
    assert crop.found_circle is True
    assert crop.image.size == (224, 224)
    assert crop.center == (250, 250)
    assert crop.radius == pytest.approx(250 / 1.08, abs=2)


def test_fallback_crops_zoom_into_the_centre_at_several_scales():
    img = _coin_image(size=(900, 600), center=(450, 300), radius=110)
    crops = fallback_crops(img)
    assert len(crops) >= 3
    assert all(c.image.size == (224, 224) and c.found_circle is False for c in crops)
    assert all(c.center == (450, 300) for c in crops)
    radii = [c.radius for c in crops]
    assert radii == sorted(radii, reverse=True)  # from the full short side inwards
    assert radii[0] == 300
    # the tightest crop is the one where the coin fills the frame
    px = np.asarray(crops[-1].image)
    assert px[112, 112].tolist() == pytest.approx([160, 160, 160], abs=25)


def test_garbage_bytes_raise_a_clear_error():
    with pytest.raises(ValueError, match="not a readable image"):
        prepare_coin_image(b"definitely not an image")


def test_exif_orientation_is_honoured_and_output_is_rgb():
    img = Image.new("L", (300, 300), 128)  # greyscale input
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    crop = prepare_coin_image(buf.getvalue())
    assert crop.image.mode == "RGB"


def test_inner_core_masks_the_common_star_ring():
    from euro2core.vision.preprocess import inner_core

    img = Image.new("RGB", (224, 224), (255, 0, 0))  # all red, ring included
    core = inner_core(img)
    px = np.asarray(core)
    assert px[112, 112].tolist() == [255, 0, 0]  # centre untouched
    assert px[112, 6].tolist() != [255, 0, 0]  # ring replaced by neutral grey
    assert px[6, 6].tolist() != [255, 0, 0]
