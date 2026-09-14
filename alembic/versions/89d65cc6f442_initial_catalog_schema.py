"""initial catalog schema

Revision ID: 89d65cc6f442
Revises:
Create Date: 2026-09-14 19:32:22.603654

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "89d65cc6f442"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.create_table(
        "country",
        sa.Column("code", sa.String(length=2), nullable=False),
        sa.Column("name_en", sa.String(length=100), nullable=False),
        sa.Column("eurozone_since", sa.Integer(), nullable=True),
        sa.Column("is_micro_state", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "domain_event",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("entity", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_domain_event_created", "domain_event", ["created_at"], unique=False)
    op.create_table(
        "source",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("authority_rank", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.Enum("catalog", "market", name="source_kind"), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.CheckConstraint("authority_rank BETWEEN 0 AND 100", name="ck_source_rank_range"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "sync_run",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job", sa.String(length=40), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.Enum("running", "succeeded", "failed", name="sync_status"), nullable=False
        ),
        sa.Column("cursor", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_run_job_started", "sync_run", ["job", "started_at"], unique=False)
    op.create_table(
        "fact_claim",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entity", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("field", sa.String(length=60), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_url", sa.Text(), nullable=True),
        sa.Column("is_winner", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity", "entity_id", "field", "source_id", "observed_at", name="uq_fact_claim_obs"
        ),
    )
    op.create_index(
        "ix_fact_claim_target", "fact_claim", ["entity", "entity_id", "field"], unique=False
    )
    op.create_table(
        "series",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("name_en", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(
            ["country_code"],
            ["country.code"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "text_translation",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entity", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("field", sa.String(length=60), nullable=False),
        sa.Column("lang", sa.String(length=2), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity", "entity_id", "field", "lang", name="uq_text_translation"),
    )
    op.create_table(
        "coin_type",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("commemorative", "circulation", "error", name="coin_kind"),
            nullable=False,
        ),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("series_id", sa.UUID(), nullable=True),
        sa.Column("joint_issue_group", sa.String(length=80), nullable=True),
        sa.Column("ecb_ref", sa.String(length=120), nullable=True),
        sa.Column("numista_type_id", sa.Integer(), nullable=True),
        sa.Column("base_type_id", sa.UUID(), nullable=True),
        sa.Column(
            "verification_status",
            sa.Enum("documented", "pending_expert", name="verification_status"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'error') = (base_type_id IS NOT NULL)", name="ck_coin_type_error_has_base"
        ),
        sa.CheckConstraint("year BETWEEN 1999 AND 2100", name="ck_coin_type_year"),
        sa.ForeignKeyConstraint(
            ["base_type_id"],
            ["coin_type.id"],
        ),
        sa.ForeignKeyConstraint(
            ["country_code"],
            ["country.code"],
        ),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["series.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ecb_ref"),
        sa.UniqueConstraint("numista_type_id"),
    )
    op.create_index(
        "ix_coin_type_country_year", "coin_type", ["country_code", "year"], unique=False
    )
    op.create_table(
        "coin_issue",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("type_id", sa.UUID(), nullable=False),
        sa.Column("mint_mark", sa.String(length=4), nullable=False),
        sa.Column("finish", sa.Enum("circulation", "bu", "proof", name="finish"), nullable=False),
        sa.Column(
            "packaging", sa.Enum("loose", "coincard", "set", name="packaging"), nullable=False
        ),
        sa.Column("mintage", sa.BigInteger(), nullable=True),
        sa.Column("numista_issue_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["type_id"], ["coin_type.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("numista_issue_id"),
        sa.UniqueConstraint(
            "type_id", "mint_mark", "finish", "packaging", name="uq_coin_issue_variant"
        ),
    )
    op.create_table(
        "coin_image",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("type_id", sa.UUID(), nullable=True),
        sa.Column("issue_id", sa.UUID(), nullable=True),
        sa.Column("side", sa.Enum("obverse", "reverse", "edge", name="image_side"), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("license", sa.String(length=120), nullable=True),
        sa.Column("author", sa.String(length=200), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=512), nullable=True),
        sa.CheckConstraint(
            "(type_id IS NOT NULL) OR (issue_id IS NOT NULL)", name="ck_coin_image_has_target"
        ),
        sa.ForeignKeyConstraint(["issue_id"], ["coin_issue.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["type_id"], ["coin_type.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_url"),
    )
    op.create_table(
        "market_observation",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("issue_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("marketplace", sa.String(length=20), nullable=False),
        sa.Column(
            "observation_kind",
            sa.Enum("sold", "asking", "auction_closed", name="observation_kind"),
            nullable=False,
        ),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "grade",
            sa.Enum("circulated", "unc", "bu", "proof", "unknown", name="grade"),
            nullable=False,
        ),
        sa.Column("sheldon", sa.SmallInteger(), nullable=True),
        sa.Column("certified_by", sa.String(length=20), nullable=True),
        sa.Column("listing_id", sa.String(length=80), nullable=False),
        sa.Column("listing_url", sa.Text(), nullable=False),
        sa.Column("title_raw", sa.Text(), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=False),
        sa.Column("is_outlier", sa.Boolean(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "match_confidence BETWEEN 0 AND 1", name="ck_market_observation_confidence"
        ),
        sa.CheckConstraint("price > 0", name="ck_market_observation_price_positive"),
        sa.CheckConstraint("sheldon IS NULL OR sheldon BETWEEN 1 AND 70", name="ck_sheldon_range"),
        sa.ForeignKeyConstraint(["issue_id"], ["coin_issue.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "marketplace", "listing_id", "observation_kind", name="uq_market_observation_listing"
        ),
    )
    op.create_index(
        "ix_market_observation_issue_time",
        "market_observation",
        ["issue_id", "observed_at"],
        unique=False,
    )
    op.create_table(
        "price_estimate",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("issue_id", sa.UUID(), nullable=False),
        sa.Column(
            "grade",
            postgresql.ENUM(name="grade", create_type=False),
            nullable=False,
        ),
        sa.Column("region", sa.String(length=20), nullable=False),
        sa.Column("window_days", sa.SmallInteger(), nullable=False),
        sa.Column("median", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("p25", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("p75", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("n_obs", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.String(length=10), nullable=False),
        sa.Column("basis", sa.String(length=20), nullable=False),
        sa.Column("method_version", sa.String(length=20), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["issue_id"], ["coin_issue.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issue_id", "grade", "region", name="uq_price_estimate_scope"),
    )
    op.create_table(
        "rarity_score",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("issue_id", sa.UUID(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("components", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("method_version", sa.String(length=20), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("score BETWEEN 0 AND 100", name="ck_rarity_score_range"),
        sa.ForeignKeyConstraint(["issue_id"], ["coin_issue.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issue_id"),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("rarity_score")
    op.drop_table("price_estimate")
    op.drop_index("ix_market_observation_issue_time", table_name="market_observation")
    op.drop_table("market_observation")
    op.drop_table("coin_image")
    op.drop_table("coin_issue")
    op.drop_index("ix_coin_type_country_year", table_name="coin_type")
    op.drop_table("coin_type")
    op.drop_table("text_translation")
    op.drop_table("series")
    op.drop_index("ix_fact_claim_target", table_name="fact_claim")
    op.drop_table("fact_claim")
    op.drop_index("ix_sync_run_job_started", table_name="sync_run")
    op.drop_table("sync_run")
    op.drop_table("source")
    op.drop_index("ix_domain_event_created", table_name="domain_event")
    op.drop_table("domain_event")
    op.drop_table("country")
    for enum_name in (
        "grade",
        "observation_kind",
        "image_side",
        "packaging",
        "finish",
        "verification_status",
        "coin_kind",
        "sync_status",
        "source_kind",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
