# Module A — Autonomous Data Core: Design Spec

Status: approved 2026-09-14.

## Goal

A local service that maintains a complete, self-updating catalog of every 2 euro coin
(commemorative and circulation, with minted variants and documented errors), tracks real
market prices from actual sales across eurozone marketplaces, and computes an auditable
rarity index. It exposes a REST API for later modules (vision, portfolio, marketplace).

## Decisions

| Topic | Decision |
|---|---|
| Deployment | Local Windows service, no cloud. Modular monolith in Python. |
| Catalog scope | All 2€ coins: commemoratives (ECB), circulation per year/mint (Numista), errors only when documented and verifiable. |
| Audience | Casual finder (free: identify + honest value range) and serious collector (variants, grades, history). |
| Sources | ECB public HTML, Numista API v3 (key), eBay Browse API (OAuth). National mints in phase 2. |
| Value | Realized sales only (`sold`, `auction_closed`). Asking prices shown separately, never as value. |
| Grades | `circulated` / `unc` / `bu` / `proof` (+ optional Sheldon number when certified by PCGS/NGC). |
| Markets | eBay ES/DE/FR/IT/NL/AT; global + per-region estimates. EUR only. |
| Images | Downloaded to disk with source URL, license, author, sha256. |
| Languages | ES + EN via translation table; extensible. |
| Consensus | Authority hierarchy (ECB 100 > national mint 80 > Numista 50 > eBay 10); conflicts visible. |
| Rarity | Computed 0–100 (mintage 60% / availability 25% / premium 15%), five tiers, components stored. |
| Autonomy | In-process scheduler (APScheduler) with per-job cadence and cursor-based resume. |
| Database | PostgreSQL 16 + pgvector via docker-compose. |

## Domain model

Three layers:

**`coin_type`** — the emission/design. `kind` ∈ {commemorative, circulation, error};
`country_code`; `year`; `series_id?`; `joint_issue_group?`; `ecb_ref?`; `numista_type_id?`.
For errors: `base_type_id` → the normal type, `verification_status` ∈ {documented,
pending_expert}.

**`coin_issue`** — the minted variant. `type_id`; `mint_mark?` (A/D/F/G/J, R, …); `finish`
∈ {circulation, bu, proof}; `packaging` ∈ {loose, coincard, set}; `mintage?` (resolved
winner); `numista_issue_id?`. Unique on (`type_id`, `mint_mark`, `finish`, `packaging`).

**`market_observation`** — a coin seen on the market. `issue_id`; `source_id`;
`marketplace` (EBAY_ES, EBAY_DE, …); `observation_kind` ∈ {sold, asking, auction_closed};
`price`; `currency` = EUR; `grade` ∈ {circulated, unc, bu, proof, unknown}; `sheldon?`;
`certified_by?`; `listing_id`; `listing_url`; `title_raw`; `match_confidence` ∈ [0, 1];
`is_outlier`; `observed_at`. Unique on (`marketplace`, `listing_id`, `observation_kind`).

Supporting tables:

- `country` (`code`, `eurozone_since`, `is_micro_state`), `series`.
- `source` (`code`, `name`, `authority_rank`, `kind` ∈ {catalog, market}, `base_url`).
- **`fact_claim`** (`entity`, `entity_id`, `field`, `value` jsonb, `source_id`, `observed_at`,
  `evidence_url`, `is_winner`). Every catalog fact is a claim; the winner is resolved by
  authority. Losers stay visible.
- `text_translation` (`entity`, `entity_id`, `field`, `lang`, `text`, `source_id`).
- `coin_image` (`type_id` | `issue_id`, `side` ∈ {obverse, reverse, edge}, `local_path`,
  `source_url`, `license`, `author`, `sha256`, `embedding vector(512)` NULL — reserved for
  Module B).
- `price_estimate` (`issue_id`, `grade`, `region`, `window_days`, `median`, `p25`, `p75`,
  `n_obs`, `confidence`, `basis`, `method_version`, `computed_at`).
- `rarity_score` (`issue_id`, `score`, `tier`, `components` jsonb, `method_version`,
  `computed_at`).
- `domain_event` (`kind`, `entity`, `entity_id`, `payload` jsonb, `created_at`).
- `sync_run` (`job`, `started_at`, `finished_at`, `status`, `cursor` jsonb, `stats` jsonb,
  `error`).

Out of scope: users, personal collections, marketplace (Modules D/E).

## Sources (adapters)

Common interface `SourceAdapter`: `discover(cursor) -> Iterable[Claim | Observation]`,
`authority_rank`, `rate_limit`. Raw responses cached under `data/cache/<source>/` keyed by
content hash so parsing is reproducible offline and tests use real fixtures. Adapters never
write domain tables; they only emit claims/observations.

1. **ECB** — yearly commemorative pages `comm_<year>.<lang>.html` (2004→) and per-country
   national-side pages. Emits `coin_type` claims (theme, mintage, issue date, official
   image).
2. **Numista v3** — type search (issuer + 2 euro), `/types/{id}`, `/types/{id}/issues`
   (year, mint mark, mintage per finish), ES/EN titles, photos with license. Emits
   `coin_issue` claims. Also circulation coins per year/mint.
3. **eBay Browse** — `item_summary/search` per marketplace. Active listings → `asking`.
   Auctions are tracked and re-queried at end → `auction_closed`. Title parser
   (multilingual dictionary: "Stempelglanz"→BU, "BE"/"PP"→proof, "coincard"/"cartera",
   lot detection) + fuzzy theme match (rapidfuzz) → `match_confidence`. Thresholds:
   < 0.6 discard; 0.6–0.85 store but exclude from estimates; ≥ 0.85 counts.
4. **National mints** — reserved slot (phase 2) for yearly circulation mintages.

Politeness: token bucket per source, exponential backoff, ETag/Last-Modified, identified
User-Agent, robots.txt respected.

## Scheduler

| Job | Cadence |
|---|---|
| `ecb_discover` | 24h |
| `numista_catalog` | 7d, incremental |
| `ebay_hot` (issues with an observation in last 30d) | 6h |
| `ebay_cold` | 72h |
| `auction_close_check` | 1h |
| `recompute_prices` | 24h |
| `recompute_rarity` | 24h |

Each run writes a `sync_run` with a cursor; on startup, unfinished runs resume.

## Consensus

For each (`entity`, `entity_id`, `field`): winner = highest `authority_rank`; tie → most
recent `observed_at`. Values are normalized before comparison (mintage → int, dates → ISO,
text → casefold, unaccented, whitespace-collapsed). `has_conflict` when sources with rank
≥ 50 disagree. Resolution is idempotent. A change of winner emits a `domain_event`.

## Price estimation

Per (`issue_id`, `grade`, `region`, window):

- Only observations with `match_confidence ≥ 0.85` and kind ∈ {sold, auction_closed}.
- Window 90 days; widen to 365 if n < 5; "insufficient data" if n < 3.
- Outliers: IQR × 1.5 fence on log(price), flagged `is_outlier`, excluded.
- Output: median, p25, p75, `n_obs`, `confidence` (high ≥ 10 / medium 5–9 / low < 5).
- Region `global` pools all marketplaces; per-marketplace only if n ≥ 3.
- If no realized sales exist, `basis = asking_only` with the asking median, clearly labeled.

## Rarity index (0–100)

- Mintage (60%): log scale, 30,000,000 → 0 and 10,000 → 100, clamped.
- Availability (25%): active listings per million mintage, normalized against catalog
  median (less supply → rarer).
- Premium (15%): log of median sale price / 2.00 €.
- Tiers: ≥ 85 Exceptional · 65–84 Very rare · 45–64 Rare · 25–44 Uncommon · < 25 Common.
- `components` and `method_version` stored for audit.

## Domain events

Emitted on: winner change in `fact_claim`, new `coin_type`, price jump > 30% between
recomputes. Kinds: `new_type_discovered`, `mintage_revised`, `price_spike`, … This is the
raw feed Module C turns into news and alerts.

## API (FastAPI, JSON, `Accept-Language` for ES/EN)

`GET /types` (filters: country, year, kind, q) · `GET /types/{id}` (translations,
conflicts) · `GET /issues/{id}` (estimates by grade/region, rarity, images) ·
`GET /issues/{id}/observations` · `GET /search?q` (tsvector + unaccent) ·
`GET /events?since` · `GET /sources` · `GET /sync/runs` · `POST /sync/{job}` ·
`GET /health`.

## CLI (Typer)

`euro2 db upgrade` · `euro2 sync ecb|numista|ebay` · `euro2 recompute prices|rarity` ·
`euro2 serve`.

## Project layout

```
src/euro2core/
  config.py  db.py
  domain/     models.py enums.py
  sources/    base.py ecb/ numista/ ebay/
  consensus/  resolver.py
  pricing/    title_parser.py matcher.py estimator.py
  rarity/     scorer.py
  images/     fetcher.py
  scheduler/  jobs.py
  api/        app.py routers/
  cli.py
tests/ unit/ integration/ fixtures/
```

Packages depend inward only: adapters never import `consensus` or `api`.

## Testing

TDD throughout. Parsers tested against captured real fixtures (ECB HTML, Numista JSON,
eBay JSON). Consensus resolver and price estimator with synthetic cases. Listing matcher
against a labeled set of ~100 real eBay titles with measured precision. Integration tests
against a real PostgreSQL from docker-compose.

## Implementation notes (post-design, 2026-09-14)

Deviations from the design above, all driven by what the real sources do:

- `coin_issue.year` was added to the unique key: circulation types span years.
- `coin_type.mintage_total` holds the ECB total; per-variant mintage stays on issues.
- `coin_image.local_path`/`sha256` are nullable: Numista photos are blocked for automated
  clients and are stored as references only.
- `observation_kind` gained `auction_open`; `market_observation.ends_at` drives the hourly
  auction close check. Open bids never count as prices.
- Cross-source reconciliation (`catalog/reconcile.py`) merges Numista types into ECB
  emissions by uniqueness per country/year when fuzzy matching fails; coloured/hologram
  editions remain standalone and listings only match them when the title says so.
- Rarity mintage bounds are calibrated per finish class (1st/99th percentiles), stored in
  `components.mintage_bounds`.
- Joint issues: participants are the euro area members of that year unioned with countries
  that have a national photo on the ECB page.
- Numista enforces a call quota (~2,000/day); jobs keep a cursor and the scheduler retries
  failed runs after one hour.

## Review fixes (multi-axis code review, 2026-09-14)

- Price estimates whose observations aged out are deleted; a stale price is never served.
- Same-name jobs are serialised with an in-process lock; `POST /sync/{job}` answers 409 while
  one runs. Cursors are checkpointed after each unit; a run left RUNNING by a crash is closed
  and its cursor resumed. The eBay daily budget counts calls spent earlier today.
- Rarity availability is unknown (not scarcity) where the market job never searched that
  country/year. ECB-only emissions carry a loose placeholder issue so prices can attach;
  Numista variants supersede it.
- Ended auctions eBay no longer serves are dropped instead of blocking the queue; a realized
  sale inherits the issue and grade resolved while open; recorded sales never migrate.
- `/images` refuses reference-only rows and paths outside the image store; `has_conflict`
  uses the resolver's normalisation; search escapes SQL wildcards.

## Stress cases

1. Contradicting sources → `fact_claim` + authority + visible conflict.
2. Ambiguous listing or lot ("2 euro Germany 2006", "lot of 5") → lot detection discards;
   missing mint mark → confidence < 0.85, does not count.
3. Source down or HTML changed → disk cache, fixture tests fail before production,
   `sync_run` marked failed, existing data never deleted.
4. Manipulated price (5000 €, fake sales) → sold-only, log-IQR fence, minimum n, exposed
   confidence.
5. API limits / blocking → per-source token bucket, exponential backoff, resumable cursor.
