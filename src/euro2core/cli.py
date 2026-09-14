import asyncio
import json
import logging
from pathlib import Path
from typing import Annotated

import typer

from euro2core.config import get_settings
from euro2core.db import get_engine
from euro2core.scheduler.jobs import (
    run_auction_close_check,
    run_ebay_market,
    run_ecb_discover,
    run_embed_images,
    run_embed_types,
    run_numista_catalog,
    run_numista_prices,
    run_publish_news,
    run_recompute_prices,
    run_recompute_rarity,
    run_reconcile,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = typer.Typer(help="euro2-core: autonomous data core for 2 euro coins.", no_args_is_help=True)
db_app = typer.Typer(help="Database migrations.", no_args_is_help=True)
sync_app = typer.Typer(help="Run a source sync job once.", no_args_is_help=True)
recompute_app = typer.Typer(help="Recompute derived data.", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(sync_app, name="sync")
app.add_typer(recompute_app, name="recompute")

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _alembic_upgrade(revision: str) -> None:
    from alembic.config import Config

    from alembic import command

    command.upgrade(Config(str(_ALEMBIC_INI)), revision)


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply all pending migrations."""
    _alembic_upgrade("head")
    typer.echo("Database is at head.")


@sync_app.command("ecb")
def sync_ecb(
    year: Annotated[
        list[int] | None, typer.Option(help="Only these years (default: 2004 to now)")
    ] = None,
) -> None:
    """Discover commemorative coins from the ECB's official yearly pages."""
    settings = get_settings()
    run = asyncio.run(
        run_ecb_discover(
            get_engine(),
            data_dir=settings.data_dir,
            user_agent=settings.user_agent,
            years=year or None,
        )
    )
    _report_run(run)


@sync_app.command("numista")
def sync_numista(
    issuer: Annotated[
        list[str] | None, typer.Option(help="Only these Numista issuer codes (default: euro area)")
    ] = None,
) -> None:
    """Import variants (mint marks, finishes, mintages), translations and photos from Numista."""
    settings = get_settings()
    run = asyncio.run(
        run_numista_catalog(
            get_engine(),
            data_dir=settings.data_dir,
            api_key=settings.numista_api_key,
            user_agent=settings.user_agent,
            issuers=issuer or None,
        )
    )
    _report_run(run)


@sync_app.command("numista-prices")
def sync_numista_prices() -> None:
    """Fetch Numista catalog values (labelled "catalog", ranked below real sales)."""
    settings = get_settings()
    run = asyncio.run(
        run_numista_prices(
            get_engine(),
            data_dir=settings.data_dir,
            api_key=settings.numista_api_key,
            user_agent=settings.user_agent,
        )
    )
    _report_run(run)


@sync_app.command("ebay")
def sync_ebay(
    marketplace: Annotated[
        list[str] | None, typer.Option(help="EBAY_ES, EBAY_DE, ... (default: all six)")
    ] = None,
    hot: Annotated[
        bool, typer.Option(help="Only country/years active in the last 30 days")
    ] = False,
) -> None:
    """Collect asking prices and live auctions from eBay, matched to catalog issues."""
    settings = get_settings()
    _require_ebay_keys(settings)
    run = asyncio.run(
        run_ebay_market(
            get_engine(),
            client_id=settings.ebay_client_id,
            client_secret=settings.ebay_client_secret,
            user_agent=settings.user_agent,
            marketplaces=marketplace or None,
            hot_days=30 if hot else None,
        )
    )
    _report_run(run)


@sync_app.command("auctions")
def sync_auctions() -> None:
    """Resolve ended auctions into realized sales."""
    settings = get_settings()
    _require_ebay_keys(settings)
    run = asyncio.run(
        run_auction_close_check(
            get_engine(),
            client_id=settings.ebay_client_id,
            client_secret=settings.ebay_client_secret,
            user_agent=settings.user_agent,
        )
    )
    _report_run(run)


@recompute_app.command("embeddings")
def recompute_embeddings() -> None:
    """Embed catalog images with CLIP so photos can be identified (downloads the model once)."""
    _report_run(asyncio.run(run_embed_images(get_engine())))


@recompute_app.command("search-index")
def recompute_search_index() -> None:
    """Embed coin texts for multilingual semantic search (downloads a small model once)."""
    _report_run(asyncio.run(run_embed_types(get_engine())))


@app.command("news")
def publish_news() -> None:
    """Turn new catalog events into news items."""
    _report_run(asyncio.run(run_publish_news(get_engine())))


@app.command("reconcile")
def reconcile() -> None:
    """Merge catalog records that different sources created for the same coin."""
    _report_run(asyncio.run(run_reconcile(get_engine())))


@recompute_app.command("prices")
def recompute_prices() -> None:
    """Rebuild price estimates from market observations (realized sales first)."""
    _report_run(asyncio.run(run_recompute_prices(get_engine())))


@recompute_app.command("rarity")
def recompute_rarity() -> None:
    """Rebuild the 0-100 rarity index for every issue with a known mintage."""
    _report_run(asyncio.run(run_recompute_rarity(get_engine())))


@app.command("serve")
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    scheduler: Annotated[bool, typer.Option(help="Run source syncs on their cadence")] = True,
) -> None:
    """Start the API (docs at /docs) and the background scheduler."""
    import uvicorn

    from euro2core.api.app import create_app

    uvicorn.run(create_app(scheduler=scheduler), host=host, port=port, log_level="info")


def _report_run(run) -> None:
    status = str(getattr(run.status, "value", run.status))
    typer.echo(f"{status}: {json.dumps(run.stats, ensure_ascii=False)}")
    if status != "succeeded":
        typer.echo(run.error or "", err=True)
        raise typer.Exit(code=1)


def _require_ebay_keys(settings) -> None:
    if settings.ebay_client_id and settings.ebay_client_secret:
        return
    typer.echo(
        "EBAY_CLIENT_ID / EBAY_CLIENT_SECRET are not set in .env. Create a production keyset at "
        "https://developer.ebay.com (My Account > Application Keys) and try again.",
        err=True,
    )
    raise typer.Exit(code=2)
