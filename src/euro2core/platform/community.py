"""Expert validation of reported errors and varieties."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import CoinKind, ReportStatus, VerificationStatus
from euro2core.domain.models import (
    CoinIssue,
    CoinType,
    DomainEvent,
    ExpertReport,
    ExpertVote,
    Notification,
    TextTranslation,
    User,
)

APPROVALS_TO_VALIDATE = 2
REJECTIONS_TO_REJECT = 2


class CommunityError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


async def submit_report(
    session: AsyncSession,
    reporter: User,
    *,
    base_type_id: uuid.UUID,
    title: str,
    description: str,
    image_path: str | None,
) -> ExpertReport:
    base = await session.get(CoinType, base_type_id)
    if base is None or base.kind == CoinKind.ERROR:
        raise CommunityError("report a regular coin type as the base", 404)
    report = ExpertReport(
        reporter_id=reporter.id,
        base_type_id=base_type_id,
        title=title.strip()[:200],
        description=description.strip(),
        image_path=image_path,
    )
    session.add(report)
    await session.flush()
    return report


async def vote(
    session: AsyncSession, expert: User, report_id: uuid.UUID, *, approve: bool, comment: str | None
) -> ExpertReport:
    report = await session.get(ExpertReport, report_id)
    if report is None:
        raise CommunityError("report not found", 404)
    if report.status != ReportStatus.PENDING:
        raise CommunityError("report already decided", 409)
    if report.reporter_id == expert.id:
        raise CommunityError("you cannot validate your own report", 409)
    if await session.scalar(
        select(ExpertVote.id).where(
            ExpertVote.report_id == report.id, ExpertVote.expert_id == expert.id
        )
    ):
        raise CommunityError("already voted", 409)
    session.add(
        ExpertVote(report_id=report.id, expert_id=expert.id, approve=approve, comment=comment)
    )
    await session.flush()
    approvals = await session.scalar(
        select(func.count())
        .select_from(ExpertVote)
        .where(ExpertVote.report_id == report.id, ExpertVote.approve.is_(True))
    )
    rejections = await session.scalar(
        select(func.count())
        .select_from(ExpertVote)
        .where(ExpertVote.report_id == report.id, ExpertVote.approve.is_(False))
    )
    if approvals >= APPROVALS_TO_VALIDATE:
        await _validate(session, report)
    elif rejections >= REJECTIONS_TO_REJECT:
        report.status = ReportStatus.REJECTED
        session.add(
            Notification(
                user_id=report.reporter_id,
                kind="report_rejected",
                title="Tu reporte no ha sido validado",
                body="Your report was not validated by the experts",
                payload={"report_id": str(report.id)},
            )
        )
    await session.flush()
    return report


async def _validate(session: AsyncSession, report: ExpertReport) -> None:
    base = await session.get(CoinType, report.base_type_id)
    error_type = CoinType(
        kind=CoinKind.ERROR,
        country_code=base.country_code,
        year=base.year,
        base_type_id=base.id,
        verification_status=VerificationStatus.DOCUMENTED,
    )
    session.add(error_type)
    await session.flush()
    session.add(
        TextTranslation(
            entity="coin_type",
            entity_id=error_type.id,
            field="title",
            lang="en",
            text=report.title,
            source_id=await _community_source_id(session),
        )
    )
    session.add(
        CoinIssue(
            type_id=error_type.id,
            year=base.year,
            mint_mark="",
            finish="circulation",
            packaging="loose",
        )
    )
    session.add(
        DomainEvent(
            kind="error_validated",
            entity="coin_type",
            entity_id=error_type.id,
            payload={
                "report_id": str(report.id),
                "base_type_id": str(base.id),
                "title": report.title,
            },
        )
    )
    session.add(
        Notification(
            user_id=report.reporter_id,
            kind="report_validated",
            title="Los expertos han validado tu reporte",
            body="Experts validated your report; the error is now in the catalog",
            payload={"report_id": str(report.id), "type_id": str(error_type.id)},
        )
    )
    report.status = ReportStatus.VALIDATED
    report.created_type_id = error_type.id


async def _community_source_id(session: AsyncSession):
    from euro2core.domain.enums import SourceKind
    from euro2core.domain.models import Source

    source = (await session.scalars(select(Source).where(Source.code == "community"))).first()
    if source is None:
        source = Source(
            code="community", name="Expert community", authority_rank=40, kind=SourceKind.CATALOG
        )
        session.add(source)
        await session.flush()
    return source.id
