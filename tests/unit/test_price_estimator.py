from datetime import UTC, datetime, timedelta
from decimal import Decimal

from euro2core.domain.enums import Grade, ObservationKind
from euro2core.pricing.estimator import METHOD_VERSION, Observation, estimate

NOW = datetime(2026, 6, 1, tzinfo=UTC)


def obs(
    price,
    *,
    kind=ObservationKind.SOLD,
    grade=Grade.UNC,
    days_ago=10,
    confidence=0.95,
    marketplace="EBAY_ES",
    id=None,
) -> Observation:
    return Observation(
        id=id or f"{marketplace}-{price}-{days_ago}",
        price=Decimal(str(price)),
        kind=kind,
        grade=grade,
        marketplace=marketplace,
        observed_at=NOW - timedelta(days=days_ago),
        match_confidence=confidence,
    )


def sales(prices, **kw):
    return [obs(p, id=f"s{i}", **kw) for i, p in enumerate(prices)]


def test_median_of_realized_sales_only():
    data = sales([28, 30, 32, 31, 29]) + [
        obs(80, kind=ObservationKind.ASKING, id="ask"),
        obs(5, confidence=0.5, id="lowconf"),
    ]
    est = estimate(data, grade=Grade.UNC, region="global", now=NOW)
    assert est.median == Decimal("30.00")
    assert est.n_obs == 5
    assert est.basis == "sold"
    assert est.window_days == 90
    assert est.method_version == METHOD_VERSION


def test_window_widens_to_a_year_when_recent_sales_are_scarce():
    data = sales([30, 31], days_ago=10) + sales([29, 30, 32], days_ago=200)
    est = estimate(data, grade=Grade.UNC, region="global", now=NOW)
    assert est.window_days == 365
    assert est.n_obs == 5


def test_fewer_than_three_sales_is_insufficient_not_a_guess():
    est = estimate(sales([30, 31]), grade=Grade.UNC, region="global", now=NOW)
    assert est.median is None
    assert est.basis == "insufficient"
    assert est.n_obs == 2
    assert est.confidence == "low"


def test_extreme_price_is_flagged_as_outlier_and_excluded():
    data = sales([28, 29, 30, 30, 31, 32, 29, 30, 5000])
    est = estimate(data, grade=Grade.UNC, region="global", now=NOW)
    assert est.outlier_ids == ["s8"]
    assert est.n_obs == 8
    assert est.median == Decimal("30.00")


def test_falls_back_to_asking_prices_when_no_sales_exist_and_says_so():
    data = [obs(p, kind=ObservationKind.ASKING, id=f"a{p}") for p in (40, 45, 50)]
    est = estimate(data, grade=Grade.UNC, region="global", now=NOW)
    assert est.basis == "asking_only"
    assert est.median == Decimal("45.00")
    assert est.confidence == "low"


def test_regional_estimate_needs_at_least_three_local_sales():
    data = sales([30, 31, 32, 33], marketplace="EBAY_DE") + sales([50, 55], marketplace="EBAY_ES")
    assert estimate(data, grade=Grade.UNC, region="EBAY_ES", now=NOW).median is None
    assert estimate(data, grade=Grade.UNC, region="EBAY_DE", now=NOW).median == Decimal("31.50")


def test_confidence_reflects_sample_size():
    assert (
        estimate(sales(range(10, 20)), grade=Grade.UNC, region="global", now=NOW).confidence
        == "high"
    )
    assert (
        estimate(sales(range(10, 16)), grade=Grade.UNC, region="global", now=NOW).confidence
        == "medium"
    )
    assert (
        estimate(sales(range(10, 14)), grade=Grade.UNC, region="global", now=NOW).confidence
        == "low"
    )


def test_grades_are_not_mixed():
    data = sales([2, 2, 2, 2], grade=Grade.CIRCULATED) + sales([30, 31, 32], grade=Grade.BU)
    assert estimate(data, grade=Grade.BU, region="global", now=NOW).median == Decimal("31.00")
    assert estimate(data, grade=Grade.CIRCULATED, region="global", now=NOW).median == Decimal(
        "2.00"
    )
