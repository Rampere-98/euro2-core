import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from euro2core.db import Base
from euro2core.domain.enums import (
    CoinKind,
    Finish,
    Grade,
    ImageSide,
    ObservationKind,
    Packaging,
    SourceKind,
    SyncStatus,
    VerificationStatus,
)


def _enum(enum_cls: type, name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Country(Base):
    __tablename__ = "country"

    code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    eurozone_since: Mapped[int | None] = mapped_column(Integer)
    is_micro_state: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Series(Base):
    __tablename__ = "series"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    country_code: Mapped[str | None] = mapped_column(ForeignKey("country.code"))
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)


class Source(Base):
    __tablename__ = "source"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    authority_rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    kind: Mapped[SourceKind] = mapped_column(_enum(SourceKind, "source_kind"), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("authority_rank BETWEEN 0 AND 100", name="ck_source_rank_range"),
    )


class CoinType(Base):
    __tablename__ = "coin_type"

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[CoinKind] = mapped_column(_enum(CoinKind, "coin_kind"), nullable=False)
    country_code: Mapped[str] = mapped_column(ForeignKey("country.code"), nullable=False)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    series_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("series.id"))
    joint_issue_group: Mapped[str | None] = mapped_column(String(80))
    # ECB total issuing volume across mints and finishes; per-variant mintage lives on issues
    mintage_total: Mapped[int | None] = mapped_column(BigInteger)
    ecb_ref: Mapped[str | None] = mapped_column(String(120), unique=True)
    numista_type_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    base_type_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("coin_type.id"))
    verification_status: Mapped[VerificationStatus | None] = mapped_column(
        _enum(VerificationStatus, "verification_status")
    )
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    issues: Mapped[list["CoinIssue"]] = relationship(back_populates="type")

    __table_args__ = (
        CheckConstraint("year BETWEEN 1999 AND 2100", name="ck_coin_type_year"),
        CheckConstraint(
            "(kind = 'error') = (base_type_id IS NOT NULL)", name="ck_coin_type_error_has_base"
        ),
        Index("ix_coin_type_country_year", "country_code", "year"),
    )


class CoinIssue(Base):
    __tablename__ = "coin_issue"

    id: Mapped[uuid.UUID] = _uuid_pk()
    type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("coin_type.id", ondelete="CASCADE"), nullable=False
    )
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Empty string means "no mint mark" so the unique constraint applies (NULLs are distinct)
    mint_mark: Mapped[str] = mapped_column(String(4), default="", nullable=False)
    finish: Mapped[Finish] = mapped_column(_enum(Finish, "finish"), nullable=False)
    packaging: Mapped[Packaging] = mapped_column(
        _enum(Packaging, "packaging"), default=Packaging.LOOSE, nullable=False
    )
    mintage: Mapped[int | None] = mapped_column(BigInteger)
    numista_issue_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    created_at: Mapped[datetime] = _now()

    type: Mapped[CoinType] = relationship(back_populates="issues")

    __table_args__ = (
        UniqueConstraint(
            "type_id", "year", "mint_mark", "finish", "packaging", name="uq_coin_issue_variant"
        ),
        CheckConstraint("year BETWEEN 1999 AND 2100", name="ck_coin_issue_year"),
    )


class MarketObservation(Base):
    __tablename__ = "market_observation"

    id: Mapped[uuid.UUID] = _uuid_pk()
    issue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("coin_issue.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id"), nullable=False)
    marketplace: Mapped[str] = mapped_column(String(20), nullable=False)
    observation_kind: Mapped[ObservationKind] = mapped_column(
        _enum(ObservationKind, "observation_kind"), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    grade: Mapped[Grade] = mapped_column(
        _enum(Grade, "grade"), default=Grade.UNKNOWN, nullable=False
    )
    sheldon: Mapped[int | None] = mapped_column(SmallInteger)
    certified_by: Mapped[str | None] = mapped_column(String(20))
    listing_id: Mapped[str] = mapped_column(String(80), nullable=False)
    listing_url: Mapped[str] = mapped_column(Text, nullable=False)
    title_raw: Mapped[str] = mapped_column(Text, nullable=False)
    match_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    is_outlier: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "marketplace", "listing_id", "observation_kind", name="uq_market_observation_listing"
        ),
        CheckConstraint("price > 0", name="ck_market_observation_price_positive"),
        CheckConstraint(
            "match_confidence BETWEEN 0 AND 1", name="ck_market_observation_confidence"
        ),
        CheckConstraint("sheldon IS NULL OR sheldon BETWEEN 1 AND 70", name="ck_sheldon_range"),
        Index("ix_market_observation_issue_time", "issue_id", "observed_at"),
    )


class FactClaim(Base):
    __tablename__ = "fact_claim"

    id: Mapped[uuid.UUID] = _uuid_pk()
    entity: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    field: Mapped[str] = mapped_column(String(60), nullable=False)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_url: Mapped[str | None] = mapped_column(Text)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_fact_claim_target", "entity", "entity_id", "field"),
        UniqueConstraint(
            "entity", "entity_id", "field", "source_id", "observed_at", name="uq_fact_claim_obs"
        ),
    )


class TextTranslation(Base):
    __tablename__ = "text_translation"

    id: Mapped[uuid.UUID] = _uuid_pk()
    entity: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    field: Mapped[str] = mapped_column(String(60), nullable=False)
    lang: Mapped[str] = mapped_column(String(2), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("entity", "entity_id", "field", "lang", name="uq_text_translation"),
    )


class CoinImage(Base):
    __tablename__ = "coin_image"

    id: Mapped[uuid.UUID] = _uuid_pk()
    type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("coin_type.id", ondelete="CASCADE")
    )
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("coin_issue.id", ondelete="CASCADE")
    )
    side: Mapped[ImageSide] = mapped_column(_enum(ImageSide, "image_side"), nullable=False)
    # NULL while the origin blocks automated downloads; the reference (URL, author, license) stays
    local_path: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    license: Mapped[str | None] = mapped_column(String(120))
    author: Mapped[str | None] = mapped_column(String(200))
    sha256: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = _now()
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR(512))

    __table_args__ = (
        CheckConstraint(
            "(type_id IS NOT NULL) OR (issue_id IS NOT NULL)", name="ck_coin_image_has_target"
        ),
    )


class PriceEstimate(Base):
    __tablename__ = "price_estimate"

    id: Mapped[uuid.UUID] = _uuid_pk()
    issue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("coin_issue.id", ondelete="CASCADE"), nullable=False
    )
    grade: Mapped[Grade] = mapped_column(_enum(Grade, "grade"), nullable=False)
    region: Mapped[str] = mapped_column(String(20), nullable=False)
    window_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    median: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    p25: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    p75: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    n_obs: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    basis: Mapped[str] = mapped_column(String(20), nullable=False)
    method_version: Mapped[str] = mapped_column(String(20), nullable=False)
    computed_at: Mapped[datetime] = _now()

    __table_args__ = (
        UniqueConstraint("issue_id", "grade", "region", name="uq_price_estimate_scope"),
    )


class RarityScore(Base):
    __tablename__ = "rarity_score"

    id: Mapped[uuid.UUID] = _uuid_pk()
    issue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("coin_issue.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    method_version: Mapped[str] = mapped_column(String(20), nullable=False)
    computed_at: Mapped[datetime] = _now()

    __table_args__ = (CheckConstraint("score BETWEEN 0 AND 100", name="ck_rarity_score_range"),)


class DomainEvent(Base):
    __tablename__ = "domain_event"

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    entity: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (Index("ix_domain_event_created", "created_at"),)


class SyncRun(Base):
    __tablename__ = "sync_run"

    id: Mapped[uuid.UUID] = _uuid_pk()
    job: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[SyncStatus] = mapped_column(
        _enum(SyncStatus, "sync_status"), default=SyncStatus.RUNNING, nullable=False
    )
    cursor: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_sync_run_job_started", "job", "started_at"),)
