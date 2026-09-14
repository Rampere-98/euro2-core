import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.catalog.claims import record_claim, resolve_field
from euro2core.catalog.issues import ensure_placeholder_issue
from euro2core.catalog.seed import get_source
from euro2core.domain.enums import CoinKind, ImageSide
from euro2core.domain.models import CoinImage, CoinType, DomainEvent, TextTranslation
from euro2core.images.fetcher import ImageFetcher
from euro2core.sources.ecb.parser import EcbEntry, slugify

log = logging.getLogger(__name__)

ECB_IMAGE_AUTHOR = "European Central Bank"
ECB_IMAGE_LICENSE = "ECB copyright; reproduction permitted with attribution"


@dataclass
class IngestStats:
    types_created: int = 0
    types_seen: int = 0
    claims_added: int = 0
    images_stored: int = 0
    images_failed: int = 0
    errors: list[str] = field(default_factory=list)


async def ingest_ecb_entries(
    session: AsyncSession, entries: Sequence[EcbEntry], fetcher: ImageFetcher | None
) -> IngestStats:
    source = await get_source(session, "ecb")
    stats = IngestStats()
    for entry in entries:
        stats.types_seen += 1
        coin_type, created = await _get_or_create_type(session, entry)
        if created:
            stats.types_created += 1
        await ensure_placeholder_issue(session, coin_type)
        claims = {
            "kind": CoinKind.COMMEMORATIVE.value,
            "title": entry.feature,
            "description": entry.description,
            "issue_date_raw": entry.issue_date_raw,
            "joint_issue_group": entry.joint_issue_group,
        }
        if entry.mintage is not None:
            claims["mintage_total"] = entry.mintage
        page_url = f"https://www.ecb.europa.eu/euro/coins/comm/html/comm_{entry.year}.en.html"
        for name, value in claims.items():
            if value is None:
                continue
            if await record_claim(
                session,
                entity="coin_type",
                entity_id=coin_type.id,
                field=name,
                value=value,
                source=source,
                evidence_url=page_url,
            ):
                stats.claims_added += 1
            await resolve_field(session, "coin_type", coin_type.id, name, coin_type)
        await _upsert_translation(session, coin_type, "title", entry.feature, source.id)
        await _upsert_translation(session, coin_type, "description", entry.description, source.id)
        if fetcher is not None:
            await _store_images(session, coin_type, entry, fetcher, stats)
    await session.flush()
    return stats


async def _get_or_create_type(session: AsyncSession, entry: EcbEntry) -> tuple[CoinType, bool]:
    existing = (
        await session.scalars(select(CoinType).where(CoinType.ecb_ref == entry.ecb_ref))
    ).first()
    if existing is not None:
        return existing, False
    coin_type = CoinType(
        kind=CoinKind.COMMEMORATIVE,
        country_code=entry.country_code,
        year=entry.year,
        ecb_ref=entry.ecb_ref,
        joint_issue_group=entry.joint_issue_group,
    )
    session.add(coin_type)
    await session.flush()
    session.add(
        DomainEvent(
            kind="new_type_discovered",
            entity="coin_type",
            entity_id=coin_type.id,
            payload={"source": "ecb", "ecb_ref": entry.ecb_ref, "feature": entry.feature},
        )
    )
    return coin_type, True


async def _upsert_translation(
    session: AsyncSession, coin_type: CoinType, field_name: str, text: str, source_id
) -> None:
    row = (
        await session.scalars(
            select(TextTranslation).where(
                TextTranslation.entity == "coin_type",
                TextTranslation.entity_id == coin_type.id,
                TextTranslation.field == field_name,
                TextTranslation.lang == "en",
            )
        )
    ).first()
    if row is None:
        session.add(
            TextTranslation(
                entity="coin_type",
                entity_id=coin_type.id,
                field=field_name,
                lang="en",
                text=text,
                source_id=source_id,
            )
        )
    elif row.text != text:
        row.text = text
        row.source_id = source_id


async def _store_images(
    session: AsyncSession,
    coin_type: CoinType,
    entry: EcbEntry,
    fetcher: ImageFetcher,
    stats: IngestStats,
) -> None:
    folder = f"{entry.year}/{entry.country_code}/{slugify(entry.feature, max_words=6)}"
    for url in entry.image_urls:
        existing = (
            await session.scalars(select(CoinImage).where(CoinImage.source_url == url))
        ).first()
        if existing is not None:
            continue
        try:
            stored = await fetcher.fetch(url, folder)
        except Exception as exc:  # network or content problems must not abort the catalog sync
            stats.images_failed += 1
            stats.errors.append(f"{url}: {exc}")
            log.warning("image fetch failed for %s: %s", url, exc)
            continue
        session.add(
            CoinImage(
                type_id=coin_type.id,
                side=ImageSide.OBVERSE,
                local_path=str(stored.local_path),
                source_url=url,
                license=ECB_IMAGE_LICENSE,
                author=ECB_IMAGE_AUTHOR,
                sha256=stored.sha256,
            )
        )
        stats.images_stored += 1
