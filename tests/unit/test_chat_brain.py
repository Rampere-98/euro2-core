import pytest

from euro2core.platform.chat_brain import (
    GLOSSARY,
    detect_intent,
    detect_language,
    extract_coin_hints,
    glossary_answer,
)


@pytest.mark.parametrize(
    "text,lang",
    [
        ("¿Cuánto vale la moneda de Alemania 2006?", "es"),
        ("How much is the Germany 2006 coin worth?", "en"),
        ("que es una moneda BU", "es"),
        ("what does proof mean", "en"),
    ],
)
def test_language_detection(text, lang):
    assert detect_language(text) == lang


@pytest.mark.parametrize(
    "text,intent",
    [
        ("¿Cuánto vale la moneda de Grace Kelly?", "value"),
        ("precio de la moneda 2 euros Finlandia 2004", "value"),
        ("How much does the Schleswig-Holstein sell for?", "value"),
        ("¿Es rara la moneda de Mónaco 2007?", "rarity"),
        ("is the vatican 2004 coin rare", "rarity"),
        ("¿Dónde puedo comprar la moneda de Estonia 2011?", "buy"),
        ("hay chollos ahora", "deals"),
        ("any bargains today?", "deals"),
        ("¿a cuánto vendo mis monedas?", "sell"),
        ("qué significa BU", "glossary"),
        ("what is a coincard", "glossary"),
        ("cómo verifico una moneda", "howto"),
        ("¿qué novedades hay?", "news"),
        ("hola", "greeting"),
        ("cuántas monedas tengo", "collection"),
        ("identifica esta moneda", "identify"),
    ],
)
def test_rule_based_intents(text, intent):
    assert detect_intent(text, embedder=None).intent == intent


def test_coin_hints_extract_country_year_and_free_text():
    hints = extract_coin_hints("¿cuánto vale la de Finlandia 2004 de la ampliación?")
    assert hints.country_code == "FI"
    assert hints.year == 2004
    assert "ampliacion" in hints.query
    assert "cuanto" not in hints.query  # question words are stripped from the search text


def test_glossary_answers_in_both_languages():
    assert "sin circular" in glossary_answer("qué significa BU", "es").lower()
    assert "uncirculated" in glossary_answer("what is bu", "en").lower()
    assert glossary_answer("qué es un coincard", "es") is not None
    assert glossary_answer("sobre la vida en marte", "es") is None
    assert {"bu", "proof", "coincard", "ceca", "sheldon", "tirada"} <= set(GLOSSARY)
