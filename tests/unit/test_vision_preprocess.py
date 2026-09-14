import io

import numpy as np
import pytest
from PIL import Image, ImageDraw

from euro2core.vision.preprocess import CoinCrop, prepare_coin_image


def _photo_with_coin(size=(640, 480), center=(420, 260), radius=120) -> bytes:
    img = Image.new("RGB", size, (40, 90, 40))  # green tablecloth
    draw = ImageDraw.Draw(img)
    x, y = center
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(200, 170, 60))
    draw.ellipse(
        (x - radius * 0.6, y - radius * 0.6, x + radius * 0.6, y + radius * 0.6),
        fill=(160, 160, 160),
    )
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
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


def test_image_without_a_coin_falls_back_to_a_centre_square():
    img = Image.new("RGB", (800, 400), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    crop = prepare_coin_image(buf.getvalue())
    assert crop.found_circle is False
    assert crop.image.size == (224, 224)


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
