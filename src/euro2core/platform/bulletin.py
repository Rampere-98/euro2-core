"""The daily market bulletin: a short article the assistant writes every morning from what the
database saw in the last 24 hours. Templated Spanish and English, no external service, one
per day (running it again the same day returns the same item)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import ObservationKind
from euro2core.domain.models import (
    CoinIssue,
    CoinType,
    MarketObservation,
    NewsItem,
    Notification,
    TextTranslation,
    User,
)
from euro2core.platform import market_assistant as ma
from euro2core.platform.news import COUNTRY_EN, COUNTRY_ES

KIND = "bulletin"
REALIZED = (ObservationKind.SOLD, ObservationKind.AUCTION_CLOSED)
MARKETPLACE_ES = {
    "EBAY_ES": "eBay España",
    "EBAY_DE": "eBay Alemania",
    "EBAY_FR": "eBay Francia",
    "EBAY_IT": "eBay Italia",
    "EBAY_NL": "eBay Países Bajos",
    "EBAY_AT": "eBay Austria",
    "EURO2_USER": "compras de coleccionistas",
    "WEB": "tiendas web",
}
MARKETPLACE_EN = {
    "EBAY_ES": "eBay Spain",
    "EBAY_DE": "eBay Germany",
    "EBAY_FR": "eBay France",
    "EBAY_IT": "eBay Italy",
    "EBAY_NL": "eBay Netherlands",
    "EBAY_AT": "eBay Austria",
    "EURO2_USER": "collectors' purchases",
    "WEB": "web shops",
}
MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]  # fmt: skip


def _eur(x: Decimal | float, lang: str) -> str:
    v = f"{Decimal(x):.2f}"
    return v.replace(".", ",") + " €" if lang == "es" else "€" + v


def _day_id(day: datetime) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"euro2://bulletin/{day.date().isoformat()}")


async def _titles(session: AsyncSession, type_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    if not type_ids:
        return {}
    rows = (
        await session.execute(
            select(TextTranslation.entity_id, TextTranslation.lang, TextTranslation.text).where(
                TextTranslation.entity == "coin_type",
                TextTranslation.entity_id.in_(type_ids),
                TextTranslation.field == "title",
            )
        )
    ).all()
    out: dict[uuid.UUID, dict] = {}
    for entity_id, lang, text in rows:
        out.setdefault(entity_id, {})[lang] = text
    return out


def _name(coin_type: CoinType, titles: dict, lang: str) -> str:
    t = titles.get(coin_type.id, {})
    title = t.get(lang) or t.get("en") or t.get("es") or ""
    country = (COUNTRY_ES if lang == "es" else COUNTRY_EN).get(
        coin_type.country_code, coin_type.country_code
    )
    return f"{title} ({country} {coin_type.year})" if title else f"{country} {coin_type.year}"


async def write_bulletin(session: AsyncSession, *, now: datetime | None = None) -> NewsItem | None:
    """Write (or return) today's bulletin and notify every user once."""
    now = now or datetime.now(UTC)
    entity_id = _day_id(now)
    existing = await session.scalar(select(NewsItem).where(NewsItem.entity_id == entity_id))
    if existing is not None:
        return existing

    since = now - timedelta(days=1)
    sales = (
        await session.execute(
            select(MarketObservation, CoinType)
            .join(CoinIssue, CoinIssue.id == MarketObservation.issue_id)
            .join(CoinType, CoinType.id == CoinIssue.type_id)
            .where(
                MarketObservation.observation_kind.in_(REALIZED),
                MarketObservation.observed_at >= since,
                MarketObservation.is_outlier.is_(False),
            )
            .order_by(MarketObservation.price.desc())
            .limit(5)
        )
    ).all()
    sales_week = await session.scalar(
        select(func.count())
        .select_from(MarketObservation)
        .where(
            MarketObservation.observation_kind.in_(REALIZED),
            MarketObservation.observed_at >= now - timedelta(days=7),
        )
    )
    new_types = (
        await session.scalars(
            select(CoinType)
            .where(CoinType.created_at >= since, CoinType.base_type_id.is_(None))
            .order_by(CoinType.year.desc())
            .limit(5)
        )
    ).all()
    movers = await ma.movers(session, limit=5, now=now)
    deals = await ma.deals(session, limit=5, now=now)
    record = (
        await session.execute(
            select(MarketObservation, CoinType)
            .join(CoinIssue, CoinIssue.id == MarketObservation.issue_id)
            .join(CoinType, CoinType.id == CoinIssue.type_id)
            .where(
                MarketObservation.observation_kind.in_(REALIZED),
                MarketObservation.observed_at >= now - timedelta(days=30),
                MarketObservation.is_outlier.is_(False),
            )
            .order_by(MarketObservation.price.desc())
            .limit(1)
        )
    ).first()

    type_ids = list(
        {
            *[t.id for _, t in sales],
            *[t.id for t in new_types],
            *[m.coin_type.id for m in movers],
            *[d.coin_type.id for d in deals],
            *([record[1].id] if record else []),
        }
    )
    titles = await _titles(session, type_ids)

    bodies = {}
    for lang in ("es", "en"):
        bodies[lang] = _compose(
            lang,
            now,
            sales=sales,
            sales_week=int(sales_week or 0),
            new_types=list(new_types),
            movers=movers,
            deals=deals,
            record=record,
            titles=titles,
        )
    title_es = f"Boletín del mercado · {now.day} de {MONTHS_ES[now.month - 1]} de {now.year}"
    title_en = f"Market bulletin · {now:%d %B %Y}"
    item = NewsItem(
        kind=KIND,
        entity="market",
        entity_id=entity_id,
        title_es=title_es,
        title_en=title_en,
        body_es=bodies["es"],
        body_en=bodies["en"],
        published_at=now,
    )
    session.add(item)
    for user_id in await session.scalars(select(User.id)):
        session.add(
            Notification(
                user_id=user_id,
                kind=KIND,
                title=title_es,
                body=bodies["es"].split("\n", 1)[0][:200],
                payload={"news_id": None, "entity_id": str(entity_id)},
            )
        )
    await session.flush()
    return item


NL = "\n"


def _compose(
    lang: str, now: datetime, *, sales, sales_week, new_types, movers, deals, record, titles
) -> str:
    es = lang == "es"
    mk = MARKETPLACE_ES if es else MARKETPLACE_EN

    def t(spanish: str, english: str) -> str:
        return spanish if es else english

    def name(coin_type: CoinType) -> str:
        return _name(coin_type, titles, lang)

    def where(marketplace: str) -> str:
        return mk.get(marketplace, marketplace)

    def section(head: str, *parts: str) -> str:
        return head + NL + NL.join(p for p in parts if p)

    sections: list[str] = []

    if movers:
        lines = []
        for m in movers:
            up = m.trend_pct >= 0
            cause = t(
                "ventas recientes por encima de la mediana" if up else "ventas recientes más bajas",
                "recent sales above the median" if up else "recent sales below the median",
            )
            median = (
                f"{_eur(m.median, lang)} {t('de mediana', 'median')}, {m.n} {t('ventas', 'sales')}"
            )
            arrow = "▲" if up else "▼"
            lines.append(f"{arrow} {name(m.coin_type)}: {m.trend_pct:+.0f} % ({median}; {cause})")
        why = t(
            "Por qué importa: una tendencia sostenida cambia el precio de salida al vender.",
            "Why it matters: a sustained trend changes the sensible asking price when selling.",
        )
        sections.append(section(t("Lo más movido", "Movers"), NL.join(lines), why))

    if sales:
        lines = [
            f"• {_eur(obs.price, lang)} — {name(ct)} · {where(obs.marketplace)}"
            for obs, ct in sales
        ]
        intro = t(
            "Las ventas más altas registradas en las últimas 24 horas:",
            "The highest sales recorded in the last 24 hours:",
        )
        sections.append(section(t("Ventas destacadas", "Notable sales"), intro, NL.join(lines)))

    if deals:
        lines = [
            f"• {name(d.coin_type)}: {_eur(d.listing.price, lang)} (−{d.discount_pct:.0f} % "
            f"{t('bajo el rango de ventas reales', 'below real sales')}, "
            f"{where(d.listing.marketplace)})"
            for d in deals
        ]
        sections.append(section(t("Chollos nuevos", "New bargains"), NL.join(lines)))

    if new_types:
        lines = [f"• {name(ct)}" for ct in new_types]
        intro = t("Diseños incorporados al catálogo:", "Designs added to the catalog:")
        sections.append(section(t("Novedades del BCE", "ECB news"), intro, NL.join(lines)))

    if record:
        obs, ct = record
        text = t(
            f"La venta más alta de los últimos 30 días: {_eur(obs.price, lang)} por {name(ct)} "
            f"en {where(obs.marketplace)}.",
            f"Highest sale of the last 30 days: {_eur(obs.price, lang)} for {name(ct)} "
            f"on {where(obs.marketplace)}.",
        )
        sections.append(section(t("Récord del mes", "Record of the month"), text))

    sections.append(
        section(
            t("Cifra del día", "Figure of the day"),
            t(
                f"{sales_week} ventas reales registradas en los últimos 7 días.",
                f"{sales_week} real sales recorded in the last 7 days.",
            ),
        )
    )

    if len(sections) == 1:  # only the figure: a quiet day
        lead = t(
            "Mercado tranquilo: sin ventas destacadas, chollos ni novedades en 24 horas.",
            "A quiet market: no notable sales, bargains or news in the last 24 hours.",
        )
    else:
        n = len(sections) - 1
        lead = t(
            f"Resumen de las últimas 24 horas en el mercado de las monedas de 2 €: "
            f"{n} {'apartado' if n == 1 else 'apartados'} con novedades.",
            f"The last 24 hours in the 2 euro coin market: "
            f"{n} {'section' if n == 1 else 'sections'} with news.",
        )
    return lead + NL + NL + (NL + NL).join(sections)
