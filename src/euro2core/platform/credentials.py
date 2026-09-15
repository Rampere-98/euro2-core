"""Effective configuration = `.env` (base) overridden by what the admin saved in the app."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.config import Settings, get_settings
from euro2core.platform.settings_store import SettingsStore


@dataclass(frozen=True)
class Credentials:
    numista_api_key: str
    ebay_client_id: str
    ebay_client_secret: str
    user_agent: str
    public_origins: list[str]
    deal_threshold_pct: float
    registration_open: bool
    replica_words: list[str]
    altered_words: list[str]
    mintage_buckets: list[list[float]]
    duckdns_domain: str
    duckdns_token: str

    @property
    def has_numista(self) -> bool:
        return bool(self.numista_api_key)

    @property
    def has_ebay(self) -> bool:
        return bool(self.ebay_client_id and self.ebay_client_secret)


async def credentials(session: AsyncSession, settings: Settings | None = None) -> Credentials:
    settings = settings or get_settings()
    store = SettingsStore(session, settings.secret_key)
    origins = await store.get("public_origins", settings.public_origins)
    return Credentials(
        numista_api_key=await store.get("numista_api_key", settings.numista_api_key),
        ebay_client_id=await store.get("ebay_client_id", settings.ebay_client_id),
        ebay_client_secret=await store.get("ebay_client_secret", settings.ebay_client_secret),
        user_agent=await store.get("user_agent", settings.user_agent),
        public_origins=[o.strip() for o in str(origins).split(",") if o.strip()],
        deal_threshold_pct=float(await store.get("deal_threshold_pct")),
        registration_open=bool(await store.get("registration_open")),
        replica_words=list(await store.get("replica_words")),
        altered_words=list(await store.get("altered_words")),
        mintage_buckets=list(await store.get("mintage_buckets")),
        duckdns_domain=await store.get("duckdns_domain"),
        duckdns_token=await store.get("duckdns_token"),
    )
