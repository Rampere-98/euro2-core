"""What a piece is worth right now, and where that number comes from."""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import Grade
from euro2core.domain.models import PriceEstimate
from euro2core.pricing.estimator import GLOBAL_REGION

FACE_VALUE = Decimal("2.00")
# preferred order of evidence; never disguise a weaker basis as a stronger one
BASIS_RANK = {"sold": 0, "catalog": 1, "asking_only": 2}
GRADE_FALLBACK = {
    Grade.UNKNOWN: (Grade.UNC, Grade.CIRCULATED, Grade.BU, Grade.PROOF),
    Grade.CIRCULATED: (Grade.UNC,),
    Grade.UNC: (Grade.BU, Grade.CIRCULATED),
    Grade.BU: (Grade.UNC,),
    Grade.PROOF: (Grade.BU, Grade.UNC),
}


@dataclass(frozen=True)
class Valuation:
    value: Decimal
    basis: str  # sold | catalog | asking_only | face_value
    grade: Grade | None
    n_obs: int
    confidence: str


async def valuations_for(
    session: AsyncSession, wanted: list[tuple[uuid.UUID, Grade]]
) -> dict[tuple[uuid.UUID, Grade], Valuation]:
    """Best available value per (issue, grade): realized sales, else catalog, else asking,
    else face value with basis "face_value" so nobody mistakes it for a market price."""
    issue_ids = {issue_id for issue_id, _ in wanted}
    if not issue_ids:
        return {}
    rows = (
        await session.scalars(
            select(PriceEstimate).where(
                PriceEstimate.issue_id.in_(issue_ids),
                PriceEstimate.region == GLOBAL_REGION,
                PriceEstimate.median.is_not(None),
            )
        )
    ).all()
    by_issue: dict[uuid.UUID, list[PriceEstimate]] = {}
    for e in rows:
        by_issue.setdefault(e.issue_id, []).append(e)
    return {
        (issue_id, grade): _pick(by_issue.get(issue_id, []), grade) for issue_id, grade in wanted
    }


def _pick(estimates: list[PriceEstimate], grade: Grade) -> Valuation:
    for candidate_grade in (grade, *GRADE_FALLBACK.get(grade, ())):
        matching = [e for e in estimates if e.grade == candidate_grade]
        if matching:
            best = min(matching, key=lambda e: (BASIS_RANK.get(e.basis, 9), -e.n_obs))
            return Valuation(best.median, best.basis, best.grade, best.n_obs, best.confidence)
    return Valuation(FACE_VALUE, "face_value", None, 0, "none")
