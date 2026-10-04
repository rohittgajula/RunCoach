"""R6 §1 sync depth and §6 wellness fields. Garmin is always mocked."""

import datetime as dt

import pytest

from apps.ingest import garmin
from apps.ingest.garmin_wellness import fields_from_raw, sync_wellness
from apps.ingest.models import DailyMetrics

TODAY = dt.date(2026, 10, 4)


class FakeListing:
    """get_activities(start, limit) over a list of entries, newest first."""

    def __init__(self, entries):
        self.entries = entries
        self.calls = []

    def get_activities(self, start, limit):
        self.calls.append((start, limit))
        return self.entries[start:start + limit]


def entries(n, start_day=TODAY, step_days=2, first_id=10_000):
    return [{"activityId": first_id - i,
             "startTimeLocal": f"{start_day - dt.timedelta(days=i * step_days)} 07:00:00"}
            for i in range(n)]


def test_backfill_pages_until_the_cutoff():
    listing = entries(250)                           # 500 days back
    client = FakeListing(listing)
    cutoff = TODAY - dt.timedelta(days=365)
    found, done = garmin.list_new_activities(client, set(), backfill=True, cutoff=cutoff)
    assert done
    assert client.calls == [(0, 100), (100, 100)]      # stopped inside the second page
    assert all(dt.date.fromisoformat(e["startTimeLocal"][:10]) >= cutoff for e in found)
    assert len(found) == 183                            # days 0..364 every 2 days


def test_backfill_stops_when_garmin_runs_out():
    client = FakeListing(entries(30))
    found, _ = garmin.list_new_activities(client, set(), backfill=True,
                                          cutoff=TODAY - dt.timedelta(days=365))
    assert len(found) == 30 and client.calls == [(0, 100)]


def test_incremental_stops_at_a_known_id():
    listing = entries(60)
    client = FakeListing(listing)
    known = {listing[25]["activityId"]}
    found, _ = garmin.list_new_activities(client, known, backfill=False, cutoff=TODAY)
    assert [e["activityId"] for e in found] == [e["activityId"] for e in listing[:25]]
    assert client.calls == [(0, 20), (20, 20)]


def test_incremental_is_capped_at_100():
    client = FakeListing(entries(400))
    found, _ = garmin.list_new_activities(client, set(), backfill=False, cutoff=TODAY)
    assert len(found) == 100 and len(client.calls) == 5


def test_listing_rate_limit_raises():
    class Limited:
        def get_activities(self, start, limit):
            raise Exception("429 Too Many Requests")

    with pytest.raises(garmin.GarminRateLimited):
        garmin.list_new_activities(Limited(), set(), backfill=True, cutoff=TODAY)


def test_sync_athlete_backfills_once(athlete, monkeypatch):
    """First sync pages deep and sets the flag; the next one is incremental."""
    seen = {}

    def fake_list(client, known, *, backfill, cutoff):
        seen.setdefault("modes", []).append(backfill)
        return [], True

    monkeypatch.setattr(garmin, "_client", lambda a: object())
    monkeypatch.setattr(garmin, "list_new_activities", fake_list)
    monkeypatch.setattr("apps.ingest.garmin_wellness.sync_wellness",
                        lambda a, c: {"days_written": 0, "rate_limited": False})
    garmin.sync_athlete(athlete)
    athlete.refresh_from_db()
    assert athlete.garmin_backfilled
    from tests.r6_helpers import make_activity

    make_activity(athlete, athlete.local_today, garmin_id=5)
    garmin.sync_athlete(athlete)
    assert seen["modes"] == [True, False]


class FakeWellness:
    """Every endpoint answers except the ones named in `broken`."""

    def __init__(self, broken=(), limited=()):
        self.broken, self.limited = set(broken), set(limited)
        self.calls = []

    def _maybe(self, name, value):
        self.calls.append(name)
        if name in self.limited:
            raise Exception("429 TooManyRequests")
        if name in self.broken:
            raise Exception("boom")
        return value

    def get_sleep_data(self, iso):
        return self._maybe("sleep", {"dailySleepDTO": {
            "sleepTimeSeconds": 25200, "lightSleepSeconds": 14000, "deepSleepSeconds": 5000,
            "remSleepSeconds": 5000, "awakeSleepSeconds": 1200,
            "sleepScores": {"overall": {"value": 81}}}})

    def get_training_readiness(self, iso):
        return self._maybe("readiness", [{"score": 66, "level": "MODERATE"}])

    def get_training_status(self, iso):
        return self._maybe("status", {})

    def get_hrv_data(self, iso):
        return self._maybe("hrv", {"hrvSummary": {
            "status": "BALANCED", "lastNightAvg": 48, "weeklyAvg": 50,
            "baseline": {"balancedLow": 44, "balancedUpper": 58}}})

    def get_rhr_day(self, iso):
        return self._maybe("rhr", {})

    def get_stats(self, iso):
        return self._maybe("stats", {"totalSteps": 9000, "averageStressLevel": 30,
                                     "bodyBatteryHighestValue": 80,
                                     "bodyBatteryLowestValue": 20,
                                     "moderateIntensityMinutes": 10,
                                     "vigorousIntensityMinutes": 5,
                                     "averageSpo2": 96, "avgWakingRespirationValue": 15.0})

    def get_max_metrics(self, iso):
        return self._maybe("vo2", [{"generic": {"vo2MaxPreciseValue": 41.5}}])

    def get_respiration_data(self, iso):
        return self._maybe("respiration", {"avgWakingRespirationValue": 15.0,
                                           "avgSleepRespirationValue": 13.5})

    def get_race_predictions(self):
        return self._maybe("predictions", {"time5K": 1800, "time10K": 3800,
                                           "timeHalfMarathon": 8600, "timeMarathon": 18500})


def test_wellness_maps_every_new_field(athlete):
    sync_wellness(athlete, FakeWellness(), days=1)
    row = DailyMetrics.objects.get(athlete=athlete, metric_date=athlete.local_today)
    assert (row.hrv_weekly_avg, row.hrv_baseline_low, row.hrv_baseline_high) == (50, 44, 58)
    assert row.hrv_status == "BALANCED" and row.sleep_score == 81
    assert row.light_sleep_seconds == 14000 and row.respiration_sleep_avg == 13.5
    assert row.intensity_minutes == 20 and row.spo2_avg == 96 and row.vo2max == 41.5
    assert (row.race_pred_5k_s, row.race_pred_10k_s, row.race_pred_half_s,
            row.race_pred_marathon_s) == (1800, 3800, 8600, 18500)


def test_one_failing_endpoint_keeps_the_rest(athlete):
    sync_wellness(athlete, FakeWellness(broken={"hrv", "sleep"}), days=1)
    row = DailyMetrics.objects.get(athlete=athlete, metric_date=athlete.local_today)
    assert row.hrv_weekly_avg is None and row.sleep_score is None
    assert row.steps == 9000 and row.training_readiness == 66


def test_a_429_stops_the_wellness_run(athlete):
    client = FakeWellness(limited={"readiness"})
    result = sync_wellness(athlete, client, days=5)
    assert result["rate_limited"]
    assert client.calls.count("sleep") == 1            # stopped on the first day
    assert "predictions" not in client.calls


def test_first_sync_is_28_days_then_since_last(athlete):
    from apps.ingest.garmin_wellness import days_to_fetch

    assert days_to_fetch(athlete) == 28
    DailyMetrics.objects.create(athlete=athlete,
                                metric_date=athlete.local_today - dt.timedelta(days=3))
    assert days_to_fetch(athlete) == 4


def test_fields_from_raw_backfills_without_garmin():
    fields = fields_from_raw({"hrv": {"hrvSummary": {"weeklyAvg": 51,
                                                     "baseline": {"balancedLow": 40}}}})
    assert fields["hrv_weekly_avg"] == 51 and fields["hrv_baseline_low"] == 40
