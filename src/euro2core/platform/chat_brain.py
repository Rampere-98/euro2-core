# ruff: noqa: SIM905  (word lists are kept as text blocks for readability)
"""The app's own assistant: understands a question about 2 euro coins and answers from the
catalog and the market data it already holds. No external service is involved — intent is
decided by rules first and by the local multilingual embedder (e5) when the rules are unsure;
coins are found with the same local semantic index the search uses.

This module is the pure part (language, intent, entities, glossary); `chat.py` fetches data.
"""

import re
from dataclasses import dataclass, field

import numpy as np

from euro2core.pricing import vocabulary as V
from euro2core.pricing.title_parser import normalize

# ----------------------------------------------------------------- language

_ES_MARKERS = frozenset(
    """
    que cual cuanto cuanta donde como hay moneda monedas vale precio es la el de una mis
    tengo hola significa rara vendo vender comprar chollo chollos novedades identifica
    gracias
    """.split()
)
_EN_MARKERS = frozenset(
    """
    what which how much where is the coin coins worth price rare sell buy bargain bargains
    deals mean means does any today hello thanks my have identify
    """.split()
)


def detect_language(text: str) -> str:
    words = normalize(text).split()
    es = sum(w in _ES_MARKERS for w in words)
    en = sum(w in _EN_MARKERS for w in words)
    return "en" if en > es else "es"


# ----------------------------------------------------------------- intents

INTENTS = (
    "bulletin",
    "value",
    "rarity",
    "buy",
    "deals",
    "sell",
    "glossary",
    "howto",
    "news",
    "greeting",
    "collection",
    "identify",
    "help",
)

# (intent, regex on the normalized text). Order matters: first match wins.
_RULES: tuple[tuple[str, str], ...] = (
    ("greeting", r"^\s*(hola|buenas|buenos dias|buenas tardes|hello|hi|hey)\b"),
    (
        "identify",
        r"\b(identifica|identificar|reconoce|que moneda es|identify|recognize|what coin is)\b",
    ),
    (
        "glossary",
        r"\b(que significa|que es un|que es una|que es el|que es la|que son|significado"
        r"|what is a|what is an|what does .* mean|what are|meaning of)\b",
    ),
    (
        "howto",
        r"\b(como (verifico|verificar|vendo|publico|subo|anado|uso|funciona)"
        r"|how (do i|to|can i)|tutorial|instrucciones)\b",
    ),
    ("deals", r"\b(chollo|chollos|oferta|ofertas|gangas?|barat[ao]s?|bargains?|deals?|cheap)\b"),
    (
        "value",
        r"\b(cuanto vale|cuanto cuesta|valor|vale|precio|cotiza|se vende por"
        r"|worth|value|price|cost|sells? for)\b",
    ),
    ("sell", r"\b(vend[oa]|vender|venta|a cuanto vendo|sell|selling|list it|listing)\b"),
    (
        "collection",
        r"\b(mi coleccion|mis monedas|cuantas monedas tengo|tengo"
        r"|my collection|my coins|how many coins do i)\b",
    ),
    (
        "rarity",
        r"\b(rar[ao]s?|rareza|escas[ao]|dificil de encontrar|rare|rarity|scarce|hard to find)\b",
    ),
    (
        "buy",
        r"\b(donde (puedo )?compr|comprar|compro|buy|purchase|where can i get|where to find)\b",
    ),
    (
        "bulletin",
        r"\b(boletin|resumen del mercado|que ha pasado hoy|que paso hoy|hoy en el mercado"
        r"|mercado hoy|market today|today.s market|daily bulletin|market summary)\b",
    ),
    (
        "news",
        r"\b(novedad|novedades|noticias?|nuevas monedas|ultimas"
        r"|news|latest|new coins|what.s new)\b",
    ),
)
_COMPILED = [(intent, re.compile(pattern)) for intent, pattern in _RULES]

# Exemplars for the embedding fallback (both languages); only used when no rule fires.
_EXEMPLARS: dict[str, tuple[str, ...]] = {
    "value": (
        "cuánto vale esta moneda",
        "what is this coin worth",
        "precio de mercado de la moneda",
    ),
    "rarity": ("es una moneda rara", "how rare is this coin", "qué rareza tiene"),
    "buy": ("dónde compro esta moneda", "where can I buy this coin", "quiero comprarla"),
    "deals": ("hay chollos ahora", "show me bargains", "monedas baratas hoy"),
    "sell": ("a cuánto vendo mi moneda", "how much should I ask when selling", "quiero venderla"),
    "glossary": ("qué significa este término numismático", "what does this term mean"),
    "howto": ("cómo hago para verificar una pieza", "how do I use the app to sell"),
    "news": ("qué novedades hay en el catálogo", "what is new"),
    "bulletin": ("qué ha pasado hoy en el mercado", "what happened in the market today"),
    "collection": ("resumen de mi colección", "how is my collection doing"),
    "identify": ("identifica la moneda de esta foto", "what coin is this"),
    "help": ("qué puedes hacer", "what can you do", "ayuda"),
}


@dataclass(frozen=True)
class Intent:
    intent: str
    confidence: float
    by_rule: bool


def detect_intent(text: str, *, embedder) -> Intent:
    norm = normalize(text)
    for intent, rx in _COMPILED:
        if rx.search(norm):
            return Intent(intent, 1.0, True)
    if embedder is None:
        return Intent("help", 0.0, False)
    query = embedder.embed_query(text)
    best, best_score = "help", -1.0
    for intent, phrases in _EXEMPLARS.items():
        vectors = embedder.embed_passages(list(phrases))
        score = float(np.max(vectors @ query))
        if score > best_score:
            best, best_score = intent, score
    return Intent(best if best_score >= 0.80 else "help", round(best_score, 3), False)


# ----------------------------------------------------------------- coin hints

_YEAR = re.compile(r"\b(19[9]\d|20\d\d)\b")
_STOP = frozenset(
    """
    cuanto cuanta vale valor precio cuesta moneda monedas de la el los las un una es esta
    este esa ese mi mis tengo que cual donde como hay puedo comprar compro vendo vender rara
    raro chollo chollos euro euros 2 dos how much is the coin coins worth what where can i
    buy sell rare price value of a an my this that for does mean and y o por para con en del
    al
    """.split()
)


@dataclass(frozen=True)
class CoinHints:
    country_code: str | None
    year: int | None
    query: str  # free text left after removing question words, country and year
    raw: str = field(default="")


def extract_coin_hints(text: str) -> CoinHints:
    norm = normalize(text)
    country = None
    for code, names in V.COUNTRIES.items():
        for name in names:
            if f" {name} " in norm:
                country = code
                norm = norm.replace(f" {name} ", " ")
                break
        if country:
            break
    year_match = _YEAR.search(norm)
    year = int(year_match.group(1)) if year_match else None
    if year_match:
        norm = norm.replace(year_match.group(1), " ")
    words = [w for w in norm.split() if w not in _STOP and len(w) > 2]
    return CoinHints(country_code=country, year=year, query=" ".join(words), raw=text)


# ----------------------------------------------------------------- glossary

GLOSSARY: dict[str, dict[str, str]] = {
    "bu": {
        "es": "BU (Brilliant Uncirculated, «sin circular brillante»): moneda acuñada con cuños "
        "nuevos y manipulada con cuidado, vendida en coincard o estuche. Vale más que la misma "
        "moneda de circulación.",
        "en": "BU (Brilliant Uncirculated): struck with fresh dies and handled carefully, sold in "
        "a coincard or set. Worth more than the circulation strike of the same coin.",
    },
    "proof": {
        "es": "Proof (PP / BE / FS): acabado espejo con relieves mate, acuñada dos veces para "
        "coleccionistas; tiradas pequeñas y el precio más alto de cada emisión.",
        "en": "Proof: mirror fields with frosted relief, struck twice for collectors; small "
        "mintages and the highest price of each issue.",
    },
    "coincard": {
        "es": "Coincard: tarjeta sellada donde la ceca vende la moneda BU; conserva la moneda "
        "intacta y suele cotizar por encima de la moneda suelta.",
        "en": "Coincard: sealed card in which the mint sells the BU coin; keeps it untouched and "
        "usually trades above the loose coin.",
    },
    "ceca": {
        "es": "Ceca (marca de ceca): la fábrica que acuñó la moneda. Alemania usa A (Berlín), D "
        "(Múnich), F (Stuttgart), G (Karlsruhe) y J (Hamburgo); cada letra es una variante con "
        "su propia tirada y precio.",
        "en": "Mint mark: the facility that struck the coin. Germany uses A (Berlin), D (Munich), "
        "F (Stuttgart), G (Karlsruhe) and J (Hamburg); each letter is its own variant.",
    },
    "sheldon": {
        "es": "Escala Sheldon: graduación de 1 a 70 usada por PCGS/NGC. MS65+ es una moneda "
        "excepcional; MS70 es perfecta. Solo tiene sentido con certificado.",
        "en": "Sheldon scale: 1–70 grading used by PCGS/NGC. MS65+ is exceptional; MS70 is "
        "flawless. Only meaningful with a certificate.",
    },
    "tirada": {
        "es": "Tirada: número de monedas acuñadas. Es el primer factor de rareza: por debajo de "
        "100 000 piezas la moneda suele cotizar muy por encima de su valor facial.",
        "en": "Mintage: the number of coins struck. The first rarity factor: below 100,000 pieces "
        "a coin usually trades well above face value.",
    },
    "valor facial": {
        "es": "Valor facial: 2 €. Es el suelo del precio: ninguna moneda auténtica vale menos, "
        "y una «venta» por debajo es un anuncio incompleto o un error.",
        "en": "Face value: €2, the price floor. No genuine coin is worth less; a 'sale' below it "
        "is an incomplete listing or a mistake.",
    },
    "emision conjunta": {
        "es": "Emisión conjunta: diseño común acuñado por todos los países del euro el mismo año "
        "(2007 Tratado de Roma, 2009 UEM, 2012 diez años del euro, 2015 bandera, 2022 Erasmus). "
        "Cada país es una moneda distinta con su tirada.",
        "en": "Joint issue: one design struck by every euro country the same year (2007, 2009, "
        "2012, 2015, 2022). Each country is a separate coin with its own mintage.",
    },
    "error": {
        "es": "Error de acuñación: fallo real de fabricación (cuño roto, doble acuñación, "
        "híbrido). Solo entra en el catálogo si dos expertos lo validan; la mayoría de "
        "«errores» anunciados en internet no lo son.",
        "en": "Minting error: a genuine production fault (broken die, double strike, mule). It "
        "enters the catalog only after two experts validate it; most 'errors' advertised "
        "online are not.",
    },
    "coloreada": {
        "es": "Edición coloreada: moneda normal a la que un tercero (a veces la propia ceca) "
        "aplica color. Es una edición especial: su valor depende del comprador, no del catálogo.",
        "en": "Coloured edition: a normal coin colourised by a third party (sometimes the mint). "
        "A special edition whose value depends on the buyer, not on the catalog.",
    },
    "rareza": {
        "es": "Índice de rareza (0–100): tirada (60 %), disponibilidad en el mercado (25 %) y "
        "prima sobre el valor facial (15 %). Niveles: común, poco común, rara, muy rara, "
        "excepcional.",
        "en": "Rarity index (0–100): mintage (60%), market availability (25%) and premium over "
        "face value (15%). Tiers: common, uncommon, rare, very rare, exceptional.",
    },
    "comision": {
        "es": "Comisiones: eBay se queda alrededor del 13 % más 0,35 € por venta. El mercado "
        "entre coleccionistas de esta app no cobra comisión.",
        "en": "Fees: eBay keeps about 13% plus €0.35 per sale. The collectors' market in this "
        "app charges nothing.",
    },
}

_GLOSSARY_ALIASES = {
    "bu": ("bu", "brillante sin circular", "brilliant uncirculated", "stempelglanz", "fdc"),
    "proof": ("proof", "polierte platte", "belle epreuve", "fondo specchio", "pp"),
    "coincard": ("coincard", "coin card", "blister"),
    "ceca": ("ceca", "marca de ceca", "mint mark", "mintmark", "letra a", "letra d"),
    "sheldon": ("sheldon", "ms65", "ms70", "pcgs", "ngc", "graduacion", "grading"),
    "tirada": ("tirada", "mintage", "cuantas se acunaron", "how many were struck"),
    "valor facial": ("valor facial", "face value"),
    "emision conjunta": ("emision conjunta", "conjunta", "joint issue", "joint"),
    "error": ("error", "errores", "fallo de acunacion", "minting error", "mule", "hibrido"),
    "coloreada": ("coloreada", "coloured", "colored", "colorizada", "holograma", "hologram"),
    "rareza": ("rareza", "indice de rareza", "rarity", "rarity index"),
    "comision": ("comision", "comisiones", "fees", "fee"),
}


def glossary_answer(text: str, lang: str) -> str | None:
    norm = normalize(text)
    for key, aliases in _GLOSSARY_ALIASES.items():
        if any(f" {a} " in norm for a in aliases):
            return GLOSSARY[key][lang if lang in GLOSSARY[key] else "es"]
    return None
