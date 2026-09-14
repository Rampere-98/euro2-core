import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.api.auth_deps import CurrentUser, ExpertUser
from euro2core.api.deps import LangDep, SessionDep
from euro2core.api.queries import summaries_for
from euro2core.api.schemas import Page, TypeSummary
from euro2core.config import get_settings
from euro2core.domain.enums import ReportStatus
from euro2core.domain.models import ExpertReport, ExpertVote, NewsItem
from euro2core.platform.community import CommunityError, submit_report, vote
from euro2core.platform.semantic import get_text_embedder, semantic_search

router = APIRouter(tags=["community"])


class NewsOut(BaseModel):
    id: uuid.UUID
    kind: str
    entity_id: uuid.UUID
    title: str
    body: str | None
    published_at: datetime


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reporter_id: uuid.UUID
    base_type_id: uuid.UUID
    title: str
    description: str
    status: ReportStatus
    created_type_id: uuid.UUID | None
    created_at: datetime
    approvals: int = 0
    rejections: int = 0


class VoteIn(BaseModel):
    approve: bool
    comment: str | None = Field(default=None, max_length=2000)


class SemanticHit(BaseModel):
    type: TypeSummary
    score: float


@router.get("/news", response_model=Page[NewsOut])
async def news(
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = SessionDep,
    lang: str = LangDep,
) -> Page[NewsOut]:
    total = (await session.execute(select(func.count()).select_from(NewsItem))).scalar_one()
    rows = (
        await session.scalars(
            select(NewsItem).order_by(NewsItem.published_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    items = [
        NewsOut(
            id=n.id,
            kind=n.kind,
            entity_id=n.entity_id,
            title=n.title_es if lang == "es" else n.title_en,
            body=n.body_es if lang == "es" else n.body_en,
            published_at=n.published_at,
        )
        for n in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/search/semantic", response_model=list[SemanticHit])
async def search_semantic(
    q: str = Query(min_length=2, max_length=200),
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = SessionDep,
    lang: str = LangDep,
) -> list[SemanticHit]:
    """Search by meaning in any language: "moneda con un puente" finds bridges."""
    hits = await semantic_search(session, get_text_embedder(), q, limit)
    summaries = {s.id: s for s in await summaries_for(session, [ct for ct, _ in hits], lang)}
    return [SemanticHit(type=summaries[ct.id], score=score) for ct, score in hits]


@router.post("/reports", response_model=ReportOut, status_code=201)
async def create_report(
    user: CurrentUser,
    base_type_id: Annotated[uuid.UUID, Form()],
    title: Annotated[str, Form(min_length=3, max_length=200)],
    description: Annotated[str, Form(min_length=10, max_length=5000)],
    file: Annotated[UploadFile | None, File()] = None,
    session: AsyncSession = SessionDep,
) -> ReportOut:
    image_path = None
    if file is not None:
        data = await file.read(12 * 1024 * 1024)
        folder = get_settings().data_dir / "reports"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{uuid.uuid4()}.jpg"
        path.write_bytes(data)
        image_path = str(path)
    try:
        report = await submit_report(
            session,
            user,
            base_type_id=base_type_id,
            title=title,
            description=description,
            image_path=image_path,
        )
    except CommunityError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    await session.commit()
    return await _with_votes(session, report)


@router.get("/reports", response_model=list[ReportOut])
async def list_reports(
    status: ReportStatus | None = None, session: AsyncSession = SessionDep
) -> list[ReportOut]:
    stmt = select(ExpertReport).order_by(ExpertReport.created_at.desc()).limit(200)
    if status:
        stmt = stmt.where(ExpertReport.status == status)
    return [await _with_votes(session, r) for r in (await session.scalars(stmt)).all()]


@router.post("/reports/{report_id}/vote", response_model=ReportOut)
async def vote_report(
    report_id: uuid.UUID, body: VoteIn, expert: ExpertUser, session: AsyncSession = SessionDep
) -> ReportOut:
    try:
        report = await vote(session, expert, report_id, approve=body.approve, comment=body.comment)
    except CommunityError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    await session.commit()
    return await _with_votes(session, report)


async def _with_votes(session: AsyncSession, report: ExpertReport) -> ReportOut:
    approvals, rejections = (
        await session.execute(
            select(
                func.count().filter(ExpertVote.approve.is_(True)),
                func.count().filter(ExpertVote.approve.is_(False)),
            ).where(ExpertVote.report_id == report.id)
        )
    ).one()
    out = ReportOut.model_validate(report)
    out.approvals, out.rejections = approvals, rejections
    return out
