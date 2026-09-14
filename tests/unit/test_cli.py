from typer.testing import CliRunner

from euro2core import cli

runner = CliRunner()


def test_help_lists_top_level_commands():
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("db", "sync", "recompute", "serve"):
        assert cmd in result.output


def test_sync_ecb_runs_the_discover_job_and_reports_stats(monkeypatch):
    class FakeRun:
        status = "succeeded"
        stats = {"types_created": 3, "years": [2004]}
        error = None

    async def fake_job(engine, **kwargs):
        return FakeRun()

    monkeypatch.setattr(cli, "run_ecb_discover", fake_job)
    monkeypatch.setattr(cli, "get_engine", lambda: object())
    result = runner.invoke(cli.app, ["sync", "ecb"])
    assert result.exit_code == 0, result.output
    assert "succeeded" in result.output
    assert "types_created" in result.output


def test_sync_ecb_exits_non_zero_when_the_run_failed(monkeypatch):
    class FakeRun:
        status = "failed"
        stats = {}
        error = "boom"

    async def fake_job(engine, **kwargs):
        return FakeRun()

    monkeypatch.setattr(cli, "run_ecb_discover", fake_job)
    monkeypatch.setattr(cli, "get_engine", lambda: object())
    result = runner.invoke(cli.app, ["sync", "ecb"])
    assert result.exit_code == 1
    assert "boom" in result.output


def test_db_upgrade_runs_alembic_to_head(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        cli, "_alembic_upgrade", lambda revision: calls.append(("upgrade", revision))
    )
    result = runner.invoke(cli.app, ["db", "upgrade"])
    assert result.exit_code == 0, result.output
    assert calls == [("upgrade", "head")]
