"""R16 §C: dated day metrics, the stale flag, sync status and the auto-sync guard.
Clocks are pinned through the modules' seams — nothing depends on the wall clock."""

import datetime as dt

import pytest
from django.utils import timezone

from apps.health import freshness
from apps.ingest import sync_status
from apps.ingest.garmin import SyncResult
from tests.r7_helpers import wellness


def at_local(athlete, hour):
    """An aware datetime: today in the athlete's timezone at `hour`:00."""
    tz = athlete.local_now.tzinfo
    return dt.datetime.combine(athlete.local_today, dt.time(hour), tzinfo=tz)


@pytest.fixture
def clock(monkeypatch, athlete):
    state = {"hour": 9}
    monkeypatch.setattr(freshness, "_local_now", lambda a: at_local(a, state["hour"]))
    monkeypatch.setattr(sync_status, "_now",
                        lambda: at_local(athlete, state["hour"]).astimezone(dt.timezone.utc))
    return state


def yesterday(athlete, n=1):
    return athlete.local_today - dt.timedelta(days=n)


# --- freshness ------------------------------------------------------------------------------

def test_today_is_stale_until_last_night_syncs(api, athlete, clock):
    for n in range(2, 12):                  # resting-HR baseline (needs >= 7 nights)
        wellness(athlete, yesterday(athlete, n), resting_hr=55)
    wellness(athlete, yesterday(athlete), sleep_seconds=7 * 3600, training_readiness=60,
             resting_hr=55, body_battery_high=80)
    body = api.get("/api/today/").json()
    fresh = body["freshness"]
    assert body["as_of"] and fresh["stale"] is True and fresh["stale_reason"] == "both_missing"
    assert fresh["stale_text"].startswith("Showing yesterday's sleep")
    assert fresh["latest_sleep_date"] == str(yesterday(athlete))
    assert fresh["today"] == str(athlete.local_today)
    by_signal = {r["signal"]: r for r in body["reasons"]}
    assert by_signal["rhr"]["date"] == str(yesterday(athlete))          # yesterday's value
    assert all("date" in r for r in body["reasons"])

    wellness(athlete, athlete.local_today, sleep_seconds=7 * 3600, training_readiness=70,
             resting_hr=54, hrv_overnight_avg=50)
    body = api.get("/api/today/").json()
    assert body["freshness"]["stale"] is False and body["freshness"]["stale_text"] is None
    by_signal = {r["signal"]: r for r in body["reasons"]}
    assert by_signal["rhr"]["date"] == by_signal["sleep"]["date"] == str(athlete.local_today)


def test_not_stale_before_5am_or_without_data(api, athlete, clock):
    assert api.get("/api/today/").json()["freshness"]["stale"] is False      # no data at all
    wellness(athlete, yesterday(athlete), sleep_seconds=7 * 3600)
    clock["hour"] = 4
    assert api.get("/api/today/").json()["freshness"]["stale"] is False
    clock["hour"] = 6
    fresh = api.get("/api/today/").json()["freshness"]
    assert fresh["stale"] and fresh["stale_reason"] == "sleep_missing"      # no readiness ever


def test_other_endpoints_carry_dates(api, athlete, clock, monkeypatch):
    monkeypatch.setattr("apps.health.briefing.ready", lambda a: True)   # not the real clock
    wellness(athlete, yesterday(athlete, 2), sleep_seconds=6 * 3600, training_readiness=50,
             hrv_overnight_avg=45, resting_hr=56, body_battery_high=70, stress_avg=30,
             vo2max=44.0)
    wellness(athlete, yesterday(athlete), sleep_seconds=7 * 3600, training_readiness=61)
    insights = api.get("/api/insights/").json()
    assert insights["freshness"]["stale"] is True and insights["as_of"]
    assert insights["readiness"]["date"] == str(yesterday(athlete))
    assert insights["hrv"]["last_night_date"] == str(yesterday(athlete, 2))
    assert insights["resting_hr"]["current_date"] == str(yesterday(athlete, 2))
    assert insights["vo2max"]["date"] == str(yesterday(athlete, 2))
    assert insights["body_battery"]["date"] == insights["stress"]["date"] == str(
        yesterday(athlete, 2))
    sleep = api.get("/api/health/sleep/").json()
    assert sleep["last_night_date"] == str(yesterday(athlete)) and sleep["as_of"]
    forecast = api.get("/api/health/readiness-forecast/").json()
    assert forecast["today"]["date"] == str(yesterday(athlete)) and forecast["as_of"]
    summary = api.get("/api/health/day/summary/").json()
    assert summary["freshness"]["stale"] is True and summary["as_of"]
    clock["hour"] = 9
    brief = api.get("/api/briefing/today/").json()
    assert brief["freshness"]["stale"] is True and brief["as_of"]
    assert brief["readiness"]["date"] is None
    wellness(athlete, athlete.local_today, sleep_seconds=7 * 3600, training_readiness=66)
    brief = api.get("/api/briefing/today/").json()
    assert brief["readiness"]["date"] == str(athlete.local_today)
    assert brief["freshness"]["stale"] is False


def test_freshness_is_per_athlete(api, other_api, athlete, other_athlete, clock):
    wellness(athlete, yesterday(athlete), sleep_seconds=7 * 3600)
    assert api.get("/api/today/").json()["freshness"]["stale"] is True
    assert other_api.get("/api/today/").json()["freshness"]["latest_sleep_date"] is None


# --- sync status / auto-sync ------------------------------------------------------------------------

@pytest.fixture
def connected(athlete, clock):
    athlete.garmin_connected = True
    athlete.garmin_last_sync = at_local(athlete, 7).astimezone(dt.timezone.utc)   # 2 h ago
    athlete.save()
    return athlete


@pytest.fixture
def garmin(monkeypatch):
    calls = []

    def fake_sync(athlete, limit=None):
        calls.append(limit)
        athlete.garmin_last_sync = sync_status._now()
        athlete.save(update_fields=["garmin_last_sync"])
        return SyncResult(imported=1)

    monkeypatch.setattr("apps.ingest.views.sync_athlete", fake_sync)
    monkeypatch.setattr("apps.ingest.tasks.garmin_blocked", lambda: False)
    monkeypatch.setattr("apps.ingest.tasks.queue_slow", lambda a: False)
    return calls


def test_status_not_connected(api, athlete, clock):
    body = api.get("/api/sync/status/").json()
    assert body == {"connected": False, "last_sync_at": None, "last_attempt_at": None,
                    "running": False, "breaker_open": False, "can_sync_now": False,
                    "auto_sync_due": False, "next_auto_sync_at": None, "min_interval_s": 1800}
    r = api.post("/api/garmin/sync/", {"auto": True}, format="json")
    assert r.status_code == 200 and r.json()["skipped"] == "not_connected"


def test_auto_sync_runs_once_then_throttles(api, connected, garmin, clock):
    status = api.get("/api/sync/status/").json()
    assert status["can_sync_now"] and status["auto_sync_due"] and status["next_auto_sync_at"] is None
    r = api.post("/api/garmin/sync/", {"auto": True}, format="json")
    assert r.status_code == 200 and r.json()["imported"] == 1 and garmin == [20]
    after = r.json()["status"]
    assert after["last_attempt_at"] and after["auto_sync_due"] is False
    assert after["running"] is False and after["next_auto_sync_at"]
    again = api.post("/api/garmin/sync/", {"auto": True}, format="json").json()
    assert again["skipped"] == "recent" and garmin == [20]          # Garmin not called
    clock["hour"] = 11                                               # 2 h later
    assert api.get("/api/sync/status/").json()["auto_sync_due"] is True
    assert "imported" in api.post("/api/garmin/sync/", {"auto": True}, format="json").json()


def test_recent_manual_sync_blocks_auto(api, connected, garmin, clock):
    connected.garmin_last_sync = at_local(connected, 9).astimezone(dt.timezone.utc) \
        - dt.timedelta(minutes=10)
    connected.save()
    assert api.get("/api/sync/status/").json()["auto_sync_due"] is False
    assert api.post("/api/garmin/sync/", {"auto": True}, format="json").json()["skipped"] == "recent"
    # A manual sync is not throttled by the 30-min rule.
    r = api.post("/api/garmin/sync/", {}, format="json")
    assert r.status_code == 200 and r.json()["imported"] == 1


def test_auto_sync_too_early_and_breaker(api, connected, garmin, clock, monkeypatch):
    clock["hour"] = 4
    body = api.post("/api/garmin/sync/", {"auto": True}, format="json").json()
    assert body["skipped"] == "too_early" and body["status"]["auto_sync_due"] is False
    assert body["status"]["next_auto_sync_at"]
    clock["hour"] = 9
    monkeypatch.setattr("apps.ingest.tasks.garmin_blocked", lambda: True)
    body = api.post("/api/garmin/sync/", {"auto": True}, format="json").json()
    assert body["skipped"] == "breaker_open" and body["status"]["breaker_open"] is True
    assert body["status"]["can_sync_now"] is False and garmin == []


def test_never_two_syncs_at_once(api, connected, garmin, clock):
    with sync_status.sync_lock(connected):
        assert api.get("/api/sync/status/").json()["running"] is True
        body = api.post("/api/garmin/sync/", {"auto": True}, format="json").json()
        assert body["skipped"] == "running"
        r = api.post("/api/garmin/sync/", {}, format="json")
        assert r.status_code == 409
    assert garmin == []
    assert api.get("/api/sync/status/").json()["running"] is False


def test_scheduled_sync_skips_while_running(connected, monkeypatch):
    from apps.ingest import tasks

    monkeypatch.setattr(tasks, "garmin_blocked", lambda: False)
    monkeypatch.setattr(tasks, "sync_athlete", lambda a: pytest.fail("must not sync"))
    with sync_status.sync_lock(connected):
        assert tasks.sync_one.run(connected.pk) == {"skipped": "running"}


def test_sync_status_is_per_athlete(api, other_api, connected, garmin, clock):
    api.post("/api/garmin/sync/", {"auto": True}, format="json")
    other = other_api.get("/api/sync/status/").json()
    assert other["last_attempt_at"] is None and other["connected"] is False
