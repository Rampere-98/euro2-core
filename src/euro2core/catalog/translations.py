import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.models import Source, TextTranslation


async def upsert_translation(
    session: AsyncSession,
    *,
    entity: str,
    entity_id: uuid.UUID,
    field: str,
    lang: str,
    text: str,
    source: Source,
) -> bool:
    """Insert or update a translation; a lower-authority source never overwrites a higher one."""
    if not text:
        return False
    row = (
        await session.scalars(
            select(TextTranslation).where(
                TextTranslation.entity == entity,
                TextTranslation.entity_id == entity_id,
                TextTranslation.field == field,
                TextTranslation.lang == lang,
            )
        )
    ).first()
    if row is None:
        session.add(
            TextTranslation(
                entity=entity,
                entity_id=entity_id,
                field=field,
                lang=lang,
                text=text,
                source_id=source.id,
            )
        )
        return True
    if row.text == text:
        return False
    current = await session.get(Source, row.source_id)
    if current is not None and current.authority_rank > source.authority_rank:
        return False
    row.text = text
    row.source_id = source.id
    return True
