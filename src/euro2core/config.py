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
    # Signs login tokens and digital certificates; set a long random value in .env
    secret_key: str = "change-me-in-.env"
    token_hours: int = 24 * 30

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"


@lru_cache
def get_settings() -> Settings:
    return Settings()
