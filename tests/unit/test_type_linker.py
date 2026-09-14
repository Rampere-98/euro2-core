from euro2core.sources.ecb.parser import EcbEntry
from euro2core.sources.linker import LINK_THRESHOLD, link_score, match_ecb_entry


def ecb(country, year, feature, group=None) -> EcbEntry:
    return EcbEntry(
        year=year,
        country_code=country,
        country_name=country,
        feature=feature,
        description="",
        mintage=None,
        mintage_raw="",
        issue_date_raw="",
        image_urls=[],
        joint_issue_group=group,
    )


GERMANY_2015 = [
    ecb("DE", 2015, "Federal state of Hessen"),
    ecb("DE", 2015, "25 years of German Unity"),
    ecb("DE", 2015, "30th anniversary of the EU flag", group="2015-eu-flag"),
]


def test_picks_the_right_coin_among_same_country_same_year_candidates():
    hit, score = match_ecb_entry(
        country="DE",
        year=2015,
        title='2 Euros (Bundesländer - "Hessen")',
        topic="State of Hessen",
        candidates=GERMANY_2015,
    )
    assert hit is GERMANY_2015[0]
    assert score >= LINK_THRESHOLD


def test_unity_anniversary_matches_by_meaningful_words_not_numbers_alone():
    hit, _ = match_ecb_entry(
        country="DE",
        year=2015,
        title="2 Euros (25 Years of German Unity)",
        topic="German reunification",
        candidates=GERMANY_2015,
    )
    assert hit is GERMANY_2015[1]


def test_joint_issue_matches_its_national_entry():
    candidates = [
        ecb("ES", 2007, "50th anniversary of the Treaty of Rome", group="2007-treaty-of-rome")
    ]
    hit, _ = match_ecb_entry(
        country="ES", year=2007, title="2 Euros (Treaty of Rome)", topic=None, candidates=candidates
    )
    assert hit is candidates[0]


def test_other_country_or_year_is_never_matched():
    hit, score = match_ecb_entry(
        country="FR",
        year=2015,
        title='2 Euros (Bundesländer - "Hessen")',
        topic="State of Hessen",
        candidates=GERMANY_2015,
    )
    assert hit is None
    assert score == 0


def test_weak_similarity_is_rejected():
    hit, score = match_ecb_entry(
        country="DE",
        year=2015,
        title="2 Euros (Something completely unrelated)",
        topic="Bratwurst festival",
        candidates=GERMANY_2015,
    )
    assert hit is None
    assert score < LINK_THRESHOLD


def test_link_score_ignores_boilerplate_tokens():
    assert link_score('2 Euros (Bundesländer - "Hessen")', None, "Federal state of Hessen") > 60
    assert link_score("2 Euros", None, "Federal state of Hessen") < LINK_THRESHOLD
