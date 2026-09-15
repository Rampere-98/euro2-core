from datetime import UTC, datetime, timedelta

from euro2core.domain.enums import SyncStatus
from euro2core.scheduler.service import (
    JOB_SPECS,
    RETRY_DELAY,
    STARTUP_DELAY,
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


def test_skipped_runs_wait_the_full_cadence_and_failures_retry_soon():
    interval = timedelta(hours=24)
    assert plan_after_result(SyncStatus.SKIPPED, interval, NOW) == NOW + interval
    assert plan_after_result(SyncStatus.FAILED, interval, NOW) == NOW + RETRY_DELAY


def test_a_recent_failure_keeps_its_retry_delay_across_restarts():
    # Numista pauses the job when the daily quota is gone; restarting the server must not
    # fire it again straight away and burn the next day's quota in fifteen seconds
    failed = NOW - timedelta(minutes=10)
    planned = plan_next_run(None, timedelta(hours=24), NOW, last_failure=failed)
    assert planned == failed + RETRY_DELAY
    # an old failure (older than the retry delay) no longer holds the job back
    old = NOW - timedelta(hours=3)
    assert plan_next_run(None, timedelta(hours=24), NOW, last_failure=old) == NOW + STARTUP_DELAY
    # a success after the failure clears it
    assert plan_next_run(
        NOW - timedelta(minutes=5), timedelta(hours=24), NOW, last_failure=failed
    ) == NOW - timedelta(minutes=5) + timedelta(hours=24)


def test_due_jobs_are_staggered_at_boot_instead_of_firing_together():
    slots = [plan_next_run(None, timedelta(hours=24), NOW, slot=i) for i in range(4)]
    assert slots[0] == NOW + STARTUP_DELAY
    assert slots == sorted(slots) and len(set(slots)) == 4
    assert slots[-1] - slots[0] <= timedelta(minutes=5)
