"""Multilingual vocabulary used to parse marketplace listing titles.

All entries are matched against a normalized title: casefolded, accents stripped,
punctuation replaced by spaces. Multi-word phrases are allowed.
"""

from euro2core.domain.enums import Finish, Grade, Packaging

# ---------------------------------------------------------------------------
# Countries: every way a seller in ES/EN/DE/FR/IT/NL might name the issuer.
# ---------------------------------------------------------------------------
COUNTRIES: dict[str, tuple[str, ...]] = {
    "AD": ("andorra",),
    "AT": ("austria", "osterreich", "oesterreich", "autriche", "oostenrijk"),
    "BE": ("belgica", "belgium", "belgien", "belgique", "belgio", "belgie"),
    "BG": ("bulgaria", "bulgarien", "bulgarie"),
    "HR": ("croacia", "croatia", "kroatien", "croatie", "croazia", "kroatie"),
    "CY": ("chipre", "cyprus", "zypern", "chypre", "cipro"),
    "EE": ("estonia", "estland", "estonie"),
    "FI": ("finlandia", "finland", "finnland", "finlande"),
    "FR": ("francia", "france", "frankreich", "frankrijk"),
    "DE": ("alemania", "germany", "deutschland", "allemagne", "germania", "duitsland", "brd"),
    "GR": ("grecia", "greece", "griechenland", "grece", "griekenland"),
    "IE": ("irlanda", "ireland", "irland", "irlande", "ierland"),
    "IT": ("italia", "italy", "italien", "italie"),
    "LV": ("letonia", "latvia", "lettland", "lettonie", "lettonia"),
    "LT": ("lituania", "lithuania", "litauen", "lituanie"),
    "LU": ("luxemburgo", "luxembourg", "luxemburg", "lussemburgo"),
    "MT": ("malta", "malte"),
    "MC": ("monaco",),
    "NL": (
        "paises bajos",
        "holanda",
        "netherlands",
        "niederlande",
        "pays bas",
        "nederland",
        "olanda",
    ),
    "PT": ("portugal", "portogallo"),
    "SM": ("san marino", "saint marin", "san marin"),
    "SK": ("eslovaquia", "slovakia", "slowakei", "slovaquie", "slovacchia", "slowakije"),
    "SI": ("eslovenia", "slovenia", "slowenien", "slovenie", "slovenie"),
    "ES": ("espana", "spain", "spanien", "espagne", "spagna", "spanje"),
    "VA": ("vaticano", "vatican", "vatikan", "vatican city", "citta del vaticano", "vatikanstadt"),
}

# ---------------------------------------------------------------------------
# Finish (how the coin was struck) and packaging (how it is sold).
# ---------------------------------------------------------------------------
FINISH: dict[Finish, tuple[str, ...]] = {
    Finish.BU: (
        "bu",
        "stempelglanz",
        "stgl",
        "fdc",
        "fior di conio",
        "fleur de coin",
        "brillant universel",
        "brilliant uncirculated",
    ),
    Finish.PROOF: (
        "proof",
        "pp",
        "polierte platte",
        "be",
        "belle epreuve",
        "fondo specchio",
        "fs",
        "spiegelglanz",
        "prueba",
    ),
}

PACKAGING: dict[Packaging, tuple[str, ...]] = {
    Packaging.COINCARD: ("coincard", "coin card", "cartera", "blister", "folder", "carterita"),
    Packaging.SET: ("set", "kms", "estuche", "cofre", "coffret", "cofanetto", "kursmunzensatz"),
}

# ---------------------------------------------------------------------------
# Grade hints when no certification is present.
# ---------------------------------------------------------------------------
GRADE: dict[Grade, tuple[str, ...]] = {
    Grade.CIRCULATED: (
        "circulada",
        "circulated",
        "circulee",
        "circolata",
        "umlauf",
        "aus umlauf",
        "mbc",
        "ebc",
        "ss",
        "vz",
        "vf",
        "xf",
        "ttb",
        "sup",
        "bb",
        "spl",
    ),
    Grade.UNC: ("sc", "sin circular", "unc", "uncirculated", "bfr", "bankfrisch", "unz", "neuve"),
}

CERTIFIERS = ("pcgs", "ngc", "anacs")

# ---------------------------------------------------------------------------
# Lots / multi-coin listings: never a single observation.
# ---------------------------------------------------------------------------
LOT_WORDS = (
    "lote",
    "lot",
    "lotto",
    "konvolut",
    "sammlung",
    "coleccion",
    "collection",
    "collezione",
    "komplett",
    "completo",
    "completa",
    "complete",
    "komplettsatz",
    "satz",
)
COUNT_NOUNS = ("monedas", "coins", "munzen", "pieces", "pezzi", "stuck", "munten", "monete")

# Words that describe the object itself and carry no theme information.
NOISE_WORDS = (
    "euro",
    "euros",
    "eur",
    "moneda",
    "monedas",
    "coin",
    "coins",
    "munze",
    "munzen",
    "piece",
    "pieces",
    "moneta",
    "monete",
    "munt",
    "munten",
    "conmemorativa",
    "conmemorativas",
    "commemorative",
    "commemoratives",
    "gedenkmunze",
    "gedenkmunzen",
    "commemorativa",
    "commemorativo",
    "commemoratieve",
    "pragestatte",
    "ceca",
    "mint",
    "mintmark",
    "oficial",
    "official",
    "rare",
    "rara",
    "selten",
    "nueva",
    "new",
    "neu",
    "de",
    "del",
    "la",
    "el",
    "los",
    "las",
    "the",
    "of",
    "der",
    "die",
    "das",
    "du",
    "des",
    "le",
    "les",
    "di",
    "il",
    "van",
    "y",
    "and",
    "und",
    "et",
    "e",
)
