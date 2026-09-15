"""Admin-editable settings: encrypted secrets, env fallback, masked view."""

import pytest
from sqlalchemy import select

from euro2core.config import Settings
from euro2core.domain.models import AppSetting
from euro2core.platform.credentials import credentials
from euro2core.platform.settings_store import SettingsStore

pytestmark = pytest.mark.integration

SECRET = "unit-test-secret-key-0123456789"


async def test_secrets_are_encrypted_at_rest_and_masked_in_the_view(session):
    store = SettingsStore(session, SECRET)
    await store.set("numista_api_key", "abcdefgh12345678")
    await store.set("deal_threshold_pct", 20)
    await session.commit()

    row = await session.get(AppSetting, "numista_api_key")
    assert row.is_secret and "abcdefgh" not in row.value  # ciphertext only
    assert await store.get("numista_api_key") == "abcdefgh12345678"
    assert await store.get("deal_threshold_pct") == 20.0

    view = {v["key"]: v for v in await store.view({})}
    assert view["numista_api_key"]["value"] == "••••5678"
    assert view["numista_api_key"]["source"] == "app" and view["numista_api_key"]["set"]
    assert view["deal_threshold_pct"]["value"] == 20.0
    assert view["user_agent"]["source"] == "default"


async def test_env_is_the_base_layer_and_the_app_overrides_it(session):
    store = SettingsStore(session, SECRET)
    env = Settings(
        _env_file=None,
        secret_key=SECRET,
        numista_api_key="from-env",
        ebay_client_id="",
        ebay_client_secret="",
    )
    creds = await credentials(session, env)
    assert creds.numista_api_key == "from-env" and not creds.has_ebay
    view = {v["key"]: v for v in await store.view({"numista_api_key": "from-env"})}
    assert view["numista_api_key"]["source"] == "env"

    await store.set("numista_api_key", "from-app")
    await store.set("ebay_client_id", "id")
    await store.set("ebay_client_secret", "sec")
    await store.set("public_origins", "https://a.example, https://b.example")
    await session.commit()
    creds = await credentials(session, env)
    assert creds.numista_api_key == "from-app" and creds.has_ebay
    assert creds.public_origins == ["https://a.example", "https://b.example"]


async def test_a_rotated_secret_key_falls_back_instead_of_crashing(session):
    await SettingsStore(session, SECRET).set("ebay_client_secret", "s3cret")
    await session.commit()
    other = SettingsStore(session, "a-different-key")
    assert await other.get("ebay_client_secret", "env-fallback") == "env-fallback"
    assert await other.get("ebay_client_secret") == ""


async def test_delete_restores_the_default(session):
    store = SettingsStore(session, SECRET)
    await store.set("user_agent", "custom/1.0")
    await store.delete("user_agent")
    await session.commit()
    assert await store.get("user_agent") == "euro2-core/0.1"
    assert (await session.scalars(select(AppSetting))).all() == []
