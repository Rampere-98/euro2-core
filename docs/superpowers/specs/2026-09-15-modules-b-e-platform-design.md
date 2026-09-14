# Modules B–E and Flutter app — design as built (2026-09-15)

Companion to the Module A spec. Everything here is implemented, tested (`tests/integration/
test_platform.py`, `test_identify.py`) and served by the same FastAPI process.

## B · Identification by photo (`vision/`)

| Step | Choice | Why |
|---|---|---|
| Locate | OpenCV Hough circle → square crop; fall back to full frame (`found_circle=false`) | phones photograph coins on any background |
| Mask | grey out the outer ring (`CORE_RATIO 0.74`) | the 12 stars are identical on every 2€ coin |
| Embed | CLIP ViT-B/32 (`laion2b_s34b_b79k`), 512-d, pgvector cosine | strong zero-shot visual features, CPU-friendly |
| Rotation | index every catalog image at 12 rotations (`image_embedding`) | orientation is arbitrary; cheaper than rotation-invariant models |
| Re-rank | SIFT + RANSAC inliers on the shortlist | separates "same design" from "similar design" |
| Confidence | `high ≥ 30` inliers, `medium ≥ 14`, `low ≥ 8`, else dropped | measured on degraded photos: 76/80 top-1 |
| Learning | `identification` rows keep the query embedding; `POST /identify/{id}/confirm` labels them | future fine-tuning set |

## C · Knowledge (`platform/semantic.py`, `news.py`, `community.py`)

- **Semantic search**: `multilingual-e5-small` via `transformers` (mean pooling, 384-d,
  `type_embedding`). Query prefix `query:`, passage prefix `passage:` as the model expects.
  scipy-free on purpose (Windows App Control blocked its DLLs).
- **News**: hourly job turns `domain_event`s into bilingual `news_item`s (new type, price jump,
  validated error). The app links each item to the coin.
- **Expert reports**: any user submits a suspected error against a base type (photo optional);
  experts vote; two approvals create a `coin_type(kind=error, base_type_id=…)` whose claims
  come from a `community` source ranked 40 — below Numista, so a documented catalog fact still
  wins a conflict.

## D · Portfolio (`platform/portfolio.py`, `valuation.py`, `achievements.py`, `alerts.py`)

- `collection_item` = one physical piece of a `coin_issue` with grade (+ optional Sheldon,
  cost, notes). `piece_event` is an append-only trail (added, verified, sold, traded).
- **Valuation** picks the best basis per piece — `sold` > `catalog` > `asking_only` >
  `face_value` — and never sums across bases without saying so (`value_by_basis`).
- **Verification**: a photo must identify as the registered coin with `high` confidence.
  Verified pieces are the only ones the marketplace accepts.
- **Certificate**: HMAC-SHA256 over the piece payload (ids, grade, verified_at and the full event chain) with the server
  secret; `POST /certificates/{id}/verify` checks digest + signature without revealing the key.
- **Achievements** are recomputed after every collection change and announced with a
  notification; `leaderboard` = pieces + rarity bonus.
- **Alerts** (Pro): thresholds evaluated right after `recompute_prices`.

## E · Marketplace (`platform/marketplace.py`)

- Listing = verified piece + optional price + `accepts_trades`. Free plan: 3 active listings.
- Offer = cash and/or the buyer's own verified pieces. Accepting transfers ownership (piece
  events on both sides, listing closed, other offers rejected).
- Ratings (1–5) after a completed transaction feed the seller's reputation shown on every
  listing.

## Flutter app (`app/`)

Single `AppState` (token, base URL, user, unread count) persisted with `shared_preferences`;
`Euro2Api` adds `Accept-Language: es` and the bearer token. Six tabs in an `IndexedStack`
(state survives tab switches and the rail↔bottom-bar flip at 800 px). When served from
`/app` by the API the base URL is the page origin, so no CORS is involved; native builds edit
the URL in Perfil.

## Deliberate limits

- No payments: Pro is a flag switched by `POST /me/plan/pro`.
- Numista photos are references only (their CDN refuses scripted downloads); ECB images are
  stored locally and are the vision index.
- Market prices need eBay keys; without them values fall back to catalog/face value and the UI
  says so.
