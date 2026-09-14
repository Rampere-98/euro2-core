# euro2-core

Autonomous data core for **2 euro coins**: a self-updating catalog of every 2€ coin
(commemorative and circulation, with mint marks, finishes and documented errors), real
market prices from actual sales, and an auditable rarity index.

This is Module A of a larger numismatics platform. It exposes a REST API that later
modules (vision identification, portfolio, marketplace) build on.

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
uv run euro2 sync ecb       # official commemorative registry
uv run euro2 sync numista   # variants, mintages, translations, images
uv run euro2 sync ebay      # market observations
uv run euro2 recompute prices
uv run euro2 recompute rarity
uv run euro2 serve          # API + scheduler on http://localhost:8000
```

If Windows App Control blocks the generated `euro2.exe` launcher (error 4551), use
`uv run python -m euro2core <command>` instead — same CLI.

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

## License

MIT
