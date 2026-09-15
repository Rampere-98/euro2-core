from decimal import Decimal

from euro2core.domain.enums import Finish
from euro2core.pricing.mintage_model import calibrate, model_band


def test_scarce_mintages_get_steep_bands_and_common_ones_stay_near_face_value():
    monaco_2007 = model_band(20_001)  # Grace Kelly
    assert monaco_2007.low == Decimal("300.00") and monaco_2007.high == Decimal("1500.00")
    monaco_2015 = model_band(10_000)
    assert monaco_2015.high == Decimal("3000.00")
    vatican_2004 = model_band(85_000)
    assert (vatican_2004.low, vatican_2004.high) == (Decimal("40.00"), Decimal("120.00"))
    germany = model_band(30_000_000)
    assert germany.low == Decimal("2.20") and germany.high == Decimal("3.50")
    assert germany.low < germany.median < germany.high


def test_finish_scales_the_band():
    loose = model_band(100_000)
    proof = model_band(100_000, Finish.PROOF)
    assert proof.low == loose.low * 2 and proof.high == loose.high * 2


def test_missing_mintage_has_no_model():
    assert model_band(None) is None and model_band(0) is None


def test_calibration_replaces_a_bucket_once_it_has_enough_real_sales():
    observed = [(150_000, Decimal("20"), Decimal("55"))] * 5 + [
        (30_000, Decimal("90"), Decimal("200"))
    ]
    cal = calibrate(observed)
    assert cal == {4: (Decimal("20"), Decimal("55"))}  # the 30k bucket had one sale: untouched
    band = model_band(200_000, calibration=cal)
    assert (band.low, band.high) == (Decimal("20.00"), Decimal("55.00"))
    assert model_band(30_000, calibration=cal).high == Decimal("300.00")
