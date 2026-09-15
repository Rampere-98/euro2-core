from pathlib import Path

import pytest

from euro2core.sources.ecb.national import (
    NationalSideImage,
    assign_images_to_years,
    national_page_url,
    parse_national_sides,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ecb"


@pytest.fixture(scope="module")
def belgium() -> list[NationalSideImage]:
    return parse_national_sides((FIXTURES / "national_be.en.html").read_text("utf-8"))


def test_only_the_two_euro_box_is_parsed_in_page_order(belgium):
    assert [i.url.rsplit("/", 1)[-1] for i in belgium] == [
        "Belgium_2euroAl.jpg",
        "Belgium_2euro_2008.jpg",
        "Belgium_2euro_2014ph.jpg",
    ]
    assert belgium[0].url.startswith("https://www.ecb.europa.eu/euro/coins/")


def test_year_comes_from_the_filename_when_present(belgium):
    assert [i.year for i in belgium] == [None, 2008, 2014]


def test_vatican_page_skips_the_sede_vacante_photo_and_keeps_years():
    images = parse_national_sides((FIXTURES / "national_va.en.html").read_text("utf-8"))
    names = [i.url.rsplit("/", 1)[-1] for i in images]
    assert "Vaticano_2euro_SedeVacante.jpg" not in names
    assert [i.year for i in images] == [2002, 2013, 2016, 2017]


def test_page_without_a_two_euro_box_yields_nothing():
    assert parse_national_sides("<html><body><h3>€1</h3></body></html>") == []


def test_page_urls_use_the_ecb_slugs_that_differ_from_iso_codes():
    assert national_page_url("BE").endswith("/euro/coins/html/be.en.html")
    assert national_page_url("EE").endswith("/et.en.html")
    assert national_page_url("SI").endswith("/sl.en.html")
    assert national_page_url("MC").endswith("/mo.en.html")


def test_each_design_year_gets_the_latest_image_not_newer_than_it():
    images = [
        NationalSideImage("a.jpg", None),  # first design, undated on the ECB page
        NationalSideImage("b.jpg", 2008),
        NationalSideImage("c.jpg", 2014),
    ]
    assigned = assign_images_to_years(images, [1999, 2007, 2008, 2009, 2014])
    assert assigned == {1999: "a.jpg", 2007: "a.jpg", 2008: "b.jpg", 2009: "b.jpg", 2014: "c.jpg"}


def test_a_single_undated_image_covers_every_year():
    assert assign_images_to_years([NationalSideImage("x.jpg", None)], [2002, 2008]) == {
        2002: "x.jpg",
        2008: "x.jpg",
    }


def test_no_images_assigns_nothing():
    assert assign_images_to_years([], [2002]) == {}


def test_an_undated_last_image_is_the_current_design():
    # Netherlands: Beatrix (dated 2001) then Willem-Alexander (undated) on the ECB page
    images = [NationalSideImage("beatrix.jpg", 2001), NationalSideImage("wa.jpg", None)]
    assert assign_images_to_years(images, [1999, 2007, 2014]) == {
        1999: "beatrix.jpg",
        2007: "beatrix.jpg",
        2014: "wa.jpg",
    }
