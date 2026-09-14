# euro2-core

Open numismatics platform for **2 euro coins**: a self-updating catalog of every 2€ coin
(commemorative and circulation, with mint marks, finishes and documented errors), real
market prices from actual sales, an auditable rarity index, identification by photo, a
collector portfolio with signed provenance, a peer-to-peer marketplace and a Flutter app.

| Module | What it does | Where |
|---|---|---|
| A · Data core | catalog, sources, consensus, prices, rarity, scheduler | `sources/`, `catalog/`, `consensus/`, `pricing/`, `rarity/`, `scheduler/` |
| B · Vision | identify a coin from a photo (CLIP + SIFT), confirm loop | `vision/` |
| C · Knowledge | semantic search in any language, automatic news, expert error reports | `platform/semantic.py`, `platform/news.py`, `platform/community.py` |
| D · Portfolio | collection, valuation by basis, achievements, price alerts (Pro) | `platform/portfolio.py`, `platform/achievements.py`, `platform/alerts.py` |
| E · Marketplace | listings of verified pieces, offers, trades, reputation, certificates | `platform/marketplace.py`, `platform/provenance.py` |
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
