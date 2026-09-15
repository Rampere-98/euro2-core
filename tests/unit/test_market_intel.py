from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from euro2core.domain.enums import Grade, ObservationKind
from euro2core.pricing.market_intel import (
    Listing,
    buy_advice,
    deal_discount,
    fair_band,
    monthly_history,
    sell_advice,
    snapshot,
)

NOW = datetime(2026, 9, 15, tzinfo=UTC)


def obs(price, days_ago=10, kind=ObservationKind.SOLD, market="EBAY_DE", title=None, conf=0.96):
    return Listing(
        listing_id=f"{kind.value}-{price}-{days_ago}",
        kind=kind,
        price=Decimal(str(price)),
        observed_at=NOW - timedelta(days=days_ago),
        marketplace=market,
        url=f"https://ebay.example/{price}",
        title=title or "2 Euro Deutschland 2006 A Schleswig-Holstein",
        match_confidence=conf,
        grade=Grade.UNC,
    )


SOLD = [
    obs(p, d)
    for p, d in ((3.0, 5), (3.5, 12), (4.0, 20), (3.8, 40), (3.2, 70), (6.0, 200), (5.5, 300))
]


def test_snapshot_uses_reliable_realized_sales_only_and_reports_the_range():
    listings = SOLD + [
        obs(0.5, 3),  # below face value: incomplete
        obs(40, 8, title="Lote 10 monedas 2 euro Alemania 2006"),  # a lot
        obs(9.9, 1, kind=ObservationKind.ASKING),
        obs(3.9, 2, kind=ObservationKind.ASKING, market="EBAY_ES"),
        obs(2.7, 4, kind=ObservationKind.ASKING, market="EBAY_ES"),
    ]
    s = snapshot(listings, issue_year=2006, now=NOW)
    assert s.realized.n == 5  # the 90-day window has enough sales
    assert (s.realized.min, s.realized.max) == (Decimal("3.00"), Decimal("4.00"))
    assert s.realized.window_days == 90
    assert s.asking.n == 3
    assert (s.asking.min, s.asking.max) == (Decimal("2.70"), Decimal("9.90"))
    assert s.band.basis == "sold"
    assert s.band.low <= s.realized.median <= s.band.high
    assert [x.listing_id for x in s.ignored] == ["sold-0.5-3", "sold-40-8"]


def test_snapshot_widens_to_a_year_when_recent_sales_are_scarce():
    listings = [obs(3.0, 5), obs(6.0, 200), obs(5.5, 300), obs(5.0, 320)]
    s = snapshot(listings, issue_year=2006, now=NOW)
    assert s.realized.window_days == 365
    assert s.realized.n == 4


def test_trend_compares_recent_median_with_the_previous_window():
    s = snapshot(SOLD, issue_year=2006, now=NOW)
    # recent (≤90 d) median 3.5 vs previous window median 5.75 → down ~39 %
    assert s.trend_pct == pytest.approx(-39.1, abs=0.5)


def test_liquidity_is_sales_per_month_and_days_to_sell():
    s = snapshot(SOLD, issue_year=2006, now=NOW)
    assert s.sales_per_month == pytest.approx(5 / 3, abs=0.01)
    assert s.expected_days_to_sell == 18


def test_best_marketplace_needs_three_sales():
    listings = SOLD + [obs(8.0, 3, market="EBAY_ES"), obs(8.5, 6, market="EBAY_ES")]
    s = snapshot(listings, issue_year=2006, now=NOW)
    assert s.best_marketplace == "EBAY_DE"  # ES has a higher median but only two sales


def test_fair_band_falls_back_to_catalog_then_face_value():
    assert fair_band(realized=None, catalog=Decimal("5")) == (
        Decimal("4.00"),
        Decimal("6.00"),
        "catalog",
    )
    assert fair_band(realized=None, catalog=None) == (
        Decimal("2.00"),
        Decimal("2.00"),
        "face_value",
    )


def test_buy_advice_verdicts():
    s = snapshot(SOLD + [obs(2.8, 1, kind=ObservationKind.ASKING)], issue_year=2006, now=NOW)
    a = buy_advice(s)
    assert a.verdict == "buy_now"
    assert a.cheapest.price == Decimal("2.80")
    assert a.saving_pct > 0
    s = snapshot(SOLD + [obs(3.6, 1, kind=ObservationKind.ASKING)], issue_year=2006, now=NOW)
    assert buy_advice(s).verdict == "fair"
    s = snapshot(SOLD + [obs(9.0, 1, kind=ObservationKind.ASKING)], issue_year=2006, now=NOW)
    assert buy_advice(s).verdict == "overpriced"
    assert buy_advice(snapshot(SOLD, issue_year=2006, now=NOW)).verdict == "no_offers"


def test_buy_advice_says_wait_when_the_market_is_falling_even_if_the_ask_is_fair():
    s = snapshot(SOLD + [obs(3.6, 1, kind=ObservationKind.ASKING)], issue_year=2006, now=NOW)
    assert s.trend_pct < -10
    assert buy_advice(s, consider_trend=True).verdict == "wait"


def test_sell_advice_prices_by_grade_and_estimates_net_after_fees():
    s = snapshot(SOLD, issue_year=2006, now=NOW)
    a = sell_advice(s, grade=Grade.CIRCULATED)
    assert a.floor < a.start
    assert a.start == (s.band.high * Decimal("0.7")).quantize(Decimal("0.01"))
    assert a.expected_days == s.expected_days_to_sell
    assert a.best_marketplace == "EBAY_DE"
    assert a.net_ebay < a.start and a.net_euro2 == a.start
    assert a.hold is False
    rising = [
        obs(6.0, 5),
        obs(6.5, 12),
        obs(7.0, 20),
        obs(6.8, 40),
        obs(7.2, 70),
        obs(4.0, 200),
        obs(4.2, 300),
    ]
    assert sell_advice(snapshot(rising, issue_year=2006, now=NOW), grade=Grade.UNC).hold is True


def test_deal_discount_relative_to_the_low_end_of_the_band():
    s = snapshot(SOLD, issue_year=2006, now=NOW)
    assert deal_discount(Decimal("2.40"), s.band) == pytest.approx(25.0, abs=0.5)
    assert deal_discount(Decimal("3.20"), s.band) == 0.0


def test_monthly_history_buckets_reliable_sales_and_asks_per_month():
    listings = SOLD + [
        obs(3.9, 2, kind=ObservationKind.ASKING),
        obs(40, 8, title="Lote 10 monedas 2 euro Alemania 2006"),
    ]
    points = monthly_history(listings, now=NOW, months=12)
    assert [p.month for p in points][-3:] == ["2026-07", "2026-08", "2026-09"]
    sept = points[-1]
    assert (sept.sold_n, sept.sold_min, sept.sold_max) == (2, Decimal("3.00"), Decimal("3.50"))
    assert (sept.ask_n, sept.ask_median) == (1, Decimal("3.90"))
    august = points[-2]  # sales 20 and 40 days ago
    assert (august.sold_n, august.sold_median) == (2, Decimal("3.90"))
    assert sum(p.sold_n for p in points) == 7  # the lot was ignored


def test_listing_copy_is_ready_to_paste_in_three_languages():
    from euro2core.pricing.market_intel import listing_copy

    copy = listing_copy(
        title="Schleswig-Holstein",
        country_code="DE",
        year=2006,
        mint_mark="A",
        finish="circulation",
        grade=Grade.UNC,
        mintage=6_000_000,
        price=Decimal("3.32"),
    )
    assert copy["es"]["title"] == "2 euros Alemania 2006 A Schleswig-Holstein sin circular"
    assert copy["en"]["title"] == "2 euro Germany 2006 A Schleswig-Holstein UNC"
    assert copy["de"]["title"] == "2 Euro Deutschland 2006 A Schleswig-Holstein unzirkuliert"
    assert "6.000.000" in copy["es"]["body"] and "3,32" in copy["es"]["body"]
    assert all(len(c["title"]) <= 80 for c in copy.values())  # eBay title limit


def test_external_search_links_cover_the_main_marketplaces():
    from euro2core.pricing.market_intel import search_links

    links = search_links(title="Schleswig-Holstein", country_code="DE", year=2006)
    labels = {link["label"] for link in links}
    assert {"eBay España", "eBay Alemania", "eBay Francia", "eBay Italia"} <= labels
    ebay_es = next(link for link in links if link["label"] == "eBay España")
    assert ebay_es["url"].startswith("https://www.ebay.es/sch/i.html?_nkw=")
    assert "Alemania" in ebay_es["url"] or "Alemania" in ebay_es["url"].replace("+", " ")
    assert any(link["kind"] == "sold" for link in links)  # completed-sales views too
