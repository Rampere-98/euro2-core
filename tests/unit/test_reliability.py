from decimal import Decimal

import pytest

from euro2core.pricing.reliability import assess


def _ok(**kw):
    base = dict(
        title="2 Euro Deutschland 2006 A Schleswig-Holstein Holstentor",
        price=Decimal("3.50"),
        match_confidence=0.96,
        issue_year=2006,
        type_is_coloured=False,
        realized=False,
        fair_p75=None,
    )
    base.update(kw)
    return assess(**base)


def test_clean_listing_is_fully_reliable():
    r = _ok()
    assert r.score == 1.0
    assert r.reasons == []


def test_lots_are_unusable_as_a_coin_price():
    r = _ok(title="Lote 5 monedas 2 euros Alemania 2006 Schleswig-Holstein")
    assert r.score == 0
    assert "lot" in r.reasons


@pytest.mark.parametrize(
    "title",
    [
        "2 euro 2006 Alemania Holstentor REPLICA",
        "2 Euro Schleswig-Holstein 2006 copia",
        "2 euro Fantasy pattern Holstentor 2006 essai",
    ],
)
def test_replicas_and_fantasies_are_unusable(title):
    r = _ok(title=title)
    assert r.score == 0
    assert "replica" in r.reasons


def test_altered_coins_are_unusable_unless_the_design_is_coloured():
    r = _ok(title="2 Euro 2006 Schleswig-Holstein vergoldet gold plated")
    assert r.score == 0 and "altered" in r.reasons
    coloured = _ok(
        title="2 Euro France 2024 Olympic Games coloured farbig",
        type_is_coloured=True,
        issue_year=2024,
    )
    assert coloured.score == 1.0


def test_weak_matches_are_unusable_and_medium_ones_discounted():
    assert _ok(match_confidence=0.8).score == 0
    r = _ok(match_confidence=0.9)
    assert r.score == pytest.approx(0.7)
    assert "match_medium" in r.reasons


def test_realized_price_below_face_value_is_incomplete():
    assert _ok(price=Decimal("1.50"), realized=True).score == 0
    assert _ok(price=Decimal("1.50"), realized=False).score == 1.0  # an ask can be a teaser


def test_absurd_price_versus_the_fair_band_is_discounted():
    r = _ok(price=Decimal("900"), fair_p75=Decimal("4"))
    assert r.score == pytest.approx(0.3)
    assert "price_absurd" in r.reasons


def test_year_mismatch_halves_the_score():
    r = _ok(title="2 Euro Deutschland 2007 A Schleswig-Holstein")
    assert r.score == pytest.approx(0.5)
    assert "year_mismatch" in r.reasons


def test_certification_adds_confidence_but_never_exceeds_one():
    r = _ok(title="2 Euro Deutschland 2006 A Schleswig-Holstein PCGS MS67", match_confidence=0.9)
    assert r.score == pytest.approx(0.8)
    assert _ok(title="2 Euro Deutschland 2006 A Schleswig-Holstein NGC MS66").score == 1.0
