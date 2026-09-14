from dataclasses import replace
from pathlib import Path

import pytest

from euro2core.sources.ecb.parser import (
    EcbEntry,
    country_code_for,
    parse_commemorative_page,
    parse_mintage,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ecb"


@pytest.fixture(scope="module")
def entries_2024() -> list[EcbEntry]:
    return parse_commemorative_page((FIXTURES / "comm_2024.en.html").read_text("utf-8"), year=2024)


@pytest.fixture(scope="module")
def entries_2007() -> list[EcbEntry]:
    return parse_commemorative_page((FIXTURES / "comm_2007.en.html").read_text("utf-8"), year=2007)


def test_parses_every_national_box_on_the_2024_page(entries_2024):
    assert len(entries_2024) == 35


def test_first_2024_entry_is_lithuania_straw_gardens(entries_2024):
    e = entries_2024[0]
    assert e.country_code == "LT"
    assert e.year == 2024
    assert e.feature.startswith("Lithuanian tradition of straw gardens")
    assert "Tomas Dragūnas" in e.description
    assert e.mintage == 500_000
    assert e.issue_date_raw == "Fourth quarter of 2024"
    assert e.image_urls == [
        "https://www.ecb.europa.eu/euro/coins/comm/html/comm_2024/Lithuania.jpg"
    ]
    assert e.joint_issue_group is None


def test_mintage_with_thousands_separator_variants(entries_2024):
    by_feature = {e.feature: e for e in entries_2024}
    portugal = by_feature["Portugal’s participation in the 33rd Olympic Games"]
    assert portugal.mintage == 520_000


def test_2004_comma_separated_mintage():
    entries = parse_commemorative_page(
        (FIXTURES / "comm_2004.en.html").read_text("utf-8"), year=2004
    )
    assert entries[0].country_code == "VA"
    assert entries[0].mintage == 100_000


def test_joint_issue_expands_to_one_entry_per_country(entries_2007):
    joint = [e for e in entries_2007 if e.joint_issue_group is not None]
    assert len(joint) == 13
    assert {e.joint_issue_group for e in joint} == {"2007-treaty-of-rome"}
    assert {e.country_code for e in joint} >= {"DE", "ES", "FR", "IT", "SI"}
    assert all(e.mintage is None for e in joint)
    assert all(e.feature == "50th anniversary of the Treaty of Rome" for e in joint)
    assert all(len(e.image_urls) == 1 for e in joint)


def test_joint_issue_without_national_images_expands_to_all_member_states_of_that_year():
    entries = parse_commemorative_page(
        (FIXTURES / "comm_2022.en.html").read_text("utf-8"), year=2022
    )
    joint = [e for e in entries if e.joint_issue_group is not None]
    assert len(joint) == 19  # euro area in 2022, micro-states excluded, Croatia not yet
    assert {e.country_code for e in joint} >= {"DE", "ES", "LT", "LV", "EE"}
    assert "HR" not in {e.country_code for e in joint}
    assert {e.joint_issue_group for e in joint} == {"2022-35-years-of-the-erasmus-programme"}
    # each country gets its own national photo plus the shared Erasmus design
    assert all(any("erasmus" in u for u in e.image_urls) for e in joint)
    spain = next(e for e in joint if e.country_code == "ES")
    assert any(u.endswith("/Spain.jpg") for u in spain.image_urls)
    assert len(entries) == 19 + 30


def test_joint_issue_with_two_images_for_one_country_yields_one_entry():
    html = """
    <div class="box"><div class="coins">
      <picture><img src="comm_2009/joint_comm_2009_Luxembourg.jpg"></picture>
      <picture><img src="comm_2009/joint_comm_2009_Luxembourg_Face.jpg"></picture>
      <picture><img src="comm_2009/joint_comm_2009_Nederland.jpg"></picture>
    </div><div class="content-box"><h3>Euro area countries</h3><div>
      <p><strong>Feature:</strong> 10 years of EMU</p><p><strong>Description:</strong> x</p>
      <p><strong>Issuing volume:</strong> varies</p><p><strong>Issuing date:</strong> Jan 2009</p>
    </div></div></div>"""
    entries = parse_commemorative_page(html, year=2009)
    images = {e.country_code: len(e.image_urls) for e in entries}
    assert len(entries) == 16  # euro area members in 2009
    assert images["LU"] == 2
    assert images["NL"] == 1
    assert images["DE"] == 0  # participates, but the ECB page shows no photo


def test_non_joint_entries_on_2007_page_are_kept(entries_2007):
    national = [e for e in entries_2007 if e.joint_issue_group is None]
    assert [e.country_code for e in national] == ["FI", "SM", "VA", "MC", "PT", "DE", "LU"]


def test_ecb_ref_is_stable_and_unique_within_page(entries_2024):
    refs = [e.ecb_ref for e in entries_2024]
    assert len(refs) == len(set(refs))
    assert refs[0].startswith(
        "2024/LT/lithuanian-tradition-of-straw-gardens-inscribed-on-the-unesco"
    )
    assert len(refs[0]) <= 120


def test_ecb_ref_distinguishes_coins_with_the_same_opening_words():
    a = replace(
        _entry_stub(), feature="The 150th anniversary of the birth of artist Akseli Gallen-Kallela"
    )
    b = replace(
        _entry_stub(), feature="The 150th anniversary of the birth of composer Jean Sibelius"
    )
    assert a.ecb_ref != b.ecb_ref


def _entry_stub() -> EcbEntry:
    return EcbEntry(
        year=2015,
        country_code="FI",
        country_name="Finland",
        feature="",
        description="",
        mintage=None,
        mintage_raw="",
        issue_date_raw="",
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("100,000 coins", 100_000),
        ("500 000 coins", 500_000),
        ("7 000 coins", 7_000),
        ("max 750 000 coins", 750_000),
        ("1 million coins", 1_000_000),
        ("1 million", 1_000_000),
        ("1,4 million coins", 1_400_000),
        ("2.49 million coins", 2_490_000),
        ("30 millions coins", 30_000_000),
        ("varies from country to country", None),
        ("", None),
    ],
)
def test_parse_mintage_handles_every_format_seen_on_ecb_pages(raw, expected):
    assert parse_mintage(raw) == expected


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("Vatican City", "VA"),
        ("Vatican", "VA"),
        ("Netherlands", "NL"),
        ("The Netherlands", "NL"),
        ("Nederland", "NL"),
        ("Vatican City State", "VA"),
        ("San Marino", "SM"),
        ("Germany", "DE"),
    ],
)
def test_country_name_mapping(name, code):
    assert country_code_for(name) == code


def test_unknown_country_name_raises():
    with pytest.raises(KeyError):
        country_code_for("Atlantis")
