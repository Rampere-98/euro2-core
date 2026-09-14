from pathlib import Path

import pytest

from euro2core.sources.ecb.parser import EcbEntry, country_code_for, parse_commemorative_page

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


def test_non_joint_entries_on_2007_page_are_kept(entries_2007):
    national = [e for e in entries_2007 if e.joint_issue_group is None]
    assert [e.country_code for e in national] == ["FI", "SM", "VA", "MC", "PT", "DE", "LU"]


def test_ecb_ref_is_stable_and_unique_within_page(entries_2024):
    refs = [e.ecb_ref for e in entries_2024]
    assert len(refs) == len(set(refs))
    assert refs[0] == "2024/LT/lithuanian-tradition-of-straw-gardens-inscribed"


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("Vatican City", "VA"),
        ("Vatican", "VA"),
        ("Netherlands", "NL"),
        ("The Netherlands", "NL"),
        ("San Marino", "SM"),
        ("Germany", "DE"),
    ],
)
def test_country_name_mapping(name, code):
    assert country_code_for(name) == code


def test_unknown_country_name_raises():
    with pytest.raises(KeyError):
        country_code_for("Atlantis")
