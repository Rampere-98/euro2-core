# ruff: noqa: F811  (fixtures imported from sibling test modules are re-bound as parameters)
"""The local assistant answers from real rows: value, rarity, buy, glossary, deals, sell."""

import pytest

from tests.integration.test_assistant import SALES, _seed_market
from tests.integration.test_platform import _signup, catalog, client  # noqa: F401

pytestmark = pytest.mark.integration


async def test_value_question_finds_the_coin_by_country_and_year(client, catalog, session):
    await _seed_market(session, catalog["de_a"], prices=SALES, asks=(2.5,))
    r = await client.post(
        "/assistant/chat", json={"message": "¿Cuánto vale la moneda de Alemania 2006?"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intent"] == "value" and body["lang"] == "es"
    assert "ventas reales 3.00–4.00 €" in body["text"]
    assert "2.50 €" in body["text"]  # cheapest reliable offer
    assert body["type_ids"] == [str(catalog["de_type"])]
    assert body["links"][0]["url"].startswith("https://ebay.es/")


async def test_value_without_sales_says_so_instead_of_inventing(client, catalog):
    r = await client.post(
        "/assistant/chat", json={"message": "How much is the Vatican 2004 coin worth?"}
    )
    body = r.json()
    assert body["lang"] == "en" and body["intent"] == "value"
    assert "face value" in body["text"] or "catalog value" in body["text"]


async def test_rarity_and_glossary_and_buy(client, catalog, session):
    r = (
        await client.post("/assistant/chat", json={"message": "¿Es rara la de Alemania 2006?"})
    ).json()
    assert r["intent"] == "rarity" and "rareza" in r["text"]
    g = (await client.post("/assistant/chat", json={"message": "qué significa BU"})).json()
    assert g["intent"] == "glossary" and "sin circular" in g["text"].lower()
    await _seed_market(session, catalog["de_a"], prices=SALES, asks=(2.5, 3.6))
    b = (
        await client.post("/assistant/chat", json={"message": "dónde compro la de Alemania 2006"})
    ).json()
    assert b["intent"] == "buy" and "2 anuncios fiables" in b["text"] and len(b["links"]) == 2


async def test_deals_and_sell_advice_for_signed_in_user(client, catalog, session):
    await _seed_market(session, catalog["de_a"], prices=SALES, asks=(2.5,))
    d = (await client.post("/assistant/chat", json={"message": "hay chollos?"})).json()
    assert d["intent"] == "deals" and "2.50 €" in d["text"]
    auth = await _signup(client, "chat@example.org")
    anon = (
        await client.post("/assistant/chat", json={"message": "a cuánto vendo mis monedas"})
    ).json()
    assert "inicies sesión" in anon["text"]
    await client.post(
        "/me/collection", json={"issue_id": str(catalog["de_a"]), "grade": "unc"}, headers=auth
    )
    s = (
        await client.post(
            "/assistant/chat", json={"message": "a cuánto vendo la de Alemania 2006"}, headers=auth
        )
    ).json()
    assert s["intent"] == "sell" and "pide" in s["text"] and "tras comisiones" in s["text"]
    c = (
        await client.post(
            "/assistant/chat", json={"message": "cuántas monedas tengo"}, headers=auth
        )
    ).json()
    assert c["intent"] == "collection" and "Tienes 1 piezas" in c["text"]


async def test_context_coin_is_used_when_the_question_names_none(client, catalog, session):
    await _seed_market(session, catalog["de_a"], prices=SALES)
    r = (
        await client.post(
            "/assistant/chat", json={"message": "¿cuánto vale?", "type_id": str(catalog["de_type"])}
        )
    ).json()
    assert r["intent"] == "value" and r["type_ids"] == [str(catalog["de_type"])]
