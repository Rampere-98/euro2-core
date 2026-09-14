from datetime import UTC, datetime, timedelta

from euro2core.scheduler.service import JOB_SPECS, STARTUP_DELAY, plan_next_run

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def test_never_run_job_starts_shortly_after_boot():
    assert plan_next_run(None, timedelta(hours=24), NOW) == NOW + STARTUP_DELAY


def test_overdue_job_runs_shortly_after_boot_not_immediately():
    last = NOW - timedelta(days=3)
    assert plan_next_run(last, timedelta(hours=24), NOW) == NOW + STARTUP_DELAY


def test_recent_job_waits_for_its_interval():
    last = NOW - timedelta(hours=5)
    assert plan_next_run(last, timedelta(hours=24), NOW) == last + timedelta(hours=24)


def test_job_specs_cover_the_approved_cadences():
    specs = {name: interval for name, interval, _ in JOB_SPECS}
    assert specs["ecb_discover"] == timedelta(hours=24)
    assert specs["numista_catalog"] == timedelta(days=7)
