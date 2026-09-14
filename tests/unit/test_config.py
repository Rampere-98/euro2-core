from pathlib import Path

from euro2core.config import Settings


def test_defaults_point_to_local_docker_db(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings(_env_file=None)
    assert str(s.database_url) == "postgresql+asyncpg://euro2:euro2@localhost:5432/euro2"
    assert s.numista_api_key == ""


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("NUMISTA_API_KEY", "abc")
    monkeypatch.setenv("DATA_DIR", "C:/tmp/euro2")
    s = Settings(_env_file=None)
    assert s.numista_api_key == "abc"
    assert s.images_dir == Path("C:/tmp/euro2") / "images"
