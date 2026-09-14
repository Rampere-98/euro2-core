import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.catalog.claims import record_claim, resolve_field
from euro2core.catalog.seed import get_source
from euro2core.catalog.translations import upsert_translation
from euro2core.domain.enums import CoinKind, Finish, ImageSide, VerificationStatus
from euro2core.domain.models import CoinImage, CoinIssue, CoinType, DomainEvent, TextTranslation
from euro2core.images.fetcher import ImageFetcher
from euro2core.sources.ecb.parser import EcbEntry
from euro2core.sources.linker import LINK_THRESHOLD, link_score, match_ecb_entry
from euro2core.sources.numista.parser import NumistaIssue, NumistaPicture, NumistaType

log = logging.getLogger(__name__)


@dataclass
class NumistaIngestResult:
    type_id: uuid.UUID | None
    created: bool = False
    linked_to_ecb: bool = False
    skipped_reason: str | None = None
    issues_created: int = 0
    issues_skipped: int = 0
    base_type_id: uuid.UUID | None = None


async def ingest_numista_type(
    session: AsyncSession,
    ntype: NumistaType,
    issues: Sequence[NumistaIssue],
    *,
    translations: Sequence[NumistaType],
    fetcher: ImageFetcher | None,
) -> NumistaIngestResult:
    source = await get_source(session, "numista")
    result = NumistaIngestResult(type_id=None)

    coin_type = (
        await session.scalars(select(CoinType).where(CoinType.numista_type_id == ntype.id))
    ).first()
    if coin_type is None:
        coin_type, result = await _attach_or_create(session, ntype, result)
        if coin_type is None:
            return result
    result.type_id = coin_type.id

    for name, value in _type_claims(ntype, issues).items():
        if value is None:
            continue
        await record_claim(
            session,
            entity="coin_type",
            entity_id=coin_type.id,
            field=name,
            value=value,
            source=source,
            evidence_url=ntype.url,
        )
        await resolve_field(session, "coin_type", coin_type.id, name, coin_type)

    for localized in (ntype, *translations):
        await upsert_translation(
            session,
            entity="coin_type",
            entity_id=coin_type.id,
            field="description",
            lang=localized.lang,
            text=localized.obverse_description or "",
            source=source,
        )
    if not await _has_translation(session, coin_type.id, "title", "en"):
        await upsert_translation(
            session,
            entity="coin_type",
            entity_id=coin_type.id,
            field="title",
            lang="en",
            text=ntype.title,
            source=source,
        )

    for issue in issues:
        if not 1999 <= issue.year <= 2100:
            if ntype.year != ntype.max_year:
                log.warning(
                    "skipping Numista issue %s of type %s: implausible year %s",
                    issue.id,
                    ntype.id,
                    issue.year,
                )
                result.issues_skipped += 1
                continue
            # Source data error on a single-year type: the type's year is the only sane value
            issue = replace(issue, year=ntype.year)
        created = await _upsert_issue(session, coin_type, issue, source, ntype.url)
        result.issues_created += int(created)

    if fetcher is not None:
        await _store_pictures(session, coin_type, ntype, fetcher)
    await session.flush()
    return result


def _type_claims(ntype: NumistaType, issues: Sequence[NumistaIssue]) -> dict:
    circulation = [i.mintage for i in issues if i.finish == Finish.CIRCULATION and i.mintage]
    return {
        "kind": ntype.kind.value,
        "series": ntype.series,
        "topic": ntype.topic,
        "km_reference": ntype.km_reference,
        "composition": ntype.composition,
        "diameter_mm": ntype.diameter_mm,
        "weight_g": ntype.weight_g,
        "mintage_total": sum(circulation) if circulation else None,
    }


async def _attach_or_create(
    session: AsyncSession, ntype: NumistaType, result: NumistaIngestResult
) -> tuple[CoinType | None, NumistaIngestResult]:
    base_type_id = None
    if ntype.kind == CoinKind.COMMEMORATIVE:
        linked = await _link_to_ecb(session, ntype)
        if linked is not None:
            linked.numista_type_id = ntype.id
            result.linked_to_ecb = True
            return linked, result
    elif ntype.kind == CoinKind.ERROR:
        base_type_id = await _find_base_type(session, ntype)
        if base_type_id is None:
            result.skipped_reason = "error type without an identifiable base coin"
            log.warning(
                "skipping Numista %s (%s): %s", ntype.id, ntype.title, result.skipped_reason
            )
            return None, result
        result.base_type_id = base_type_id
    coin_type = CoinType(
        kind=ntype.kind,
        country_code=ntype.country_code,
        year=ntype.year,
        numista_type_id=ntype.id,
        base_type_id=base_type_id,
        verification_status=VerificationStatus.DOCUMENTED if base_type_id else None,
    )
    session.add(coin_type)
    await session.flush()
    session.add(
        DomainEvent(
            kind="new_type_discovered",
            entity="coin_type",
            entity_id=coin_type.id,
            payload={"source": "numista", "numista_type_id": ntype.id, "title": ntype.title},
        )
    )
    result.created = True
    return coin_type, result


async def _link_to_ecb(session: AsyncSession, ntype: NumistaType) -> CoinType | None:
    rows = (
        await session.execute(
            select(CoinType, TextTranslation.text)
            .join(
                TextTranslation,
                (TextTranslation.entity == "coin_type")
                & (TextTranslation.entity_id == CoinType.id)
                & (TextTranslation.field == "title")
                & (TextTranslation.lang == "en"),
            )
            .where(
                CoinType.country_code == ntype.country_code,
                CoinType.year == ntype.year,
                CoinType.kind == CoinKind.COMMEMORATIVE,
                CoinType.numista_type_id.is_(None),
            )
        )
    ).all()
    candidates = [
        EcbEntry(
            year=ct.year,
            country_code=ct.country_code,
            country_name=ct.country_code,
            feature=title,
            description="",
            mintage=None,
            mintage_raw="",
            issue_date_raw="",
        )
        for ct, title in rows
    ]
    hit, _ = match_ecb_entry(
        country=ntype.country_code,
        year=ntype.year,
        title=ntype.title,
        topic=ntype.topic,
        candidates=candidates,
    )
    if hit is None:
        return None
    return next(ct for ct, title in rows if title == hit.feature)


async def _find_base_type(session: AsyncSession, ntype: NumistaType) -> uuid.UUID | None:
    rows = (
        await session.execute(
            select(CoinType, TextTranslation.text)
            .join(
                TextTranslation,
                (TextTranslation.entity == "coin_type")
                & (TextTranslation.entity_id == CoinType.id)
                & (TextTranslation.field == "title")
                & (TextTranslation.lang == "en"),
            )
            .where(
                CoinType.country_code == ntype.country_code,
                CoinType.year == ntype.year,
                CoinType.kind != CoinKind.ERROR,
            )
        )
    ).all()
    best, best_score = None, 0.0
    for ct, title in rows:
        score = link_score(ntype.title, ntype.topic, title)
        if score > best_score:
            best, best_score = ct, score
    return best.id if best is not None and best_score >= LINK_THRESHOLD else None


async def _upsert_issue(
    session: AsyncSession, coin_type: CoinType, issue: NumistaIssue, source, evidence_url: str
) -> bool:
    row = (
        await session.scalars(select(CoinIssue).where(CoinIssue.numista_issue_id == issue.id))
    ).first()
    created = False
    if row is None:
        row = (
            await session.scalars(
                select(CoinIssue).where(
                    CoinIssue.type_id == coin_type.id,
                    CoinIssue.year == issue.year,
                    CoinIssue.mint_mark == issue.mint_mark,
                    CoinIssue.finish == issue.finish,
                    CoinIssue.packaging == issue.packaging,
                )
            )
        ).first()
    if row is None:
        row = CoinIssue(
            type_id=coin_type.id,
            year=issue.year,
            mint_mark=issue.mint_mark,
            finish=issue.finish,
            packaging=issue.packaging,
        )
        session.add(row)
        created = True
    row.numista_issue_id = issue.id
    await session.flush()
    if issue.mintage is not None:
        await record_claim(
            session,
            entity="coin_issue",
            entity_id=row.id,
            field="mintage",
            value=issue.mintage,
            source=source,
            evidence_url=evidence_url,
        )
        await resolve_field(session, "coin_issue", row.id, "mintage", row)
    return created


async def _has_translation(
    session: AsyncSession, entity_id: uuid.UUID, field: str, lang: str
) -> bool:
    return (
        await session.scalars(
            select(TextTranslation.id).where(
                TextTranslation.entity == "coin_type",
                TextTranslation.entity_id == entity_id,
                TextTranslation.field == field,
                TextTranslation.lang == lang,
            )
        )
    ).first() is not None


async def _store_pictures(
    session: AsyncSession, coin_type: CoinType, ntype: NumistaType, fetcher: ImageFetcher
) -> None:
    folder = f"{coin_type.year}/{coin_type.country_code}/numista-{ntype.id}"
    for side, picture in ((ImageSide.OBVERSE, ntype.obverse), (ImageSide.REVERSE, ntype.reverse)):
        if picture is None:
            continue
        await _store_picture(session, coin_type, side, picture, folder, fetcher)


async def _store_picture(
    session: AsyncSession,
    coin_type: CoinType,
    side: ImageSide,
    picture: NumistaPicture,
    folder: str,
    fetcher: ImageFetcher,
) -> None:
    image = (
        await session.scalars(select(CoinImage).where(CoinImage.source_url == picture.url))
    ).first()
    if image is not None and image.local_path:
        return
    if image is None:
        image = CoinImage(
            type_id=coin_type.id,
            side=side,
            source_url=picture.url,
            license=picture.license,
            author=picture.author,
        )
        session.add(image)
    try:
        stored = await fetcher.fetch(picture.url, folder)
    except Exception as exc:
        # Numista photos sit behind bot protection; keep the attributed reference and retry later
        log.info("photo not downloadable, kept as reference: %s (%s)", picture.url, exc)
        return
    image.local_path = str(stored.local_path)
    image.sha256 = stored.sha256
