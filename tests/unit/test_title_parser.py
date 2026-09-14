import pytest

from euro2core.domain.enums import Finish, Grade, Packaging
from euro2core.pricing.title_parser import parse_title


@pytest.mark.parametrize(
    ("title", "country", "year"),
    [
        ("2 Euro Alemania 2006 Schleswig-Holstein", "DE", 2006),
        ("2 Euro Deutschland 2006 Holstentor Lübeck A", "DE", 2006),
        ("2 euros France 2015 30 ans du drapeau européen", "FR", 2015),
        ("2 Euro Vaticano 2004 75° anniversario", "VA", 2004),
        ("Moneda 2€ Mónaco 2007 Grace Kelly", "MC", 2007),
        ("2 Euro San Marino 2004 Bartolomeo Borghesi", "SM", 2004),
    ],
)
def test_country_and_year_in_several_languages(title, country, year):
    p = parse_title(title)
    assert p.country_code == country
    assert p.year == year


@pytest.mark.parametrize(
    ("title", "mark"),
    [
        ("2 Euro Deutschland 2006 Schleswig-Holstein Prägestätte A", "A"),
        ("2 Euro Alemania 2006 Holstentor ceca J", "J"),
        ("2 Euro Germany 2006 Schleswig-Holstein G unc", "G"),
        ("2 Euro Deutschland 2006 D bfr", "D"),
        ("2 Euro Alemania 2006", None),
        ("2 Euro France 2015 A", None),
    ],
)
def test_german_mint_marks_only_in_german_context(title, mark):
    assert parse_title(title).mint_mark == mark


@pytest.mark.parametrize(
    ("title", "finish", "packaging"),
    [
        ("2 Euro Deutschland 2019 Bundesrat Stempelglanz", Finish.BU, None),
        ("2 Euro Deutschland 2019 PP Polierte Platte", Finish.PROOF, None),
        ("2 euros France 2019 BE Belle Epreuve", Finish.PROOF, None),
        ("2 euro Italia 2019 FDC Fior di Conio", Finish.BU, None),
        ("2 Euro Alemania 2019 Proof", Finish.PROOF, None),
        ("2 Euro Nederland 2013 coincard BU", Finish.BU, Packaging.COINCARD),
        ("2 euros España 2018 cartera oficial FNMT", None, Packaging.COINCARD),
        ("2 Euro Deutschland 2006 KMS Set", None, Packaging.SET),
        ("2 Euro Alemania 2006 Schleswig-Holstein circulada", None, None),
    ],
)
def test_finish_and_packaging(title, finish, packaging):
    p = parse_title(title)
    assert p.finish == finish
    assert p.packaging == packaging


@pytest.mark.parametrize(
    "title",
    [
        "Lote 5 monedas 2 euros conmemorativas",
        "2 Euro Deutschland 2006 ADFGJ komplett",
        "Lot de 12 pièces 2 euros commémoratives",
        "2 Euro Sammlung 2004-2010 Konvolut",
        "Set completo 2 euros Alemania 2006 A D F G J",
        "2 euro x10 commemorative coins",
    ],
)
def test_lots_and_sets_of_several_coins_are_flagged(title):
    assert parse_title(title).is_lot is True


def test_single_coin_is_not_a_lot():
    assert parse_title("2 Euro Alemania 2006 Schleswig-Holstein").is_lot is False


@pytest.mark.parametrize(
    ("title", "grade", "sheldon", "certifier"),
    [
        ("2 Euro Deutschland 2006 A PCGS MS66", Grade.UNC, 66, "PCGS"),
        ("2 Euro Vaticano 2004 NGC MS 65", Grade.UNC, 65, "NGC"),
        ("2 Euro Alemania 2006 circulada", Grade.CIRCULATED, None, None),
        ("2 Euro Deutschland 2006 aus Umlauf", Grade.CIRCULATED, None, None),
        ("2 Euro Deutschland 2006 bfr", Grade.UNC, None, None),
        ("2 Euro Alemania 2006 SC sin circular", Grade.UNC, None, None),
        ("2 Euro Deutschland 2019 Stempelglanz", Grade.BU, None, None),
        ("2 Euro Deutschland 2019 PP", Grade.PROOF, None, None),
        ("2 Euro Alemania 2006", Grade.UNKNOWN, None, None),
    ],
)
def test_grade_inference(title, grade, sheldon, certifier):
    p = parse_title(title)
    assert p.grade == grade
    assert p.sheldon == sheldon
    assert p.certified_by == certifier


@pytest.mark.parametrize(
    ("title", "coloured"),
    [
        ("2 Euro Frankreich 2014 Welt-AIDS-Tag farbig coloriert", True),
        ("2 euros France 2015 drapeau colorisée", True),
        ("2 euro Italia 2019 colorata", True),
        ("2 euros Alemania 2006 Schleswig-Holstein coloreada", True),
        ("2 Euro Netherlands 2015 EU flag coloured", True),
        ("2 Euro Deutschland 2006 Schleswig-Holstein A", False),
    ],
)
def test_coloured_editions_are_flagged(title, coloured):
    assert parse_title(title).is_coloured is coloured


def test_theme_words_exclude_structural_tokens():
    p = parse_title("2 Euro Alemania 2006 Schleswig-Holstein Holstentor A Stempelglanz")
    assert p.theme_text == "schleswig holstein holstentor"
