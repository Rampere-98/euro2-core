"""Turn catalog domain events into bilingual news items."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.models import CoinIssue, CoinType, DomainEvent, NewsItem, TextTranslation

COUNTRY_ES = {
    "AD": "Andorra",
    "AT": "Austria",
    "BE": "Bélgica",
    "BG": "Bulgaria",
    "CY": "Chipre",
    "DE": "Alemania",
    "EE": "Estonia",
    "ES": "España",
    "FI": "Finlandia",
    "FR": "Francia",
    "GR": "Grecia",
    "HR": "Croacia",
    "IE": "Irlanda",
    "IT": "Italia",
    "LT": "Lituania",
    "LU": "Luxemburgo",
    "LV": "Letonia",
    "MC": "Mónaco",
    "MT": "Malta",
    "NL": "Países Bajos",
    "PT": "Portugal",
    "SI": "Eslovenia",
    "SK": "Eslovaquia",
    "SM": "San Marino",
    "VA": "Vaticano",
}
COUNTRY_EN = {
    "AD": "Andorra",
    "AT": "Austria",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "CY": "Cyprus",
    "DE": "Germany",
    "EE": "Estonia",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GR": "Greece",
    "HR": "Croatia",
    "IE": "Ireland",
    "IT": "Italy",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "MC": "Monaco",
    "MT": "Malta",
    "NL": "Netherlands",
    "PT": "Portugal",
    "SI": "Slovenia",
    "SK": "Slovakia",
    "SM": "San Marino",
    "VA": "Vatican City",
}
NEWSWORTHY = ("new_type_discovered", "fact_revised", "price_spike", "types_merged")


async def publish_pending(session: AsyncSession, limit: int = 500) -> dict[str, int]:
    done = select(NewsItem.event_id).where(NewsItem.event_id.is_not(None))
    events = (
        await session.scalars(
            select(DomainEvent)
            .where(DomainEvent.kind.in_(NEWSWORTHY), DomainEvent.id.not_in(done))
            .order_by(DomainEvent.created_at)
            .limit(limit)
        )
    ).all()
    stats = {"published": 0, "skipped": 0}
    for event in events:
        item = await _render(session, event)
        if item is None:
            stats["skipped"] += 1
            continue
        session.add(item)
        stats["published"] += 1
    await session.flush()
    return stats


async def _coin_context(session: AsyncSession, entity: str, entity_id: uuid.UUID):
    if entity == "coin_issue":
        issue = await session.get(CoinIssue, entity_id)
        if issue is None:
            return None
        coin_type = await session.get(CoinType, issue.type_id)
    else:
        coin_type = await session.get(CoinType, entity_id)
    if coin_type is None:
        return None
    title = await session.scalar(
        select(TextTranslation.text).where(
            TextTranslation.entity == "coin_type",
            TextTranslation.entity_id == coin_type.id,
            TextTranslation.field == "title",
            TextTranslation.lang == "en",
        )
    )
    return coin_type, title or f"{coin_type.country_code} {coin_type.year}"


async def _render(session: AsyncSession, event: DomainEvent) -> NewsItem | None:
    ctx = await _coin_context(session, event.entity, event.entity_id)
    if ctx is None:
        return None
    coin_type, title = ctx
    es_country = COUNTRY_ES.get(coin_type.country_code, coin_type.country_code)
    en_country = COUNTRY_EN.get(coin_type.country_code, coin_type.country_code)
    p = event.payload or {}
    if event.kind == "new_type_discovered":
        source = p.get("source", "catalog")
        title_es = f"Nueva emisión: {es_country} {coin_type.year} — {title}"
        title_en = f"New emission: {en_country} {coin_type.year} — {title}"
        body_es = f"Descubierta en {source.upper()}. Ya está en el catálogo."
        body_en = f"Discovered at {source.upper()}. It is now in the catalog."
    elif event.kind == "fact_revised":
        field = p.get("field", "dato")
        change = f"{p.get('previous')} → {p.get('current')}"
        title_es = f"{es_country} {coin_type.year}: revisión de {field} ({change})"
        title_en = f"{en_country} {coin_type.year}: {field} revised ({change})"
        body_es = f"Una fuente con más autoridad ha corregido {field} de «{title}»."
        body_en = f"A higher-authority source corrected {field} of “{title}”."
    elif event.kind == "price_spike":
        change = float(p.get("change", 0)) * 100
        arrow = "sube" if change > 0 else "baja"
        arrow_en = "up" if change > 0 else "down"
        before, after = p.get("previous_median"), p.get("median")
        title_es = (
            f"{es_country} {coin_type.year} {arrow} un {abs(change):.0f} %: {before} € → {after} €"
        )
        title_en = (
            f"{en_country} {coin_type.year} {arrow_en} {abs(change):.0f}%: €{before} → €{after}"
        )
        grade, n = p.get("grade"), p.get("n_obs")
        body_es = f"Mediana de ventas reales de «{title}» (grado {grade}, {n} ventas)."
        body_en = f"Median of realized sales of “{title}” (grade {grade}, {n} sales)."
    elif event.kind == "types_merged":
        title_es = f"{es_country} {coin_type.year}: ficha unificada de «{title}»"
        title_en = f"{en_country} {coin_type.year}: unified record for “{title}”"
        body_es = (
            "BCE y Numista describían la misma moneda; ahora es una sola ficha con ambas fuentes."
        )
        body_en = "ECB and Numista described the same coin; it is now one record with both sources."
    else:
        return None
    return NewsItem(
        event_id=event.id,
        kind=event.kind,
        entity="coin_type",
        entity_id=coin_type.id,
        title_en=title_en[:300],
        title_es=title_es[:300],
        body_en=body_en,
        body_es=body_es,
        published_at=event.created_at,
    )
