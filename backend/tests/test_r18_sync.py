"""R18 §A: full refresh = full sync, the intraday / daily-totals root causes, run-aware
auto-sync and data_version. A fake Garmin client; clocks pinned through the seams — nothing
depends on the wall clock."""

import datetime as dt

import pytest

from apps.athletes import versioning
from apps.ingest import sync_jobs, sync_status
from apps.ingest.garmin import SyncResult
from apps.ingest.models import DailyMetrics, GarminProfile, IntradayDay
from tests.r7_helpers import make_workout


def at_local(athlete, hour, minute=0):
    tz = athlete.local_now.tzinfo
    return dt.datetime.combine(athlete.local_today, dt.time(hour, minute), tzinfo=tz)


@pytest.fixture
def clock(monkeypatch, athlete):
    state = {"hour": 9, "minute": 0}
    monkeypatch.setattr(sync_status, "_now",
                        lambda: at_local(athlete, state["hour"], state["minute"])
                        .astimezone(dt.timezone.utc))
    return state


class FakeGarmin:
    """The garminconnect methods the sync calls, answering from `steps` (today's total)."""

    def __init__(self, athlete, steps=5000, rate_limit=()):
        self.athlete, self.steps, self.rate_limit = athlete, steps, set(rate_limit)
        self.calls: list[str] = []

    def _hit(self, name):
        self.calls.append(name)
        if name in self.rate_limit:
            raise RuntimeError("429 Too Many Requests")

    # activities
    def get_activities(self, start, limit):
        self._hit("get_activities")
        return []

    # wellness (one day)
    def get_stats(self, iso):
        self._hit("get_stats")
        steps = self.steps if iso == self.athlete.local_today.isoformat() else 9000
        return {"totalSteps": steps, "dailyStepGoal": 8000, "averageStressLevel": 30}

    def get_sleep_data(self, iso):
        self._hit("get_sleep_data")
        return {"dailySleepDTO": {"sleepTimeSeconds": 7 * 3600, "sleepNeed": {"actual": 480 * 60}}}

    def get_training_readiness(self, iso):
        self._hit("get_training_readiness")
        return [{"score": 70, "level": "HIGH"}]

    def get_training_status(self, iso):
        return None

    def get_hrv_data(self, iso):
        return {"hrvSummary": {"status": "BALANCED", "lastNightAvg": 50}}

    def get_rhr_day(self, iso):
        return None

    def get_max_metrics(self, iso):
        return None

    def get_respiration_data(self, iso):
        return None

    def get_race_predictions(self):
        return None

    # intraday
    def _gmt(self, iso):
        return {"startTimestampGMT": f"{iso}T00:00:00.0", "startTimestampLocal": f"{iso}T05:30:00.0"}

    def get_heart_rates(self, iso):
        self._hit("get_heart_rates")
        return {**self._gmt(iso), "heartRateValues": [], "restingHeartRate": 55}

    def get_stress_data(self, iso):
        self._hit("get_stress_data")
        return {**self._gmt(iso), "stressValuesArray": [], "bodyBatteryValuesArray": []}

    def get_steps_data(self, iso):
        self._hit("get_steps_data")
        # 15-min buckets from 08:00 local (= 02:30 GMT)
        day = dt.date.fromisoformat(iso)
        start = dt.datetime.combine(day, dt.time(2, 30))
        return [{"startGMT": (start + dt.timedelta(minutes=15 * i)).isoformat(),
                 "steps": 100, "primaryActivityLevel": "active"} for i in range(4)]


@pytest.fixture
def connected(athlete, clock, monkeypatch):
    athlete.garmin_connected = True
    athlete.garmin_backfilled = True
    athlete.garmin_last_sync = at_local(athlete, 7).astimezone(dt.timezone.utc)
    athlete.save()
    GarminProfile.objects.update_or_create(athlete=athlete,
                                           defaults={"slow_synced_on": athlete.local_today})
    monkeypatch.setattr("apps.ingest.tasks.garmin_blocked", lambda: False)
    tripped: list = []
    monkeypatch.setattr("apps.ingest.tasks.trip_breaker", tripped.append)
    athlete.tripped = tripped
    return athlete


@pytest.fixture
def fake_client(connected, monkeypatch, settings):
    settings.GARMIN_SLOW_PAUSE_S = 0
    client = FakeGarmin(connected)
    monkeypatch.setattr("apps.ingest.garmin._client", lambda a: client)
    return client


# --- root cause 1: intraday refreshes on every sync ----------------------------------------------

def test_manual_sync_now_queues_intraday(api, connected, monkeypatch, no_real_garmin_queue):
    """Prod: DailyMetrics re-synced at 21:02 but IntradayDay stuck at 11:01 — the manual /
    auto sync path never queued the intraday fetch (only the 05:30 UTC beat did)."""
    monkeypatch.setattr("apps.ingest.views.sync_athlete",
                        lambda a, limit=None: SyncResult(imported=0))
    r = api.post("/api/garmin/sync/", {}, format="json")
    assert r.status_code == 200, r.json()
    assert "sync_intraday_one" in [q[0] for q in no_real_garmin_queue]
    assert isinstance(r.json()["data_version"], int)


# --- root cause 2: today's totals follow the latest wellness sync -------------------------------

def test_wellness_sync_refreshes_todays_intraday_totals(api, athlete, fake_client):
    from apps.ingest.garmin_intraday import refresh_aggregates
    from apps.ingest.garmin_wellness import sync_wellness

    today = athlete.local_today
    DailyMetrics.objects.create(athlete=athlete, metric_date=today, steps=1000,
                                raw={"stats": {"totalSteps": 1000}})
    row = IntradayDay.objects.create(athlete=athlete, day=today, utc_offset_min=330,
                                     steps=[[480, 1000, "active"]])
    refresh_aggregates(row)
    row.refresh_from_db()
    assert row.steps_total == 1000
    sync_wellness(athlete, fake_client, days=2)           # Garmin now says 5000
    row.refresh_from_db()
    assert row.steps_total == 5000
    assert api.get("/api/health/day/summary/").json()["steps"] == 5000
    trend = api.get("/api/health/day/trends/", {"range": "7d"}).json()
    assert any(d.get("steps") == 5000 for d in trend["days"])


# --- full sync ---------------------------------------------------------------------------------

def test_full_sync_job_runs_every_phase(api, connected, fake_client, no_real_garmin_queue):
    before = versioning.current(connected.pk)
    r = api.post("/api/garmin/sync/", {"full": True}, format="json")
    assert r.status_code == 202, r.json()
    body = r.json()
    assert body["mode"] == "full" and body["deduped"] is False and body["job_id"]
    assert body["status"]["phase"] == "queued" and body["status"]["running"] is True
    assert [q[0] for q in no_real_garmin_queue] == ["full_sync"]

    # A second tap while it is queued → the same job, nothing new queued.
    again = api.post("/api/garmin/sync/", {"full": True}, format="json").json()
    assert again["deduped"] is True and again["job_id"] == body["job_id"]
    assert len(no_real_garmin_queue) == 1

    job = sync_jobs.run(connected.pk, body["job_id"])         # the garmin worker
    assert job["phase"] == "done" and job["progress"] == 100 and job["error"] is None
    status = api.get("/api/sync/status/").json()
    assert status["phase"] == "done" and status["finished_at"] and status["running"] is False
    parts = status["parts"]
    assert parts["activities"]["status"] == "ok"
    assert parts["wellness"] == {"status": "ok", "days": 2, "written": 2}
    assert parts["intraday"]["status"] == "ok" and parts["intraday"]["days"] == 2
    assert parts["slow"] == {"status": "not_due"} and parts["derived"]["status"] == "ok"
    today = connected.local_today
    assert DailyMetrics.objects.get(athlete=connected, metric_date=today).steps == 5000
    assert set(IntradayDay.objects.filter(athlete=connected).values_list("day", flat=True)) == {
        today, today - dt.timedelta(days=1)}
    assert status["data_version"] > before
    # Within 60 s of the last job: deduped, not a new burst of Garmin calls.
    calls = len(fake_client.calls)
    third = api.post("/api/garmin/sync/", {"full": True}, format="json").json()
    assert third["deduped"] is True and len(fake_client.calls) == calls


def test_every_sync_refetches_intraday_not_only_the_first(api, connected, fake_client, clock):
    first = api.post("/api/garmin/sync/", {"full": True}, format="json").json()
    sync_jobs.run(connected.pk, first["job_id"])
    row = IntradayDay.objects.get(athlete=connected, day=connected.local_today)
    stamp = row.fetched_at
    clock["hour"] = 21                                    # evening refresh
    fake_client.steps = 12000
    second = api.post("/api/garmin/sync/", {"full": True}, format="json").json()
    assert second["deduped"] is False
    sync_jobs.run(connected.pk, second["job_id"])
    row.refresh_from_db()
    assert row.fetched_at >= stamp and fake_client.calls.count("get_steps_data") == 4
    assert api.get("/api/health/day/summary/").json()["steps"] == 12000


def test_full_sync_refused_when_breaker_open_or_not_connected(api, athlete, connected,
                                                              monkeypatch):
    monkeypatch.setattr("apps.ingest.tasks.garmin_blocked", lambda: True)
    r = api.post("/api/garmin/sync/", {"full": True}, format="json")
    assert r.status_code == 429 and r.json()["status"]["breaker_open"] is True
    connected.garmin_connected = False
    connected.save()
    assert api.post("/api/garmin/sync/", {"full": True}, format="json").status_code == 400


def test_rate_limit_mid_job_stops_and_trips_breaker(api, connected, fake_client):
    fake_client.rate_limit = {"get_sleep_data"}
    job_id = api.post("/api/garmin/sync/", {"full": True}, format="json").json()["job_id"]
    job = sync_jobs.run(connected.pk, job_id)
    assert job["phase"] == "failed" and "rate-limited" in job["error"]
    assert job["parts"]["wellness"]["status"] == "rate_limited"
    assert job["parts"]["intraday"] is None                     # stopped: no further calls
    assert "get_steps_data" not in fake_client.calls
    assert connected.tripped                                    # breaker tripped once


def test_job_never_runs_twice_at_once(api, connected, fake_client):
    job_id = api.post("/api/garmin/sync/", {"full": True}, format="json").json()["job_id"]
    with sync_status.sync_lock(connected):
        job = sync_jobs.run(connected.pk, job_id)
    assert job["phase"] == "failed" and job["error"] == "A sync is already running."
    assert fake_client.calls == []


def test_sync_jobs_are_per_athlete(api, other_api, connected, fake_client):
    api.post("/api/garmin/sync/", {"full": True}, format="json")
    other = other_api.get("/api/sync/status/").json()
    assert other["job_id"] is None and other["phase"] == "idle" and other["running"] is False


# --- run-aware auto-sync -------------------------------------------------------------------------

@pytest.fixture
def run_today(connected):
    connected.usual_run_time = dt.time(7, 0)
    connected.save()
    return make_workout(connected, connected.local_today, kind="EASY")


def test_run_aware_window_polls_every_5_min(api, connected, run_today, clock):
    clock["hour"], clock["minute"] = 7, 30
    connected.garmin_last_sync = at_local(connected, 7, 20).astimezone(dt.timezone.utc)
    connected.save()
    status = api.get("/api/sync/status/").json()
    aware = status["run_aware"]
    assert aware["active"] and aware["waiting_for_run"] and aware["run_time"] == "07:00"
    assert aware["run_time_source"] == "usual" and aware["workout_id"] == run_today.pk
    assert status["min_interval_s"] == 300 and status["auto_sync_due"] is True
    clock["hour"], clock["minute"] = 11, 0                       # window over (07:00 + 3 h)
    connected.garmin_last_sync = at_local(connected, 10, 50).astimezone(dt.timezone.utc)
    connected.save()
    status = api.get("/api/sync/status/").json()
    assert status["run_aware"]["active"] is False and status["min_interval_s"] == 1800
    assert status["auto_sync_due"] is False


def test_run_arrived_ends_the_window(api, connected, run_today, clock):
    from tests.r10_helpers import run

    clock["hour"], clock["minute"] = 7, 30
    run(connected, connected.local_today)
    aware = api.get("/api/sync/status/").json()["run_aware"]
    assert aware["arrived"] is True and aware["active"] is False


def test_auto_in_window_is_a_cheap_run_check_after_a_recent_full(api, connected, run_today,
                                                                 clock, fake_client,
                                                                 no_real_garmin_queue):
    clock["hour"], clock["minute"] = 7, 0
    connected.garmin_last_sync = at_local(connected, 6, 30).astimezone(dt.timezone.utc)
    connected.save()
    first = api.post("/api/garmin/sync/", {"auto": True}, format="json").json()
    assert first["mode"] == "full"
    sync_jobs.run(connected.pk, first["job_id"])
    clock["minute"] = 3
    assert api.post("/api/garmin/sync/", {"auto": True},
                    format="json").json()["skipped"] == "recent"          # 5-min spacing
    clock["minute"] = 10
    second = api.post("/api/garmin/sync/", {"auto": True}, format="json").json()
    assert second["mode"] == "run_check"
    calls = len(fake_client.calls)
    job = sync_jobs.run(connected.pk, second["job_id"])
    assert job["phase"] == "done" and job["parts"]["wellness"] == {"status": "skipped"}
    assert fake_client.calls[calls:] == ["get_activities"]                 # one listing call


def test_run_check_continues_when_the_run_arrives(connected, run_today, clock, fake_client,
                                                  monkeypatch):
    from tests.r10_helpers import run

    def new_run(athlete, limit=None, **kw):
        a = run(athlete, athlete.local_today)
        return SyncResult(imported=1, activity_ids=[a.pk])

    monkeypatch.setattr("apps.ingest.garmin.sync_athlete", new_run)
    clock["hour"], clock["minute"] = 7, 30
    job, _ = sync_jobs.start(connected, "run_check")
    done = sync_jobs.run(connected.pk, job["id"])
    assert done["phase"] == "done" and done["parts"]["wellness"]["status"] == "ok"
    assert done["parts"]["intraday"]["status"] == "ok" and done["parts"]["derived"]["derived"] == 1


def test_auto_posts_are_not_eaten_by_the_hourly_throttle(api, connected, clock):
    for _ in range(12):                    # 12 polls an hour in a run window
        r = api.post("/api/garmin/sync/", {"auto": True}, format="json")
        assert r.status_code == 200


# --- data_version --------------------------------------------------------------------------------

def test_data_version_bumps_on_mutations_and_is_returned(api, athlete):
    v0 = api.get("/api/athlete/").json()["data_version"]
    r = api.patch("/api/athlete/", {"loop_distance_km": 1.2}, format="json")
    assert r.status_code == 200 and r.json()["data_version"] > v0
    assert int(r["X-Data-Version"]) == r.json()["data_version"]
    v1 = r.json()["data_version"]
    DailyMetrics.objects.create(athlete=athlete, metric_date=athlete.local_today, steps=10)
    assert versioning.current(athlete.pk) > v1                    # a background write bumps
    assert int(api.get("/api/sync/status/")["X-Data-Version"]) == versioning.current(athlete.pk)


def test_data_version_is_per_athlete(api, other_api, athlete, other_athlete):
    theirs = versioning.current(other_athlete.pk)
    api.patch("/api/athlete/", {"loop_distance_km": 2.0}, format="json")
    api.post("/api/memory/", {"text": "Likes trails."}, format="json")
    assert versioning.current(other_athlete.pk) == theirs


def test_derived_caches_recompute_after_a_change(api, athlete):
    from apps.ingest.models import IntradayDay as Row

    today = athlete.local_today
    DailyMetrics.objects.create(athlete=athlete, metric_date=today, steps=1000,
                                raw={"stats": {"totalSteps": 1000}})
    assert api.get("/api/health/day/summary/").json()["steps"] == 1000
    assert api.get("/api/health/day/summary/").json()["steps"] == 1000      # cached
    row = DailyMetrics.objects.get(athlete=athlete, metric_date=today)
    row.raw = {"stats": {"totalSteps": 4321}}
    row.save()                                                              # bumps
    assert api.get("/api/health/day/summary/").json()["steps"] == 4321
    assert not Row.objects.exists()
