# ruff: noqa: F811  (fixtures imported from sibling test modules are re-bound as parameters)
"""Admin panel API: settings, key tests, jobs, users, logs, stats; admins only."""

import httpx
import pytest
import respx

from euro2core.domain.models import AppSetting
from euro2core.sources.numista.client import NUMISTA_API_BASE
from tests.integration.test_platform import _signup, catalog, client  # noqa: F401

pytestmark = pytest.mark.integration


async def test_only_admins_reach_the_panel(client, catalog):
    admin = await _signup(client, "owner@example.org")
    user = await _signup(client, "plain@example.org")
    assert (await client.get("/admin/settings")).status_code == 401
    assert (await client.get("/admin/settings", headers=user)).status_code == 403
    assert (await client.get("/admin/settings", headers=admin)).status_code == 200


async def test_settings_are_saved_encrypted_and_shown_masked(client, catalog, session):
    admin = await _signup(client, "owner@example.org")
    r = await client.put(
        "/admin/settings",
        json={"values": {"numista_api_key": "secret-key-98765", "deal_threshold_pct": 25}},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    view = {v["key"]: v for v in r.json()}
    assert view["numista_api_key"]["value"] == "••••8765"
    assert view["numista_api_key"]["source"] == "app"
    assert view["deal_threshold_pct"]["value"] == 25
    row = await session.get(AppSetting, "numista_api_key")
    assert row is not None and "secret-key" not in row.value
    # clearing goes back to env/default
    r = await client.put("/admin/settings", json={"values": {"numista_api_key": ""}}, headers=admin)
    assert {v["key"]: v for v in r.json()}["numista_api_key"]["set"] is False
    assert (
        await client.put("/admin/settings", json={"values": {"nope": 1}}, headers=admin)
    ).status_code == 422


@respx.mock
async def test_key_test_makes_one_real_call(client, catalog):
    admin = await _signup(client, "owner@example.org")
    r = await client.post("/admin/settings/test", json={"source": "numista"}, headers=admin)
    assert r.json() == {"ok": False, "detail": "no hay clave de Numista"}
    await client.put(
        "/admin/settings", json={"values": {"numista_api_key": "k-123456"}}, headers=admin
    )
    respx.get(f"{NUMISTA_API_BASE}/types/2169").mock(
        return_value=httpx.Response(200, json={"title": "2 Euro (Schleswig-Holstein)"})
    )
    r = await client.post("/admin/settings/test", json={"source": "numista"}, headers=admin)
    assert r.json()["ok"] is True and "Schleswig" in r.json()["detail"]


async def test_jobs_can_be_paused_rescheduled_and_run(client, catalog, monkeypatch):
    admin = await _signup(client, "owner@example.org")
    jobs = {j["job"]: j for j in (await client.get("/admin/jobs", headers=admin)).json()}
    assert jobs["numista_catalog"]["needs"] == "numista"
    assert jobs["numista_catalog"]["has_credentials"] is False
    assert jobs["ecb_discover"]["interval_hours"] == 24

    r = await client.patch(
        "/admin/jobs/publish_news", json={"enabled": False, "interval_hours": 2}, headers=admin
    )
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert r.json()["interval_hours"] == 2
    assert (
        await client.patch("/admin/jobs/nope", json={"enabled": True}, headers=admin)
    ).status_code == 404

    from datetime import timedelta

    async def fake(engine, settings):
        return None

    monkeypatch.setattr(
        "euro2core.api.routers.admin.JOB_SPECS", (("ecb_discover", timedelta(hours=24), fake),)
    )
    assert (await client.post("/admin/jobs/ecb_discover/run", headers=admin)).status_code == 202
    assert (await client.post("/admin/jobs/nope/run", headers=admin)).status_code == 404


async def test_users_roles_logs_and_stats(client, catalog):
    admin = await _signup(client, "owner@example.org")
    other = await _signup(client, "someone@example.org", name="Alguien")
    users = (await client.get("/admin/users", params={"q": "alguien"}, headers=admin)).json()
    assert [u["display_name"] for u in users] == ["Alguien"]
    r = await client.patch(
        f"/admin/users/{other['_id']}", json={"role": "expert", "plan": "pro"}, headers=admin
    )
    assert r.json()["role"] == "expert" and r.json()["plan"] == "pro"
    me = (await client.get("/me", headers=admin)).json()
    assert (
        await client.patch(f"/admin/users/{me['id']}", json={"role": "user"}, headers=admin)
    ).status_code == 409
    logs = (await client.get("/admin/logs", headers=admin)).json()
    assert isinstance(logs, list)
    stats = (await client.get("/admin/stats", headers=admin)).json()
    assert stats["types"] >= 1 and stats["users"] == 2
    version = (await client.get("/admin/version", headers=admin)).json()
    assert version["version"] and version["updater"] is False
    assert (await client.post("/admin/update", headers=admin)).status_code == 501


async def test_registration_can_be_closed_from_the_panel(client, catalog):
    admin = await _signup(client, "owner@example.org")
    await client.put(
        "/admin/settings", json={"values": {"registration_open": False}}, headers=admin
    )
    r = await client.post(
        "/auth/register",
        json={"email": "late@example.org", "password": "secret-pass-1", "display_name": "L"},
    )
    assert r.status_code == 403


async def test_stats_break_identifications_down_by_device(client, catalog, session):
    from euro2core.domain.models import Identification

    admin = await _signup(client, "owner@example.org")
    session.add_all(
        [
            Identification(found_circle=True, candidates=[], device="ios", pwa=True),
            Identification(found_circle=True, candidates=[], device="ios", pwa=False),
            Identification(found_circle=False, candidates=[], device="android", pwa=False),
            Identification(found_circle=False, candidates=[]),
        ]
    )
    await session.commit()
    stats = (await client.get("/admin/stats", headers=admin)).json()
    assert stats["identifications_30d_by_device"] == {"ios": 2, "android": 1, "unknown": 1}
    assert stats["identifications_30d_pwa"] == 1
