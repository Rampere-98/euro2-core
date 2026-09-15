# Module F — Market assistant (buy & sell) — design (2026-09-15)

Goal: the app is not a catalog with prices but an assistant that keeps the user inside the
2 euro market: which coins are really for sale, what they really go for (min/max/fair band),
where the bargains are, what to ask when selling, and when to wait. Free for every user.

## Sources (all free, all legitimate)

| Source | What | Why not others |
|---|---|---|
| eBay Browse API (ES/DE/FR/IT/NL/AT) | active listings (asking), auctions, realized sales when they close | free developer keyset, 5k calls/day, the deepest 2€ market |
| euro2 marketplace | listings between verified collectors, no fees | ours |
| Numista catalog values | reference when no sales exist | labelled `catalog`, never mixed with sales |
| Todocoleccion, Delcampe | — | `robots.txt` forbids crawling; Catawiki has no API |

## Reliability of a listing (`pricing/reliability.py`)

Every observation is scored 0–1 from its title and price before it is shown or used:

| Signal | Effect |
|---|---|
| parser says lot / multiple coins | unusable (0) — a lot price is not a coin price |
| replica / copia / fantasy / prueba / essai / pattern | unusable (0) |
| plated / gilded / coloured / chapada / bañada on a plain design | unusable (0) — altered coin |
| match confidence < 0.85 | unusable (0); 0.85–0.95 → 0.7; ≥ 0.95 → 1.0 |
| sold price below face value (2 €) | unusable (0) — incomplete or shipping-only |
| price > 20 × fair p75 | 0.3 — likely a typo or a fantasy price |
| title year differs from the issue year | 0.5 |
| certified (PCGS/NGC) | +0.1 (cap 1) |

Reasons are returned in Spanish/English for the UI ("lote de 5 monedas", "réplica", …).

## Market snapshot per issue (`pricing/market_intel.py`)

- **Realized** (reliable `sold`/`auction_closed`, 90 d → 365 d): n, min, p25, median, p75, max.
- **Fair band** = [p25, p75] of realized; fallback `catalog` value ±20 %; fallback face value.
  The basis is always returned with the band.
- **Asking** (reliable active listings): n, min, median, max, per marketplace, links.
- **Trend**: median of last 90 d vs median of the previous 275 d, as a percentage.
- **Liquidity**: reliable sales per 30 days → expected days to sell.
- **Best marketplace**: highest realized median with n ≥ 3.

## Advice

- **Buy** (`buy_advice`): cheapest reliable active listing vs the band → `buy_now` (≤ p25),
  `fair` (p25–p75), `overpriced` (> p75), `wait` when trend ≤ −10 %, `no_offers` when none.
  Includes the listing link and the saving vs the band.
- **Sell** (`sell_advice` for a piece in the collection): start price = p75, floor = p25,
  adjusted by grade (circulated ×0.7, unc ×1.0, bu ×1.15, proof ×1.5 unless the band already
  comes from that grade); expected days from liquidity; eBay fee estimate (13.25 % + 0.35 €)
  vs euro2 marketplace (0); `hold` hint when trend ≥ +15 %.
- **Deals feed** (`deals`): active reliable listings priced ≤ 85 % of fair p25, ranked by
  discount × reliability × rarity weight; includes euro2 marketplace listings.
- **Movers**: issues whose 90-day realized median moved most vs the previous window.

## Watchlist (free)

`POST /me/watchlist {issue_id}` — after every market sync the user is notified of new deals on
watched issues and of price moves > 20 %. Price threshold alerts (`/me/alerts`) become free.

## API

`GET /market/deals` · `GET /market/movers` · `GET /issues/{id}/market` ·
`GET /me/collection/{id}/sell-advice` · `GET/POST/DELETE /me/watchlist`.

## App

Mercado becomes the assistant: **Chollos** (feed with links), **Comprar** (search a coin →
snapshot, band, min/max, listings, verdict), **Vender** (my pieces → suggested price, where,
net after fees, publish in one tap), **Coleccionistas** (peer listings, offers), **Seguimiento**
(watchlist). Coin detail shows the market block with min/max and links.
