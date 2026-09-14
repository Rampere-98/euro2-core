"""Declarative schema checks: no database needed, inspects SQLAlchemy metadata."""

from sqlalchemy import UniqueConstraint

from euro2core.db import Base
from euro2core.domain import models  # noqa: F401  (registers tables on Base.metadata)
from euro2core.domain.enums import CoinKind, Finish, Grade, ObservationKind, Packaging

EXPECTED_TABLES = {
    "country",
    "series",
    "source",
    "coin_type",
    "coin_issue",
    "market_observation",
    "fact_claim",
    "text_translation",
    "coin_image",
    "price_estimate",
    "rarity_score",
    "domain_event",
    "sync_run",
}


def _unique_sets(table_name: str) -> set[frozenset[str]]:
    table = Base.metadata.tables[table_name]
    return {
        frozenset(c.name for c in cons.columns)
        for cons in table.constraints
        if isinstance(cons, UniqueConstraint)
    }


def test_all_domain_tables_are_declared():
    assert set(Base.metadata.tables) >= EXPECTED_TABLES


def test_coin_issue_is_unique_per_type_year_mint_finish_packaging():
    # circulation types span many years; each year x mint x finish is its own issue
    assert frozenset({"type_id", "year", "mint_mark", "finish", "packaging"}) in _unique_sets(
        "coin_issue"
    )


def test_market_observation_is_unique_per_listing_and_kind():
    assert frozenset({"marketplace", "listing_id", "observation_kind"}) in _unique_sets(
        "market_observation"
    )


def test_fact_claim_has_provenance_columns():
    cols = set(Base.metadata.tables["fact_claim"].columns.keys())
    assert {
        "entity",
        "entity_id",
        "field",
        "value",
        "source_id",
        "observed_at",
        "is_winner",
    } <= cols


def test_coin_image_reserves_vector_embedding_for_vision_module():
    col = Base.metadata.tables["coin_image"].columns["embedding"]
    assert col.nullable
    assert col.type.dim == 512


def test_enums_cover_approved_vocabulary():
    assert {k.value for k in CoinKind} == {"commemorative", "circulation", "error"}
    assert {f.value for f in Finish} == {"circulation", "bu", "proof"}
    assert {p.value for p in Packaging} == {"loose", "coincard", "set"}
    assert {g.value for g in Grade} == {"circulated", "unc", "bu", "proof", "unknown"}
    assert {o.value for o in ObservationKind} == {
        "sold",
        "asking",
        "auction_open",
        "auction_closed",
    }
