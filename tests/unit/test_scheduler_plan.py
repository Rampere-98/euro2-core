from datetime import UTC, datetime, timedelta

from euro2core.config import Settings
from euro2core.domain.enums import SyncStatus
from euro2core.scheduler.service import (
    EBAY_JOBS,
    JOB_SPECS,
    NUMISTA_JOBS,
    RETRY_DELAY,
    STARTUP_DELAY,
    enabled_job_specs,
    plan_after_result,
    plan_next_run,
)

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def test_never_run_job_starts_shortly_after_boot():
    assert plan_next_run(None, timedelta(hours=24), NOW) == NOW + STARTUP_DELAY


def test_overdue_job_runs_shortly_after_boot_not_immediately():
    last = NOW - timedelta(days=3)
    assert plan_next_run(last, timedelta(hours=24), NOW) == NOW + STARTUP_DELAY


def test_recent_job_waits_for_its_interval():
    last = NOW - timedelta(hours=5)
    assert plan_next_run(last, timedelta(hours=24), NOW) == last + timedelta(hours=24)


def test_failed_run_is_retried_soon_and_success_waits_the_full_interval():
    interval = timedelta(days=7)
    assert plan_after_result(SyncStatus.FAILED, interval, NOW) == NOW + RETRY_DELAY
    assert plan_after_result(SyncStatus.SUCCEEDED, interval, NOW) == NOW + interval
    assert interval > RETRY_DELAY


def test_job_specs_cover_the_approved_cadences():
    specs = {name: interval for name, interval, _ in JOB_SPECS}
    assert specs["ecb_discover"] == timedelta(hours=24)
    assert specs["numista_catalog"] == timedelta(days=7)
    assert specs["numista_prices"] == timedelta(hours=24)
    assert specs["recompute_prices"] == timedelta(hours=24)
    assert specs["recompute_rarity"] == timedelta(hours=24)
    assert specs["ebay_market"] == timedelta(hours=72)
    assert specs["ebay_hot"] == timedelta(hours=6)
    assert specs["auction_close_check"] == timedelta(hours=1)
    assert specs["embed_images"] == timedelta(hours=24)
    assert specs["publish_news"] == timedelta(hours=1)
    assert specs["embed_types"] == timedelta(hours=24)


def test_jobs_without_credentials_are_not_scheduled():
    settings = Settings(
        _env_file=None, numista_api_key="", ebay_client_id="", ebay_client_secret=""
    )
    ids = {job_id for job_id, _, _ in enabled_job_specs(settings)}
    assert "ecb_discover" in ids and "recompute_prices" in ids
    assert not ids & (NUMISTA_JOBS | EBAY_JOBS)
    settings = Settings(
        _env_file=None, numista_api_key="k", ebay_client_id="", ebay_client_secret=""
    )
    ids = {job_id for job_id, _, _ in enabled_job_specs(settings)}
    assert ids >= NUMISTA_JOBS
    assert "ebay_market" not in ids
