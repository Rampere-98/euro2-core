"""Search phrases per marketplace language: sellers write titles in their own language."""

from euro2core.sources.ebay.parser import MARKETPLACES

# ISO country -> name by language (es, de, fr, it, nl); English is what eBay AT/DE/NL also index
COUNTRY_NAMES: dict[str, dict[str, str]] = {
    "AD": {"es": "andorra", "de": "andorra", "fr": "andorre", "it": "andorra", "nl": "andorra"},
    "AT": {
        "es": "austria",
        "de": "österreich",
        "fr": "autriche",
        "it": "austria",
        "nl": "oostenrijk",
    },
    "BE": {"es": "bélgica", "de": "belgien", "fr": "belgique", "it": "belgio", "nl": "belgië"},
    "BG": {
        "es": "bulgaria",
        "de": "bulgarien",
        "fr": "bulgarie",
        "it": "bulgaria",
        "nl": "bulgarije",
    },
    "CY": {"es": "chipre", "de": "zypern", "fr": "chypre", "it": "cipro", "nl": "cyprus"},
    "DE": {
        "es": "alemania",
        "de": "deutschland",
        "fr": "allemagne",
        "it": "germania",
        "nl": "duitsland",
    },
    "EE": {"es": "estonia", "de": "estland", "fr": "estonie", "it": "estonia", "nl": "estland"},
    "ES": {"es": "españa", "de": "spanien", "fr": "espagne", "it": "spagna", "nl": "spanje"},
    "FI": {
        "es": "finlandia",
        "de": "finnland",
        "fr": "finlande",
        "it": "finlandia",
        "nl": "finland",
    },
    "FR": {"es": "francia", "de": "frankreich", "fr": "france", "it": "francia", "nl": "frankrijk"},
    "GR": {
        "es": "grecia",
        "de": "griechenland",
        "fr": "grèce",
        "it": "grecia",
        "nl": "griekenland",
    },
    "HR": {"es": "croacia", "de": "kroatien", "fr": "croatie", "it": "croazia", "nl": "kroatië"},
    "IE": {"es": "irlanda", "de": "irland", "fr": "irlande", "it": "irlanda", "nl": "ierland"},
    "IT": {"es": "italia", "de": "italien", "fr": "italie", "it": "italia", "nl": "italië"},
    "LT": {"es": "lituania", "de": "litauen", "fr": "lituanie", "it": "lituania", "nl": "litouwen"},
    "LU": {
        "es": "luxemburgo",
        "de": "luxemburg",
        "fr": "luxembourg",
        "it": "lussemburgo",
        "nl": "luxemburg",
    },
    "LV": {"es": "letonia", "de": "lettland", "fr": "lettonie", "it": "lettonia", "nl": "letland"},
    "MC": {"es": "mónaco", "de": "monaco", "fr": "monaco", "it": "monaco", "nl": "monaco"},
    "MT": {"es": "malta", "de": "malta", "fr": "malte", "it": "malta", "nl": "malta"},
    "NL": {
        "es": "holanda",
        "de": "niederlande",
        "fr": "pays-bas",
        "it": "olanda",
        "nl": "nederland",
    },
    "PT": {
        "es": "portugal",
        "de": "portugal",
        "fr": "portugal",
        "it": "portogallo",
        "nl": "portugal",
    },
    "SI": {
        "es": "eslovenia",
        "de": "slowenien",
        "fr": "slovénie",
        "it": "slovenia",
        "nl": "slovenië",
    },
    "SK": {
        "es": "eslovaquia",
        "de": "slowakei",
        "fr": "slovaquie",
        "it": "slovacchia",
        "nl": "slowakije",
    },
    "SM": {
        "es": "san marino",
        "de": "san marino",
        "fr": "saint-marin",
        "it": "san marino",
        "nl": "san marino",
    },
    "VA": {"es": "vaticano", "de": "vatikan", "fr": "vatican", "it": "vaticano", "nl": "vaticaan"},
}

_UNIT = {
    "es": "2 euros",
    "de": "2 euro",
    "fr": "2 euros",
    "it": "2 euro",
    "nl": "2 euro",
    "at": "2 euro",
}


def search_query(country_code: str, year: int, marketplace: str) -> str:
    lang = MARKETPLACES[marketplace]
    name_lang = "de" if lang == "at" else lang
    name = COUNTRY_NAMES[country_code][name_lang]
    return f"{_UNIT[lang]} {name} {year}"
