from decimal import Decimal

import pytest

from euro2core.rarity.scorer import METHOD_VERSION, MarketSignals, score, tier_for


def market(listings_per_million=None, median_sale=None, catalog_median_lpm=10.0):
    return MarketSignals(
        active_listings_per_million=listings_per_million,
        median_sale_price=Decimal(str(median_sale)) if median_sale is not None else None,
        catalog_median_listings_per_million=catalog_median_lpm,
    )


def test_huge_mintage_common_coin_scores_near_zero():
    r = score(mintage=30_000_000, market=market(10, 2.5))
    assert r.score < 15
    assert r.tier == "common"


def test_tiny_mintage_scores_near_top():
    r = score(mintage=10_000, market=market(0.5, 500))
    assert r.score > 85
    assert r.tier == "exceptional"


def test_score_is_monotonic_in_mintage():
    scores = [
        score(mintage=m, market=market(10, 5)).score
        for m in (10_000, 100_000, 1_000_000, 10_000_000)
    ]
    assert scores == sorted(scores, reverse=True)


def test_scarce_supply_raises_score_over_abundant_supply_at_equal_mintage():
    scarce = score(mintage=500_000, market=market(1.0, 20))
    abundant = score(mintage=500_000, market=market(100.0, 20))
    assert scarce.score > abundant.score


def test_premium_over_face_value_raises_score():
    cheap = score(mintage=500_000, market=market(10, 2.2))
    pricey = score(mintage=500_000, market=market(10, 60))
    assert pricey.score > cheap.score


def test_missing_market_data_falls_back_to_mintage_only_but_records_it():
    r = score(mintage=500_000, market=market(None, None))
    assert 0 <= r.score <= 100
    assert r.components["availability"] is None
    assert r.components["premium"] is None
    assert r.components["mintage"] is not None


def test_unknown_mintage_yields_no_score():
    assert score(mintage=None, market=market(10, 5)) is None


def test_components_and_method_version_are_stored_for_audit():
    r = score(mintage=500_000, market=market(10, 5))
    assert r.method_version == METHOD_VERSION
    assert set(r.components) >= {"mintage", "availability", "premium", "weights"}


@pytest.mark.parametrize(
    ("value", "tier"),
    [
        (0, "common"),
        (24.9, "common"),
        (25, "uncommon"),
        (45, "rare"),
        (65, "very_rare"),
        (85, "exceptional"),
        (100, "exceptional"),
    ],
)
def test_tiers(value, tier):
    assert tier_for(value) == tier
