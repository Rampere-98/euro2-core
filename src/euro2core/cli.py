from pathlib import Path

import typer

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
def sync_ecb() -> None:
    raise typer.Exit(code=_not_implemented("sync ecb"))


@sync_app.command("numista")
def sync_numista() -> None:
    raise typer.Exit(code=_not_implemented("sync numista"))


@sync_app.command("ebay")
def sync_ebay() -> None:
    raise typer.Exit(code=_not_implemented("sync ebay"))


@recompute_app.command("prices")
def recompute_prices() -> None:
    raise typer.Exit(code=_not_implemented("recompute prices"))


@recompute_app.command("rarity")
def recompute_rarity() -> None:
    raise typer.Exit(code=_not_implemented("recompute rarity"))


@app.command("serve")
def serve() -> None:
    """Start the API and the background scheduler."""
    raise typer.Exit(code=_not_implemented("serve"))


def _not_implemented(name: str) -> int:
    typer.echo(f"{name}: not implemented yet", err=True)
    return 2
