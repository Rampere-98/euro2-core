import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://euro2:euro2@localhost:5432/euro2"  # type: ignore[assignment]
    )
    numista_api_key: str = ""
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    data_dir: Path = Path("./data")
    user_agent: str = "euro2-core/0.1"
    # Signs login tokens, certificates and the encrypted settings store. Left empty it is
    # generated once and kept in data/secret.key, so nothing has to be edited by hand.
    secret_key: str = ""
    token_hours: int = 24 * 30
    # Comma-separated browser origins allowed to call the API (empty = any, for development)
    public_origins: str = ""
    # Behind Cloudflare Tunnel / a reverse proxy: take the visitor's IP from the proxy headers
    trust_proxy: bool = False

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    def origins(self) -> list[str]:
        return [o.strip() for o in self.public_origins.split(",") if o.strip()]


def _ensure_secret(settings: Settings) -> Settings:
    if settings.secret_key and settings.secret_key != "change-me-in-.env":
        return settings
    path = settings.data_dir / "secret.key"
    if path.exists():
        settings.secret_key = path.read_text(encoding="utf-8").strip()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        settings.secret_key = secrets.token_urlsafe(48)
        path.write_text(settings.secret_key, encoding="utf-8")
    return settings


@lru_cache
def get_settings() -> Settings:
    return _ensure_secret(Settings())
