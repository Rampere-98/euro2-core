import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class ImageOut(BaseModel):
    id: uuid.UUID
    side: str
    url: str | None  # local copy served by the API; None when only the reference is known
    source_url: str
    author: str | None
    license: str | None
    # True when the photo belongs to the base design this coin derives from (a coloured or
    # hologram edition, a minting error) because no photo of the coin itself exists
    borrowed: bool = False


class FactAlternative(BaseModel):
    value: Any
    source: str
    observed_at: datetime
    evidence_url: str | None


class FactOut(BaseModel):
    value: Any
    source: str
    observed_at: datetime
    evidence_url: str | None
    has_conflict: bool
    alternatives: list[FactAlternative]


class ValueHint(BaseModel):
    """Value range of a coin type from its best available basis, for lists and filters."""

    low: Decimal
    high: Decimal
    median: Decimal
    basis: str  # sold | catalog | mintage_model | asking_only


class TypeSummary(BaseModel):
    id: uuid.UUID
    kind: str
    country_code: str
    year: int
    title: str | None
    mintage_total: int | None
    joint_issue_group: str | None
    ecb_ref: str | None
    numista_type_id: int | None
    base_type_id: uuid.UUID | None = None  # set for editions and errors derived from a design
    issue_count: int
    image: ImageOut | None
    value: ValueHint | None = None


class IssueSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    year: int
    mint_mark: str
    finish: str
    packaging: str
    mintage: int | None
    numista_issue_id: int | None


class TypeDetail(TypeSummary):
    description: str | None
    composition: str | None
    series: str | None
    topic: str | None
    km_reference: str | None
    verification_status: str | None
    facts: dict[str, FactOut]
    issues: list[IssueSummary]
    images: list[ImageOut]
    available_languages: list[str]


class EstimateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    grade: str
    region: str
    window_days: int
    median: Decimal | None
    p25: Decimal | None
    p75: Decimal | None
    n_obs: int
    confidence: str
    basis: str
    method_version: str


class RarityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    score: float
    tier: str
    components: dict[str, Any]
    method_version: str
    computed_at: datetime


class IssueDetail(IssueSummary):
    type: TypeSummary
    facts: dict[str, FactOut]
    estimates: list[EstimateOut]
    rarity: RarityOut | None
    images: list[ImageOut]


class ObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    marketplace: str
    observation_kind: str
    price: Decimal
    currency: str
    grade: str
    sheldon: int | None
    certified_by: str | None
    listing_url: str
    title_raw: str
    match_confidence: float
    is_outlier: bool
    observed_at: datetime


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    entity: str
    entity_id: uuid.UUID
    payload: dict[str, Any]
    created_at: datetime


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    authority_rank: int
    kind: str
    base_url: str | None


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    stats: dict[str, Any] | None
    error: str | None


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
