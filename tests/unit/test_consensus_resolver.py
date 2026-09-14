import random
import uuid
from datetime import UTC, datetime, timedelta

from euro2core.consensus.resolver import Claim, normalize, resolve, resolve_all

ENTITY_ID = uuid.uuid4()
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def claim(value, rank, *, source="x", at=T0, field="mintage", entity_id=ENTITY_ID) -> Claim:
    return Claim(
        entity="coin_type",
        entity_id=entity_id,
        field=field,
        value=value,
        source_code=source,
        authority_rank=rank,
        observed_at=at,
    )


def test_highest_authority_wins():
    res = resolve([claim(1_500_000, 50, source="numista"), claim(1_000_000, 100, source="ecb")])
    assert res.winner.source_code == "ecb"
    assert res.winner.value == 1_000_000


def test_tie_on_authority_goes_to_most_recent():
    old = claim(10, 50, source="a", at=T0)
    new = claim(20, 50, source="b", at=T0 + timedelta(days=1))
    assert resolve([old, new]).winner is new


def test_agreeing_sources_do_not_conflict():
    res = resolve([claim(1_000_000, 100, source="ecb"), claim(1_000_000, 50, source="numista")])
    assert res.has_conflict is False
    assert res.alternatives == []


def test_disagreeing_authoritative_sources_conflict_and_alternatives_are_kept():
    res = resolve([claim(1_000_000, 100, source="ecb"), claim(1_500_000, 50, source="numista")])
    assert res.has_conflict is True
    assert [a.source_code for a in res.alternatives] == ["numista"]


def test_disagreement_from_low_rank_source_is_not_a_conflict():
    res = resolve([claim(1_000_000, 100, source="ecb"), claim(999, 10, source="ebay")])
    assert res.has_conflict is False
    assert [a.source_code for a in res.alternatives] == ["ebay"]


def test_normalization_makes_equivalent_values_agree():
    assert normalize("mintage", "1.000.000") == normalize("mintage", 1_000_000)
    assert normalize("mintage", "1 000 000") == 1_000_000
    assert normalize("theme", "  Schleswig-Holstein ") == normalize("theme", "schleswig–holstein")
    assert normalize("theme", "Städte") == normalize("theme", "stadte")
    assert normalize("issue_date", "2006-02-03") == normalize("issue_date", datetime(2006, 2, 3))


def test_resolution_is_independent_of_input_order():
    claims = [
        claim(1, 100, source="ecb"),
        claim(2, 80, source="mint", at=T0 + timedelta(days=5)),
        claim(3, 50, source="numista"),
        claim(4, 10, source="ebay"),
    ]
    winners = set()
    for seed in range(10):
        shuffled = claims[:]
        random.Random(seed).shuffle(shuffled)
        winners.add(resolve(shuffled).winner.source_code)
    assert winners == {"ecb"}


def test_resolve_all_groups_by_entity_and_field():
    other_id = uuid.uuid4()
    claims = [
        claim(1_000_000, 100),
        claim(1_500_000, 50),
        claim("Bundesländer", 50, field="theme"),
        claim(5_000, 100, entity_id=other_id),
    ]
    out = resolve_all(claims)
    assert set(out) == {
        ("coin_type", ENTITY_ID, "mintage"),
        ("coin_type", ENTITY_ID, "theme"),
        ("coin_type", other_id, "mintage"),
    }
    assert out[("coin_type", ENTITY_ID, "mintage")].has_conflict is True
    assert out[("coin_type", ENTITY_ID, "theme")].winner.value == "Bundesländer"
