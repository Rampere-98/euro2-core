import json
from pathlib import Path

import pytest

from euro2core.domain.enums import CoinKind, Finish, Packaging
from euro2core.sources.numista.parser import (
    EUROZONE_ISSUERS,
    classify_kind,
    is_two_euro,
    iso_for_issuer,
    parse_issue,
    parse_type,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "numista"


def load(name: str):
    return json.loads((FIXTURES / name).read_text("utf-8"))


def test_search_results_are_filtered_to_two_euro_coins_only():
    results = load("search_germany_2euro.json")["types"]
    kept = [t for t in results if is_two_euro(t)]
    titles = {t["title"] for t in kept}
    assert "2 Euro Cents" not in titles
    assert "1 Euro (1st map)" not in titles
    assert "2 Euro (Pattern)" not in titles  # patterns are not real coins
    assert '2 Euros (Bundesländer - "Schleswig-Holstein")' in titles
    assert "2 Euros (2nd map)" in titles
    assert '2 Euros Bundesländer - "Hamburg" (Mule)' in titles
    assert len(kept) == 38


@pytest.mark.parametrize(
    ("title", "object_type", "kind"),
    [
        (
            '2 Euros (Bundesländer - "Schleswig-Holstein")',
            "Circulating commemorative coins",
            CoinKind.COMMEMORATIVE,
        ),
        ("2 Euros (2nd map)", "Standard circulation coins", CoinKind.CIRCULATION),
        ("2 Euros - John Paul II", "Standard circulation coins", CoinKind.CIRCULATION),
        ("2 Euros - Benedict XVI (Swiss Guard)", "Non-circulating coins", CoinKind.COMMEMORATIVE),
        (
            '2 Euros Bundesländer - "Hamburg" (Mule)',
            "Circulating commemorative coins",
            CoinKind.ERROR,
        ),
    ],
)
def test_kind_classification(title, object_type, kind):
    assert classify_kind(title, object_type) == kind


def test_parse_type_detail_extracts_catalog_fields_and_image_attribution():
    t = parse_type(load("type_2169.json"))
    assert t.id == 2169
    assert t.country_code == "DE"
    assert t.kind == CoinKind.COMMEMORATIVE
    assert t.year == 2006
    assert t.title == '2 Euros (Bundesländer - "Schleswig-Holstein")'
    assert t.series == "German states"
    assert t.topic == "State of Schleswig-Holstein"
    assert t.url == "https://en.numista.com/2169"
    assert t.km_reference == "KM 253"
    assert t.obverse.url.endswith("-original.jpg")
    assert t.obverse.author == "brismike"
    assert t.obverse.license == "CC BY-NC"
    assert t.reverse.author == "brismike"
    assert "Holstentor" in t.obverse_description


def test_parse_type_in_spanish_gives_localized_descriptions():
    t = parse_type(load("type_2169_es.json"))
    assert t.lang == "es"
    assert "níquel" in t.composition
    assert t.obverse_description != parse_type(load("type_2169.json")).obverse_description


@pytest.mark.parametrize(
    ("raw", "mint", "finish", "packaging", "mintage"),
    [
        (
            {"id": 1, "year": 2006, "mint_letter": "A", "mintage": 6000000},
            "A",
            Finish.CIRCULATION,
            Packaging.LOOSE,
            6000000,
        ),
        (
            {"id": 2, "year": 2006, "mint_letter": "A", "mintage": 85000, "comment": "BU set"},
            "A",
            Finish.BU,
            Packaging.SET,
            85000,
        ),
        (
            {"id": 3, "year": 2006, "mint_letter": "A", "mintage": 75000, "comment": "Proof"},
            "A",
            Finish.PROOF,
            Packaging.LOOSE,
            75000,
        ),
        (
            {"id": 4, "year": 2010, "mint_letter": "D", "comment": "in Sets"},
            "D",
            Finish.BU,
            Packaging.SET,
            None,
        ),
        (
            {"id": 5, "year": 2006, "mint_letter": "R", "mintage": 100000},
            "R",
            Finish.CIRCULATION,
            Packaging.LOOSE,
            100000,
        ),
        (
            {"id": 6, "year": 2013, "mintage": 5000, "comment": "Coincard"},
            "",
            Finish.BU,
            Packaging.COINCARD,
            5000,
        ),
        ({"id": 7, "year": 2015, "comment": "Proof set"}, "", Finish.PROOF, Packaging.SET, None),
    ],
)
def test_parse_issue_maps_comment_to_finish_and_packaging(raw, mint, finish, packaging, mintage):
    issue = parse_issue(raw)
    assert issue.mint_mark == mint
    assert issue.finish == finish
    assert issue.packaging == packaging
    assert issue.mintage == mintage
    assert issue.year == raw["year"]


def test_real_issue_list_yields_fifteen_variants_for_a_german_commemorative():
    issues = [parse_issue(i) for i in load("type_2169_issues.json")]
    assert len(issues) == 15
    assert sorted({i.mint_mark for i in issues}) == ["A", "D", "F", "G", "J"]
    assert {(i.finish, i.packaging) for i in issues} == {
        (Finish.CIRCULATION, Packaging.LOOSE),
        (Finish.BU, Packaging.SET),
        (Finish.PROOF, Packaging.LOOSE),
    }
    assert sum(i.mintage for i in issues if i.finish == Finish.CIRCULATION) == 30_110_000


def test_issuer_codes_map_to_iso_including_section_and_child_codes():
    assert iso_for_issuer("germany") == "DE"
    assert iso_for_issuer("allemagne") == "DE"
    assert iso_for_issuer("papal_states_section") == "VA"
    assert iso_for_issuer("vatican") == "VA"
    assert iso_for_issuer("saint-marin") == "SM"
    assert set(EUROZONE_ISSUERS.values()) >= {"DE", "ES", "VA", "MC", "SM", "AD", "HR", "BG"}
