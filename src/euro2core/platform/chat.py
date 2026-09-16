"""Answer a user's question from the catalog and market data (see chat_brain for the pure
part). Every answer is built from real rows and says so; nothing is invented."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import CoinKind
from euro2core.domain.models import (
    CoinIssue,
    CoinType,
    NewsItem,
    RarityScore,
    TextTranslation,
    User,
)
from euro2core.platform import market_assistant as ma
from euro2core.platform.chat_brain import (
    CoinHints,
    detect_intent,
    detect_language,
    extract_coin_hints,
    glossary_answer,
)
from euro2core.platform.portfolio import list_items, net_worth
from euro2core.platform.semantic import semantic_search
from euro2core.pricing.market_intel import sell_advice

MAX_CANDIDATES = 3


@dataclass(frozen=True)
class Reply:
    text: str
    intent: str
    lang: str
    type_ids: list[uuid.UUID] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)


_T = {
    "es": {
        "greeting": "¡Hola! Soy el asistente de Euro2. Pregúntame cuánto vale una moneda, si es "
        "rara, dónde comprarla, a cuánto venderla, qué chollos hay o qué significa un término.",
        "help": "Puedo decirte el valor real de una moneda (ventas, no precios pedidos), su "
        "rareza, dónde está en venta ahora, a cuánto vender las tuyas, los chollos del día y "
        "explicarte términos como BU, proof o ceca. Prueba: «¿cuánto vale la de Grace Kelly?».",
        "no_coin": "No he encontrado esa moneda. Dime país y año (por ejemplo «Finlandia 2004») "
        "o el motivo de la moneda.",
        "which": "He encontrado varias; ¿cuál dices?",
        "identify": "Para identificar una moneda usa la pestaña Escanear y hazle una foto a la "
        "cara nacional: la comparo con todo el catálogo en tu propio dispositivo.",
        "howto": "Guía rápida: 1) Escanear → foto → «Es esta» para confirmar. 2) Catálogo → "
        "moneda → «A mi colección». 3) Colección → menú de la pieza → «Verificar con foto» "
        "(recomendado antes de vender). 4) Mercado → Vender → precio sugerido, texto del "
        "anuncio y enlaces a las plazas. 5) «Seguir» en cualquier moneda para recibir chollos "
        "y movimientos.",
        "no_news": "No hay novedades publicadas todavía.",
        "no_bulletin": "Todavía no hay boletín de hoy; se redacta cada mañana.",
        "news": "Últimas novedades:\n{items}",
        "login": "Para eso necesito que inicies sesión (Perfil).",
        "collection": "Tienes {n} piezas. Valor estimado {value} € (coste {cost} €, "
        "{gain_sign}{gain} €). Por base: {bases}.",
        "collection_empty": "Tu colección está vacía. Escanea una moneda o añádela desde el "
        "catálogo.",
        "no_deals": "Ahora mismo no hay chollos fiables. Sigue tus monedas favoritas y te aviso "
        "en cuanto aparezca uno.",
        "deals": "Chollos de hoy (anuncios fiables ≥ 15 % por debajo de las ventas "
        "reales):\n{items}",
        "value": "{title} ({country} {year}): ventas reales {rmin}–{rmax} € (mediana {median} €, "
        "{n} ventas en {days} días). Rango justo {low}–{high} €.{trend}{offer}",
        "value_catalog": "{title} ({country} {year}): sin ventas reales registradas; valor de "
        "catálogo aproximado {low}–{high} €.{offer}",
        "value_model": "{title} ({country} {year}): sin ventas registradas todavía; por su tirada "
        "({mintage}) estimo {low}–{high} €. Es una estimación propia, no un precio de mercado."
        "{offer}",
        "value_face": "{title} ({country} {year}): sin ventas ni valor de catálogo todavía; hoy "
        "su referencia es el valor facial (2 €).{offer}",
        "trend_up": " Tendencia: +{t} % en 90 días.",
        "trend_down": " Tendencia: {t} % en 90 días.",
        "offer_buy": " Oferta más barata ahora: {price} € en {market} ({verdict}).",
        "verdict_buy_now": "buen precio",
        "verdict_fair": "precio justo",
        "verdict_overpriced": "cara",
        "verdict_wait": "mejor esperar",
        "rarity": "{title} ({country} {year}): rareza {tier} ({score}/100). Tirada {mintage}. "
        "{variants}",
        "rarity_variants": "Tiene {n} variantes (ceca/acabado); la más rara es {best}.",
        "rarity_unknown": "{title}: todavía no tengo índice de rareza (falta la tirada o el "
        "mercado).",
        "buy": "{title}: {n} anuncios fiables ahora, desde {min} € hasta {max} €. Rango justo "
        "{low}–{high} €. {verdict_line}",
        "buy_none": "{title}: no hay anuncios fiables activos ahora mismo. Pulsa «Seguir» en la "
        "moneda y te aviso cuando aparezca uno a buen precio.",
        "sell_no_item": "No tienes esa moneda en tu colección. Añádela y te diré a cuánto "
        "venderla.",
        "sell": "Para vender tu {title} ({grade}): pide {start} €, no bajes de {floor} €. "
        "Neto en eBay ≈ {net_ebay} € tras comisiones; en venta directa {net_here} €. {days}{hold}",
        "sell_days": "Suele tardar ~{d} días en venderse. ",
        "sell_hold": "Está subiendo: si no tienes prisa, espera.",
        "sell_all": "Tus piezas con más valor de venta:\n{items}",
        "glossary_none": "No conozco ese término. Prueba con BU, proof, coincard, ceca, "
        "Sheldon, tirada, emisión conjunta, error, coloreada, rareza o comisión.",
    },
    "en": {
        "greeting": "Hi! I'm the Euro2 assistant. Ask me what a coin is worth, whether it is "
        "rare, where to buy it, what to ask when selling, today's deals, or what a term means.",
        "help": "I can tell you a coin's real value (sales, not asking prices), its rarity, "
        "where it is for sale now, what to ask for yours, today's deals, and explain terms "
        "like BU, proof or mint mark. Try: 'how much is the Grace Kelly coin worth?'.",
        "no_coin": "I couldn't find that coin. Give me country and year (e.g. 'Finland 2004') "
        "or the coin's theme.",
        "which": "I found several; which one do you mean?",
        "identify": "To identify a coin use the Scan tab and photograph the national side: it "
        "is matched against the whole catalog on your own device.",
        "howto": "Quick guide: 1) Scan → photo → 'Es esta' to confirm. 2) Catalog → coin → add "
        "to collection. 3) Collection → piece menu → verify with a photo (recommended before "
        "selling). "
        "4) Market → Sell → suggested price, listing text and marketplace links. 5) 'Follow' "
        "any coin to be told about deals and price moves.",
        "no_news": "No news published yet.",
        "no_bulletin": "No bulletin yet today; it is written every morning.",
        "news": "Latest news:\n{items}",
        "login": "You need to sign in for that (Profile).",
        "collection": "You own {n} pieces. Estimated value €{value} (cost €{cost}, "
        "{gain_sign}€{gain}). By basis: {bases}.",
        "collection_empty": "Your collection is empty. Scan a coin or add one from the catalog.",
        "no_deals": "No reliable bargains right now. Follow your favourite coins and I'll tell "
        "you as soon as one appears.",
        "deals": "Today's deals (reliable listings ≥ 15% below real sales):\n{items}",
        "value": "{title} ({country} {year}): real sales €{rmin}–{rmax} (median €{median}, {n} "
        "sales in {days} days). Fair band €{low}–{high}.{trend}{offer}",
        "value_catalog": "{title} ({country} {year}): no real sales on record; approximate "
        "catalog value €{low}–{high}.{offer}",
        "value_model": "{title} ({country} {year}): no recorded sales yet; from its mintage "
        "({mintage}) I estimate €{low}–{high}. An in-app estimate, not a market price.{offer}",
        "value_face": "{title} ({country} {year}): no sales or catalog value yet; today its "
        "reference is face value (€2).{offer}",
        "trend_up": " Trend: +{t}% over 90 days.",
        "trend_down": " Trend: {t}% over 90 days.",
        "offer_buy": " Cheapest offer now: €{price} on {market} ({verdict}).",
        "verdict_buy_now": "good price",
        "verdict_fair": "fair price",
        "verdict_overpriced": "overpriced",
        "verdict_wait": "better wait",
        "rarity": "{title} ({country} {year}): rarity {tier} ({score}/100). Mintage {mintage}. "
        "{variants}",
        "rarity_variants": "It has {n} variants (mint/finish); the rarest is {best}.",
        "rarity_unknown": "{title}: no rarity index yet (mintage or market data missing).",
        "buy": "{title}: {n} reliable listings now, from €{min} to €{max}. Fair band "
        "€{low}–{high}. {verdict_line}",
        "buy_none": "{title}: no reliable listings active right now. Follow the coin and I'll "
        "tell you when one appears at a good price.",
        "sell_no_item": "That coin is not in your collection. Add it and I'll tell you what to "
        "ask.",
        "sell": "To sell your {title} ({grade}): ask €{start}, don't go below €{floor}. Net "
        "on eBay ≈ €{net_ebay} after fees; sold directly €{net_here}. {days}{hold}",
        "sell_days": "It usually takes ~{d} days to sell. ",
        "sell_hold": "It is rising: if you're not in a hurry, wait.",
        "sell_all": "Your pieces with the highest sale value:\n{items}",
        "glossary_none": "I don't know that term. Try BU, proof, coincard, mint mark, Sheldon, "
        "mintage, joint issue, error, coloured, rarity or fees.",
    },
}

TIER_ES = {
    "common": "común",
    "uncommon": "poco común",
    "rare": "rara",
    "very_rare": "muy rara",
    "exceptional": "excepcional",
}
GRADE_ES = {
    "unknown": "sin grado",
    "circulated": "circulada",
    "unc": "sin circular",
    "bu": "BU",
    "proof": "proof",
}
COUNTRY_ES = {
    "AD": "Andorra", "AT": "Austria", "BE": "Bélgica", "BG": "Bulgaria", "CY": "Chipre",
    "DE": "Alemania", "EE": "Estonia", "ES": "España", "FI": "Finlandia", "FR": "Francia",
    "GR": "Grecia", "HR": "Croacia", "IE": "Irlanda", "IT": "Italia", "LT": "Lituania",
    "LU": "Luxemburgo", "LV": "Letonia", "MC": "Mónaco", "MT": "Malta", "NL": "Países Bajos",
    "PT": "Portugal", "SI": "Eslovenia", "SK": "Eslovaquia", "SM": "San Marino", "VA": "Vaticano",
}  # fmt: skip


def _fmt(n) -> str:
    return f"{n:,}".replace(",", ".") if isinstance(n, int) else "—"


async def _title(session: AsyncSession, type_id: uuid.UUID, lang: str) -> str:
    for candidate in (lang, "en", "es"):
        text = await session.scalar(
            select(TextTranslation.text).where(
                TextTranslation.entity == "coin_type",
                TextTranslation.entity_id == type_id,
                TextTranslation.field == "title",
                TextTranslation.lang == candidate,
            )
        )
        if text:
            return text
    return "2 €"


async def _find_coins(
    session: AsyncSession, hints: CoinHints, embedder, lang: str
) -> list[CoinType]:
    """Country + year narrow the catalog; the free text picks within it (semantic index when
    available, title match otherwise)."""
    stmt = select(CoinType).where(CoinType.kind != CoinKind.ERROR)
    if hints.country_code:
        stmt = stmt.where(CoinType.country_code == hints.country_code)
    if hints.year:
        stmt = stmt.where(CoinType.year == hints.year)
    narrowed = list((await session.scalars(stmt.limit(200))).all())
    if hints.query and embedder is not None:
        hits = await semantic_search(session, embedder, hints.raw or hints.query, limit=10)
        allowed = {t.id for t in narrowed} if (hints.country_code or hints.year) else None
        ranked = [
            ct for ct, score in hits if score >= 0.80 and (allowed is None or ct.id in allowed)
        ]
        if ranked:
            return ranked[:MAX_CANDIDATES]
    if hints.query:
        pattern = f"%{hints.query.split()[0]}%"
        ids = set(
            (
                await session.scalars(
                    select(TextTranslation.entity_id).where(
                        TextTranslation.entity == "coin_type",
                        TextTranslation.field == "title",
                        func.unaccent(TextTranslation.text).ilike(func.unaccent(pattern)),
                    )
                )
            ).all()
        )
        by_title = (
            [t for t in narrowed if t.id in ids]
            if narrowed and (hints.country_code or hints.year)
            else None
        )
        if by_title is None and ids:
            by_title = list(
                (
                    await session.scalars(
                        select(CoinType).where(CoinType.id.in_(ids)).limit(MAX_CANDIDATES)
                    )
                ).all()
            )
        if by_title:
            return by_title[:MAX_CANDIDATES]
    if hints.country_code and hints.year:
        return narrowed[:MAX_CANDIDATES]
    return []


async def answer(
    session: AsyncSession,
    message: str,
    *,
    embedder,
    user: User | None = None,
    type_id: uuid.UUID | None = None,
    lang: str | None = None,
) -> Reply:
    lang = lang or detect_language(message)
    t = _T[lang]
    intent = detect_intent(message, embedder=embedder).intent

    if intent == "greeting":
        return Reply(t["greeting"], intent, lang, suggestions=_suggestions(lang))
    if intent == "help":
        return Reply(t["help"], intent, lang, suggestions=_suggestions(lang))
    if intent == "identify":
        return Reply(t["identify"], intent, lang)
    if intent == "howto":
        return Reply(t["howto"], intent, lang)
    if intent == "glossary":
        return Reply(glossary_answer(message, lang) or t["glossary_none"], intent, lang)
    if intent == "bulletin":
        item = await session.scalar(
            select(NewsItem)
            .where(NewsItem.kind == "bulletin")
            .order_by(NewsItem.published_at.desc())
            .limit(1)
        )
        if item is None:
            return Reply(t["no_bulletin"], intent, lang)
        text = (item.title_es if lang == "es" else item.title_en) + "\n\n"
        text += (item.body_es if lang == "es" else item.body_en) or ""
        return Reply(text, intent, lang)
    if intent == "news":
        rows = (
            await session.scalars(select(NewsItem).order_by(NewsItem.published_at.desc()).limit(5))
        ).all()
        if not rows:
            return Reply(t["no_news"], intent, lang)
        items = "\n".join(f"• {(n.title_es if lang == 'es' else n.title_en)}" for n in rows)
        return Reply(
            t["news"].format(items=items), intent, lang, type_ids=[n.entity_id for n in rows]
        )
    if intent == "deals":
        found = await ma.deals(session, limit=5)
        if not found:
            return Reply(t["no_deals"], intent, lang)
        lines, links = [], []
        for d in found:
            title = await _title(session, d.coin_type.id, lang)
            lines.append(
                f"• {title} ({d.coin_type.country_code} {d.coin_type.year}): "
                f"{d.listing.price} € (−{d.discount_pct:.0f} %, {d.listing.marketplace})"
            )
            links.append({"label": title, "url": d.listing.url})
        return Reply(
            t["deals"].format(items="\n".join(lines)),
            intent,
            lang,
            type_ids=[d.coin_type.id for d in found],
            links=links,
        )
    if intent == "collection":
        if user is None:
            return Reply(t["login"], intent, lang)
        valued = await list_items(session, user.id)
        if not valued:
            return Reply(t["collection_empty"], intent, lang)
        worth = net_worth(valued)
        gain = worth["gain"]
        bases = ", ".join(f"{k} {v} €" for k, v in worth["value_by_basis"].items())
        return Reply(
            t["collection"].format(
                n=worth["pieces"],
                value=worth["value"],
                cost=worth["cost"],
                gain_sign="+" if gain >= 0 else "",
                gain=gain,
                bases=bases,
            ),
            intent,
            lang,
        )

    # coin-centric intents ------------------------------------------------
    hints = extract_coin_hints(message)
    coins: list[CoinType] = []
    if type_id is not None and not (hints.country_code or hints.year or hints.query):
        ct = await session.get(CoinType, type_id)
        coins = [ct] if ct else []
    if not coins:
        coins = await _find_coins(session, hints, embedder, lang)

    if intent == "sell":
        if user is None:
            return Reply(t["login"], intent, lang)
        return await _sell(session, t, lang, user, coins)
    if not coins:
        return Reply(t["no_coin"], intent, lang)
    if len(coins) > 1:
        titles = [await _title(session, c.id, lang) for c in coins]
        listing = "\n".join(
            f"• {ti} ({c.country_code} {c.year})" for ti, c in zip(titles, coins, strict=True)
        )
        return Reply(f"{t['which']}\n{listing}", intent, lang, type_ids=[c.id for c in coins])
    coin = coins[0]
    title = await _title(session, coin.id, lang)
    country = (
        COUNTRY_ES.get(coin.country_code, coin.country_code) if lang == "es" else coin.country_code
    )
    if intent == "rarity":
        return await _rarity(session, t, lang, coin, title, country)
    market = await ma.market_for_type(session, coin)
    if intent == "buy":
        return _buy(t, lang, coin, title, market)
    return _value(t, lang, coin, title, country, market)


def _suggestions(lang: str) -> list[str]:
    return (
        [
            "¿Cuánto vale la de Grace Kelly?",
            "¿Hay chollos hoy?",
            "¿Qué significa BU?",
            "¿Cómo vendo una moneda?",
        ]
        if lang == "es"
        else [
            "How much is the Grace Kelly coin worth?",
            "Any deals today?",
            "What is BU?",
            "How do I sell?",
        ]
    )


def _verdict_word(t: dict, verdict: str) -> str:
    return t.get(f"verdict_{verdict}", verdict)


def _value(t, lang, coin, title, country, market: ma.TypeMarket) -> Reply:
    s = market.snapshot
    offer = ""
    if market.buy.cheapest is not None:
        offer = t["offer_buy"].format(
            price=market.buy.cheapest.price,
            market=market.buy.cheapest.marketplace,
            verdict=_verdict_word(t, market.buy.verdict),
        )
    links = [{"label": title, "url": market.buy.cheapest.url}] if market.buy.cheapest else []
    if s.realized is not None:
        trend = ""
        if s.trend_pct is not None:
            trend = (t["trend_up"] if s.trend_pct >= 0 else t["trend_down"]).format(
                t=f"{s.trend_pct:.0f}"
            )
        text = t["value"].format(
            title=title,
            country=country,
            year=coin.year,
            rmin=s.realized.min,
            rmax=s.realized.max,
            median=s.realized.median,
            n=s.realized.n,
            days=s.realized.window_days,
            low=s.band.low,
            high=s.band.high,
            trend=trend,
            offer=offer,
        )
    elif s.band.basis == "catalog":
        text = t["value_catalog"].format(
            title=title,
            country=country,
            year=coin.year,
            low=s.band.low,
            high=s.band.high,
            offer=offer,
        )
    elif s.band.basis == "mintage_model":
        text = t["value_model"].format(
            title=title,
            country=country,
            year=coin.year,
            low=s.band.low,
            high=s.band.high,
            mintage=_fmt(coin.mintage_total),
            offer=offer,
        )
    else:
        text = t["value_face"].format(title=title, country=country, year=coin.year, offer=offer)
    return Reply(text, "value", lang, type_ids=[coin.id], links=links)


def _buy(t, lang, coin, title, market: ma.TypeMarket) -> Reply:
    s = market.snapshot
    if not s.offers:
        return Reply(t["buy_none"].format(title=title), "buy", lang, type_ids=[coin.id])
    prices = [o.listing.price for o in s.offers]
    verdict_line = (
        t["offer_buy"]
        .format(
            price=market.buy.cheapest.price,
            market=market.buy.cheapest.marketplace,
            verdict=_verdict_word(t, market.buy.verdict),
        )
        .strip()
    )
    links = [
        {"label": f"{o.listing.price} € · {o.listing.marketplace}", "url": o.listing.url}
        for o in s.offers[:5]
    ]
    return Reply(
        t["buy"].format(
            title=title,
            n=len(prices),
            min=min(prices),
            max=max(prices),
            low=s.band.low,
            high=s.band.high,
            verdict_line=verdict_line,
        ),
        "buy",
        lang,
        type_ids=[coin.id],
        links=links,
    )


async def _rarity(session, t, lang, coin, title, country) -> Reply:
    rows = (
        await session.execute(
            select(RarityScore, CoinIssue)
            .join(CoinIssue, CoinIssue.id == RarityScore.issue_id)
            .where(CoinIssue.type_id == coin.id)
            .order_by(RarityScore.score.desc())
        )
    ).all()
    if not rows:
        return Reply(t["rarity_unknown"].format(title=title), "rarity", lang, type_ids=[coin.id])
    best_score, best_issue = rows[0]
    variants = ""
    if len(rows) > 1:
        label = " ".join(
            x for x in (best_issue.mint_mark, best_issue.finish.value, str(best_issue.year)) if x
        )
        variants = t["rarity_variants"].format(
            n=len(rows), best=f"{label} ({best_score.score:.0f}/100)"
        )
    # the plainest variant's score describes the coin most people hold
    typical = min(rows, key=lambda r: r[0].score)[0]
    return Reply(
        t["rarity"]
        .format(
            title=title,
            country=country,
            year=coin.year,
            tier=TIER_ES.get(typical.tier, typical.tier) if lang == "es" else typical.tier,
            score=f"{typical.score:.0f}",
            mintage=_fmt(coin.mintage_total),
            variants=variants,
        )
        .replace("  ", " "),
        "rarity",
        lang,
        type_ids=[coin.id],
    )


async def _sell(session, t, lang, user, coins: list[CoinType]) -> Reply:
    valued = await list_items(session, user.id)
    if coins:
        wanted = {c.id for c in coins}
        issue_ids = set(
            (await session.scalars(select(CoinIssue.id).where(CoinIssue.type_id.in_(wanted)))).all()
        )
        mine = [v for v in valued if v.item.issue_id in issue_ids]
        if not mine:
            return Reply(t["sell_no_item"], "sell", lang, type_ids=list(wanted))
        v = mine[0]
        issue = await session.get(CoinIssue, v.item.issue_id)
        coin = await session.get(CoinType, issue.type_id)
        market = await ma.market_for_type(session, coin)
        advice = sell_advice(market.snapshot, grade=v.item.grade)
        title = await _title(session, coin.id, lang)
        grade = (
            GRADE_ES.get(v.item.grade.value, v.item.grade.value)
            if lang == "es"
            else v.item.grade.value
        )
        days = t["sell_days"].format(d=advice.expected_days) if advice.expected_days else ""
        return Reply(
            t["sell"]
            .format(
                title=title,
                grade=grade,
                start=advice.start,
                floor=advice.floor,
                net_here=advice.net_euro2,
                net_ebay=advice.net_ebay,
                days=days,
                hold=t["sell_hold"] if advice.hold else "",
            )
            .strip(),
            "sell",
            lang,
            type_ids=[coin.id],
        )
    if not valued:
        return Reply(t["collection_empty"], "sell", lang)
    top = sorted(valued, key=lambda v: v.valuation.value, reverse=True)[:5]
    lines = []
    ids = []
    for v in top:
        issue = await session.get(CoinIssue, v.item.issue_id)
        title = await _title(session, issue.type_id, lang)
        ids.append(issue.type_id)
        lines.append(f"• {title}: {v.valuation.value} € ({v.valuation.basis})")
    return Reply(t["sell_all"].format(items="\n".join(lines)), "sell", lang, type_ids=ids)
