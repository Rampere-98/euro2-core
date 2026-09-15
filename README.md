# euro2-core

Open numismatics platform for **2 euro coins**: a self-updating catalog of every 2€ coin
(commemorative and circulation, with mint marks, finishes and documented errors), honest
values (real sales when they exist, labelled estimates when they do not), an auditable rarity
index, identification by photo, a collector portfolio with signed provenance, a market
assistant for buyers and sellers, a local AI chat, and a Flutter app. Informational only: the
app tells you what a coin is, what it is worth and where to look — it does not sell anything.

**Nobody needs an API key.** The service runs on the owner's machine (`euro2 serve`) and the
app reads from it; ECB pages need no key, values fall back to the app's own mintage model and
to what collectors record, and the assistant runs local models (CLIP, e5). Optional keys in
the owner's `.env` (Numista, eBay) only enrich the data centrally, within their own quotas.

| Module | What it does | Where |
|---|---|---|
| A · Data core | catalog, sources, consensus, prices, rarity, scheduler | `sources/`, `catalog/`, `consensus/`, `pricing/`, `rarity/`, `scheduler/` |
| B · Vision | identify a coin from a photo (CLIP + SIFT), confirm loop | `vision/` |
| C · Knowledge | semantic search in any language, automatic news, expert error reports | `platform/semantic.py`, `platform/news.py`, `platform/community.py` |
| D · Portfolio | collection, valuation by basis, achievements, price alerts (Pro) | `platform/portfolio.py`, `platform/achievements.py`, `platform/alerts.py` |
| E · Marketplace | listings of verified pieces, offers, trades, reputation, certificates | `platform/marketplace.py`, `platform/provenance.py` |
| F · Market assistant | reliability of listings, fair band, deals, buy/sell advice, price chart, watchlist, listing copy | `pricing/reliability.py`, `pricing/market_intel.py`, `platform/market_assistant.py` |
| G · Local assistant | chat that answers value/rarity/buy/sell/glossary from the catalog, no external service | `platform/chat_brain.py`, `platform/chat.py` |
| Key-free values | mintage model calibrated by real sales; collectors' purchases as market data | `pricing/mintage_model.py`, `platform/community_market.py` |
| App | Flutter (web/Android/iOS), Spanish UI, served by the API at `/app` | `app/` |

## What makes it different

- **Three-layer model**: emission (`coin_type`) → minted variant (`coin_issue`: mint mark,
  finish, packaging) → market observation. A German commemorative is five circulation
  issues (A/D/F/G/J) plus BU and proof, each with its own mintage and price.
- **Provenance, not overwrites**: every catalog fact is a `fact_claim` with its source.
  Sources are ranked by authority (ECB > national mint > Numista > marketplaces); conflicts
  stay visible instead of being silently resolved.
- **Honest prices**: estimates use only realized sales (`sold`, `auction_closed`), robust
  statistics (median, IQR outlier fence in log space) and expose sample size and
  confidence. Asking prices are reported separately and never disguised as value.
- **Computed rarity**: 0–100 index from mintage, market availability and premium over face
  value, with every component stored for audit.

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2 (async) · PostgreSQL 16 + pgvector · Alembic ·
httpx · APScheduler · Typer. Managed with [uv](https://docs.astral.sh/uv/).

## Quick start

```bash
cp .env.example .env        # fill in API keys
docker compose up -d        # PostgreSQL 16 + pgvector
uv sync
uv run euro2 db upgrade
uv run euro2 sync ecb       # official commemorative registry (2004 -> today)
uv run euro2 sync numista   # variants, mintages, translations, photo references
uv run euro2 reconcile      # merge records two sources created for the same coin
uv run euro2 sync ebay      # asking prices and live auctions (needs eBay keys)
uv run euro2 sync auctions  # ended auctions -> realized sales
uv run euro2 recompute prices
uv run euro2 recompute rarity
uv run euro2 serve          # API (docs at /docs) + scheduler on http://localhost:8000
```

To keep it running unattended on Windows (starts at logon, restarts if it stops):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1
```

If Windows App Control blocks the generated `euro2.exe` launcher (error 4551), use
`uv run python -m euro2core <command>` instead — same CLI.

Every job records a `sync_run` (stats, error, resumable cursor) and can be triggered from the
API with `POST /sync/{job}`. `serve` runs them on their cadence: ECB daily, Numista weekly,
eBay market every 72h (active coins every 6h), auction checks hourly, prices and rarity daily.
A failed run keeps its cursor and is retried an hour later.

## Things learned from the real sources

- **Numista quota**: the API returns 429 after roughly 2,000 calls; the sync stops, keeps its
  cursor and resumes on the next run. Responses are cached for 7 days, so retries are cheap.
- **Numista photos** sit behind bot protection (403 for any automated client). They are kept
  as attributed references (URL, author, license) with no local copy; ECB photos download fine.
- **Cross-source naming**: about 20% of Numista commemoratives do not fuzzy-match the ECB
  title ("Nordrhein-Westfalen" vs "North Rhine-Westphalia"). `reconcile` settles them by
  uniqueness per country and year; coloured and hologram editions stay separate entries.
- **Rarity per finish class**: proofs and BU sets always have tiny mintages, so the mintage
  scale is calibrated against each finish class's own distribution.
- **Source data errors happen**: mintages written as "30 million", an issue dated year 0, a
  joint-issue page missing a country's photo. Each has a test and a defined behaviour.

### Images

- Commemoratives: the official ECB photo of each national side, downloaded with attribution.
  One photo may illustrate several coins (joint issues); "coming soon" placeholders are ignored.
- Circulation coins: the ECB per-country pages list every design a country has used
  (`Belgium_2euro_2008.jpg`…); each circulation type gets the design current in its first year.
- Numista photos are attributed references only (their CDN refuses scripted downloads), so a
  coin that exists only on Numista — 2026 issues before the ECB page appears, coloured or
  hologram editions — shows no photo until an official one exists.

## Tests

```bash
uv run pytest                      # unit tests always run; integration tests need the test DB
docker exec euro2-db psql -U euro2 -d euro2 -c "CREATE DATABASE euro2_test"
DATABASE_URL=postgresql+asyncpg://euro2:euro2@localhost:5432/euro2_test uv run alembic upgrade head
```

Integration tests truncate tables, so they use `euro2_test` (override with
`TEST_DATABASE_URL`), never the working catalog.

## Data sources

| Source | Kind | Authority | Access |
|---|---|---|---|
| European Central Bank | catalog | 100 | public HTML |
| National mints / central banks | catalog | 80 | phase 2 |
| Numista API v3 | catalog | 50 | free API key |
| eBay Browse API (ES/DE/FR/IT/NL/AT) | market | 10 | developer keyset |

Downloaded images keep their source URL, license and author.

## Design

See [docs/superpowers/specs](docs/superpowers/specs/) for the approved design spec.

## Flutter app

```bash
cd app
flutter pub get
flutter build web --release --base-href /app/   # then `euro2 serve` exposes it at /app
flutter run -d chrome                           # or any device; API URL is editable in Perfil
```

Six tabs: **Escanear** (camera/gallery → candidates with confidence → "Es esta" feedback),
**Catálogo** (text or semantic search, country/year filters, provenance and conflicts per fact,
variants with mintage, rarity tier and prices by basis), **Colección** (net worth split by
basis, verify a piece by photo, traceability + signed certificate, achievements), **Mercado**
(publish verified pieces, offers, accept/reject, ratings), **Noticias** (auto-published
catalog changes, error reports with expert votes) and **Perfil** (login, Pro plan,
notifications, leaderboard, server URL).

## License

MIT

## Module B — identification by photo

`POST /identify` (multipart `file`) answers with the most likely coins. Pipeline:

1. **OpenCV** finds the coin (Hough circle), crops a square around it and greys out the outer
   ring: the 12 stars are identical on every 2 euro coin and would only add noise.
2. **CLIP ViT-B/32** embeds the core; the catalog is indexed at 12 rotations per image in
   pgvector, because coins are photographed at any orientation.
3. **SIFT + RANSAC** verifies the shortlist geometrically, so the answer is the exact design
   rather than a similar one. Confidence comes from the number of consistent feature matches.

Measured on 80 catalog photos rotated up to ±25°, downscaled to 140–260 px and recompressed
at 45–80 % JPEG quality: **76/80 top-1 (95 %)**; three of the four misses were returned as
"low" confidence and the fourth was a joint issue whose design is identical across countries.
Every request is stored with its embedding; `POST /identify/{id}/confirm` records the true coin,
which is the training set for future fine-tuning. `uv run euro2 recompute embeddings` builds the
index (downloads ~600 MB of weights once); the scheduler keeps it updated daily.

## Modules C–E — platform

Accounts use argon2 + JWT (`/auth/register`, `/auth/login`). Everything below is bilingual
(`Accept-Language: es|en`).

- **Portfolio** — `POST /me/collection` stores a piece (`coin_issue` + grade + optional
  Sheldon/price). `GET /me/collection` values each piece with the best available basis
  (realized sales > catalog > asking > face value) and says which one it used; a total is
  reported per basis so a "catalog" number is never mixed with a real one. Each piece has a
  `piece_event` trail (added, verified, sold, traded) and an HMAC-signed certificate that
  anyone can check with `POST /certificates/{id}/verify`.
- **Verification** — `POST /me/collection/{id}/verify` runs Module B on a photo of the piece;
  only a high-confidence match with the registered coin marks it verified, and only verified
  pieces can be listed for sale.
- **Gamification** — achievements (milestones, complete country, complete joint issue, rare
  hunter, verified piece) awarded on every change with a notification; `GET /leaderboard`.
- **Alerts (Pro)** — `POST /me/alerts` above/below thresholds, evaluated after every price
  recompute. `POST /me/plan/pro` is a demo switch (no billing).
- **Marketplace** — listings (`/market/listings`, free plan up to 3 active), cash or trade
  offers, accept/reject transfers the piece and writes the provenance event, five-star
  ratings feed `GET /users/{id}/reputation`.
- **Community** — `POST /reports` submits a suspected minting error against a base type;
  two expert approvals create a documented `error` type with a "community" source (rank 40).
- **News** — domain events (new type, price jump, validated error) become bilingual
  `news_item`s hourly. **Semantic search** — `GET /search/semantic?q=` embeds titles and
  descriptions with `multilingual-e5-small`, so "moneda con un puente" finds bridges in any
  language.

## Module F — market assistant

Every listing is scored before it is shown (`pricing/reliability.py`): lots, replicas, plated or
colourised coins, weak matches and sub-face-value "sales" are discarded with a reason the app
displays. On what remains, `pricing/market_intel.py` builds the coin's snapshot: realized range
(min/p25/median/p75/max over 90 → 365 days), the fair band (p25–p75 of real sales, else catalog
±20 %, else face value — always labelled), current reliable offers, trend (last 90 days vs the
rest of the year), liquidity and best marketplace. From that: a buy verdict (`buy_now`, `fair`,
`overpriced`, `wait`), a sell plan per piece (start price, floor, net after eBay fees vs the
free euro2 marketplace, expected days, hold hint), a deals feed and movers.

`GET /types/{id}/market` also returns the monthly chart data (sold min/median/max, asking
median) and the estimate trail (`estimate_history`, appended whenever a recompute changes a
value). Watching a coin (`/me/watchlist`, free) turns deals and > 20 % moves into notifications
after every price recompute. Price alerts are free for every user.

## Values without any API key

Every variant always has a value with an explicit basis, in this order:

1. `sold` — real sales (eBay via API when configured, and **purchases collectors record on
   their own pieces**, which need no third party at all).
2. `catalog` — Numista catalog value, when the owner has a key.
3. `mintage_model` — the app's own estimate from the design's mintage (`pricing/mintage_model.py`):
   explicit buckets from the scarcest (< 15 000 → 800–3 000 €) to the commonest (≥ 8 M →
   2,20–3,50 €), scaled by finish. Whenever a bucket accumulates five coins with real sales the
   bucket recalibrates itself from them. Circulation designs are treated as common unless the
   circulation strike itself is scarce; coloured/hologram editions inherit their base design.
4. `face_value` — 2 €, only when even the mintage is unknown.

The catalog rows show the reference variant's range with its basis; `GET /types` filters by
`min_value`/`max_value` and sorts by value.

## Local assistant (chat)

`POST /assistant/chat {"message": "¿cuánto vale la de Mónaco 2007?"}` answers from the
database: intent by rules (Spanish and English), local e5 embeddings when rules are unsure,
coins resolved from country/year/theme with the same local semantic index as search. It covers
value, rarity, where it is for sale, what to ask when selling, today's deals, news, the user's
collection and a numismatic glossary. Nothing leaves the machine.
