from typer.testing import CliRunner

from euro2core import cli

runner = CliRunner()


def test_help_lists_top_level_commands():
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("db", "sync", "recompute", "serve"):
        assert cmd in result.output


def test_db_upgrade_runs_alembic_to_head(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        cli, "_alembic_upgrade", lambda revision: calls.append(("upgrade", revision))
    )
    result = runner.invoke(cli.app, ["db", "upgrade"])
    assert result.exit_code == 0, result.output
    assert calls == [("upgrade", "head")]
