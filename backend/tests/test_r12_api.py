"""R12 endpoints: custom periods + freq on every Health endpoint (shared parser, period
block, bucketing), the wake planner, My alarm, the read-only watch-alarm check, alarm /
bedtime pushes — with tenant isolation, auth and account deletion."""

import datetime as dt

import pytest
from django.core.cache.backends.locmem import LocMemCache
from django.utils import timezone

from apps.habits.models import HabitLog
from apps.ingest import garmin_slow, tasks
from apps.ingest.models import GarminProfile
from apps.reminders.models import Alarm, PushSubscription
from tests.r10_helpers import metric, night, run

PASSWORD = "correct-horse-battery-1"

PERIOD_ENDPOINTS = ["/api/insights/", "/api/health/fitness/", "/api/health/sleep/",
                    "/api/health/form/", "/api/health/body/", "/api/health/day/trends/",
                    "/api/habits/summary/", "/api/health/training-status/"]


def ago(athlete, n):
    return athlete.local_today - dt.timedelta(days=n)


@pytest.fixture(autouse=True)
def private_breaker(monkeypatch, settings):
    cache = LocMemCache("r12-breaker", {})
    cache.clear()
    monkeypatch.setattr(tasks, "cache", cache)
    settings.GARMIN_SLOW_PAUSE_S = 0
    return cache


# --- A. period parser ------------------------------------------------------------------

@pytest.mark.parametrize("url", PERIOD_ENDPOINTS)
def test_every_endpoint_takes_custom_dates_and_reports_period(api, athlete, url):
    start, end = ago(athlete, 40), ago(athlete, 10)
    body = api.get(url, {"start": start, "end": end}).json()
    assert body["range"] == "custom"
    assert body["start"] == start.isoformat() and body["end"] == end.isoformat()
    assert body["period"] == {"start": start.isoformat(), "end": end.isoformat(), "days": 31,
                              "compare_start": (start - dt.timedelta(days=31)).isoformat(),
                              "compare_end": (start - dt.timedelta(days=1)).isoformat(),
                              "freq": "day"}
    preset = api.get(url, {"range": "1y"}).json()
    assert preset["range"] == "1y" and preset["period"]["freq"] == "week"
    assert api.get(url, {"range": "7d", "freq": "month"}).json()["period"]["freq"] == "month"


@pytest.mark.parametrize("url", PERIOD_ENDPOINTS + ["/api/health/compare/"])
@pytest.mark.parametrize("params,message", [
    ({"range": "4w", "start": "2026-01-01"}, "not both"),
    ({"start": "2026-01-01"}, "both required"),
    ({"start": "2026-01-01", "end": "nope"}, "must be dates"),
    ({"start": "2026-02-01", "end": "2026-01-01"}, "on or before"),
    ({"start": "2023-01-01", "end": "2026-01-01"}, "at most 730"),
    ({"range": "2y"}, "range must be one of"),
    ({"range": "4w", "freq": "hour"}, "freq must be"),
])
def test_period_validation(api, url, params, message):
    params = {**params, "x": "sleep_h", "y": "hrv"} if "compare" in url else params
    r = api.get(url, params)
    assert r.status_code == 400 and message in r.json()["detail"]


def test_future_end_rejected(api, athlete):
    tomorrow = athlete.local_today + dt.timedelta(days=1)
    r = api.get("/api/health/sleep/", {"start": ago(athlete, 3), "end": tomorrow})
    assert r.status_code == 400 and "future" in r.json()["detail"]


def test_legacy_12w_still_works_where_it_did(api):
    assert api.get("/api/insights/", {"range": "12w"}).json()["range"] == "12w"
    assert api.get("/api/habits/summary/", {"range": "12w"}).json()["period"]["days"] == 84
    assert api.get("/api/health/sleep/", {"range": "12w"}).status_code == 400


def test_defaults_unchanged(api):
    assert api.get("/api/health/fitness/").json()["range"] == "6m"
    assert api.get("/api/health/sleep/").json()["range"] == "4w"
    assert api.get("/api/health/training-status/").json()["period"]["days"] == 28
    assert api.get("/api/insights/").json()["range"] == "4w"


# --- A. bucketing in the endpoints -----------------------------------------------------

def test_sleep_series_bucketed_weekly_nights_kept(api, athlete):
    for i in range(1, 15):
        night(athlete, ago(athlete, i), hours=7 + (i % 2), sleep_score=70)
    daily = api.get("/api/health/sleep/", {"range": "4w"}).json()
    assert len(daily["series"]) == 14 and "n" not in daily["series"][0]
    assert daily["series"][0]["bedtime_h"] == 23.0 and daily["series"][0]["wake_h"] is not None
    weekly = api.get("/api/health/sleep/", {"range": "4w", "freq": "week"}).json()
    assert len(weekly["nights"]) == 14                   # nights stay one per night
    assert 2 <= len(weekly["series"]) <= 3 and sum(p["n"] for p in weekly["series"]) == 14
    assert all(dt.date.fromisoformat(p["date"]).weekday() == 0 for p in weekly["series"])
    assert weekly["series"][0]["score"] == 70


def test_body_and_fitness_take_last_value(api, athlete):
    from apps.ingest.models import BodyComposition

    monday = ago(athlete, 7 + athlete.local_today.weekday())
    for i, kg in enumerate([70.0, 69.5, 69.0]):
        BodyComposition.objects.create(athlete=athlete, measured_on=monday + dt.timedelta(days=i),
                                       weight_kg=kg)
        metric(athlete, monday + dt.timedelta(days=i), vo2max=40.0 + i)
    body = api.get("/api/health/body/", {"range": "4w", "freq": "week"}).json()
    assert body["series"] == [{"date": monday.isoformat(), "weight_kg": 69.0, "body_fat_pct": None,
                               "source": "garmin", "n": 3}]
    fit = api.get("/api/health/fitness/", {"range": "4w", "freq": "week"}).json()
    assert fit["vo2max"]["series"] == [{"date": monday.isoformat(), "value": 42.0, "n": 3}]
    assert fit["vo2max"]["current"] == 42.0


def test_habits_series_summed_by_month_and_custom_period(api, athlete):
    for i in range(1, 40):
        at = timezone.now() - dt.timedelta(days=i)
        HabitLog.objects.create(athlete=athlete, kind="sugar", quantity=1, at=at)
    body = api.get("/api/habits/summary/", {"range": "3m", "freq": "month"}).json()
    assert sum(p["count"] for p in body["sugar"]["series"]) == 39
    assert all(p["date"].endswith("-01") for p in body["sugar"]["series"])
    custom = api.get("/api/habits/summary/", {"start": ago(athlete, 20), "end": ago(athlete, 11)}).json()
    assert custom["sugar"]["total"] == 10 and len(custom["sugar"]["series"]) == 10


def test_form_series_and_training_status_history(api, athlete):
    for i in range(1, 15):
        run(athlete, ago(athlete, i), km=5, cadence=160 + i)
        metric(athlete, ago(athlete, i), training_status="Productive", acute_load=300 + i,
               chronic_load=280)
    form = api.get("/api/health/form/", {"range": "4w", "freq": "week"}).json()
    assert len(form["runs"]) == 14 and sum(p["n"] for p in form["series"]) == 14
    assert sum(p["run_km"] for p in form["series"]) == pytest.approx(14 * 4.5)
    status = api.get("/api/health/training-status/", {"range": "4w", "freq": "week"}).json()
    assert sum(p["n"] for p in status["history"]) == 14
    assert status["history"][-1]["status_key"] == "productive"
    old = api.get("/api/health/training-status/").json()
    assert len(old["history"]) == 14 and old["status"] == "Productive"


def test_day_trends_weekly_steps_summed(api, athlete):
    from apps.ingest.models import IntradayDay

    monday = ago(athlete, 7 + athlete.local_today.weekday())
    for i in range(7):
        IntradayDay.objects.create(athlete=athlete, day=monday + dt.timedelta(days=i),
                                   steps_total=1000, stress_avg=30 + i)
    body = api.get("/api/health/day/trends/", {"range": "4w", "freq": "week"}).json()
    week = next(p for p in body["days"] if p["date"] == monday.isoformat())
    assert week["steps"] == 7000 and week["stress_avg"] == 33 and week["n"] == 7


def test_insights_custom_period_and_buckets(api, athlete):
    for i in range(1, 30):
        metric(athlete, ago(athlete, i), hrv_overnight_avg=40 + i % 3, resting_hr=55)
    body = api.get("/api/insights/", {"start": ago(athlete, 20), "end": ago(athlete, 1),
                                      "freq": "week"}).json()
    assert body["range"] == "custom" and body["readiness"]
    assert sum(p["n"] for p in body["hrv"]["series"]) == 20
    assert all("n" in p for p in body["resting_hr"]["series"])


def test_compare_weekly_buckets_and_lag(api, athlete):
    for i in range(1, 92):
        metric(athlete, ago(athlete, i), sleep_seconds=6 * 3600 + (i % 7) * 600,
               hrv_overnight_avg=40 + (i % 7))
    body = api.get("/api/health/compare/", {"x": "sleep_h", "y": "hrv", "range": "3m",
                                            "freq": "week"}).json()
    assert body["period"]["freq"] == "week" and 12 <= body["n"] <= 14
    assert all(dt.date.fromisoformat(p["date"]).weekday() == 0 for p in body["points"])
    lagged = api.get("/api/health/compare/", {"x": "sleep_h", "y": "hrv", "range": "3m",
                                              "freq": "week", "lag": 1}).json()
    assert lagged["n"] == body["n"] - 1
    daily = api.get("/api/health/compare/", {"x": "sleep_h", "y": "hrv", "range": "3m"}).json()
    assert daily["period"]["freq"] == "day" and daily["n"] == 90


# --- B. wake planner, my alarm, watch ----------------------------------------------------

def plan_run(athlete, day):
    from apps.planning.models import PlannedWorkout, TrainingPlan
    from apps.planning.plan_store import propose_plan

    plan = propose_plan(athlete, race_name="10K", race_date=athlete.local_today
                        + dt.timedelta(weeks=10), distance_km=10.0)
    plan.status = TrainingPlan.Status.ACTIVE
    plan.save()
    PlannedWorkout.objects.filter(plan=plan, date=day).delete()
    return PlannedWorkout.objects.create(athlete=athlete, plan=plan, date=day, title="Easy 30",
                                         kind="EASY", duration_s=1800, load=30)


def test_wake_plan_defaults(api, athlete):
    body = api.get("/api/health/wake-plan/").json()
    assert body["date"] == (athlete.local_today + dt.timedelta(days=1)).isoformat()
    assert body["run"]["planned"] is False and body["wake_source"] == "default"
    assert body["wake_time"] == "07:00" and body["bedtime"] == "22:45"
    assert body["bedtime_reminder_at"] == "22:15" and body["need_source"] == "default"
    assert body["flags"] == [] and body["watch"]["available"] is False
    assert body["my_alarm"]["enabled"] is False and body["my_alarm_on_date"] is None
    assert "SET_ALARM" in body["android_intent"]


def test_wake_plan_for_a_run_with_watch_mismatch(api, athlete):
    tomorrow = athlete.local_today + dt.timedelta(days=1)
    workout = plan_run(athlete, tomorrow)
    for i in range(7):
        night(athlete, ago(athlete, i), hours=7, need_h=7.5, bed=(23, 0))
    api.patch("/api/alarm/", {"run_time": "06:30"}, format="json")
    GarminProfile.objects.create(athlete=athlete, watch_alarms_available=True,
                                 watch_alarms=[{"time": "07:00", "days": list(range(7)),
                                                "once": False, "enabled": True, "label": None,
                                                "device": "FR"}])
    body = api.get("/api/health/wake-plan/").json()
    assert body["run"] == {"planned": True, "workout_id": workout.pk, "title": "Easy 30",
                           "kind": "EASY", "run_time": "06:30", "run_time_source": "setting"}
    assert body["wake_time"] == "05:45" and body["wake_source"] == "run"
    assert body["need_s"] == 27000 and body["bedtime"] == "22:00"
    assert [f["kind"] for f in body["flags"]] == ["watch_alarm_after_run"]
    assert body["watch"]["summary"] == "07:00 every day"


def test_wake_plan_habit_and_history_run_time(api, athlete):
    for i in range(7):
        night(athlete, ago(athlete, i), hours=8, bed=(22, 30))      # wakes 06:30
    for i in range(1, 4):
        a = run(athlete, ago(athlete, i))
        a.started_at = timezone.make_aware(dt.datetime.combine(ago(athlete, i), dt.time(6, 0)),
                                           athlete.local_now.tzinfo)
        a.save()
    body = api.get("/api/health/wake-plan/").json()
    assert body["wake_source"] == "habit" and body["wake_time"] == "06:30"
    assert body["run"]["run_time"] == "06:00" and body["run"]["run_time_source"] == "history"


def test_wake_plan_date_validation(api, athlete):
    assert api.get("/api/health/wake-plan/", {"date": "x"}).status_code == 400
    assert api.get("/api/health/wake-plan/", {"date": ago(athlete, 1)}).status_code == 400
    far = athlete.local_today + dt.timedelta(days=8)
    assert api.get("/api/health/wake-plan/", {"date": far}).status_code == 400
    assert api.get("/api/health/wake-plan/", {"date": athlete.local_today}).status_code == 200


def test_alarm_get_patch_validation(api):
    body = api.get("/api/alarm/").json()
    assert body == {"time": None, "days": [0, 1, 2, 3, 4, 5, 6], "enabled": False, "push": False,
                    "run_time": None, "bedtime_reminder": False, "bedtime_lead_min": 30,
                    "push_available": False, "note": body["note"]}
    assert "can't set your phone" in body["note"]
    ok = api.patch("/api/alarm/", {"time": "06:15", "days": [4, 0, 2], "enabled": True,
                                   "push": True, "bedtime_lead_min": 45}, format="json").json()
    assert ok["time"] == "06:15" and ok["days"] == [0, 2, 4] and ok["bedtime_lead_min"] == 45
    for bad in ({"time": "6am"}, {"days": [7]}, {"days": [1, 1]}, {"days": "mon"},
                {"enabled": "yes"}, {"bedtime_lead_min": 5}, {"colour": "red"},
                {"time": None}, {"days": []}):
        assert api.patch("/api/alarm/", bad, format="json").status_code == 400, bad
    cleared = api.patch("/api/alarm/", {"enabled": False, "time": None}, format="json").json()
    assert cleared["time"] is None and cleared["enabled"] is False


class DeviceClient:
    def __init__(self, devices=True, fail=None):
        self.calls = []
        self.devices = devices
        self.fail = fail

    def __getattr__(self, name):            # every other slow-fetch call: nothing there
        def missing(*a, **kw):
            self.calls.append(name)
            raise Exception("404 Not Found")
        return missing

    def get_devices(self):
        self.calls.append("get_devices")
        if self.fail == "get_devices":
            raise Exception("429 Too Many Requests")
        return [{"deviceId": 111, "productDisplayName": "Forerunner 265"}] if self.devices else []

    def get_device_settings(self, device_id):
        self.calls.append("get_device_settings")
        return {"alarms": [{"alarmMode": "ON", "alarmTime": 360,
                            "alarmDays": ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]},
                           {"alarmMode": "ON", "alarmTime": 480, "alarmDays": ["SATURDAY"]}],
                "otherSetting": "untouched"}


def test_slow_fetch_reads_watch_alarms(api, athlete):
    client = DeviceClient()
    garmin_slow.sync_slow(athlete, client, force=True)
    assert not any(c.startswith(("set_", "update_", "delete_", "put_")) for c in client.calls)
    body = api.get("/api/health/watch-alarms/").json()
    assert body["available"] is True and body["checked_on"] == athlete.local_today.isoformat()
    assert body["summary"] == "06:00 Mon–Fri · 08:00 Sat"
    assert body["alarms"][0]["device"] == "Forerunner 265"


def test_watch_alarms_unavailable_without_devices(api, athlete):
    garmin_slow.sync_slow(athlete, DeviceClient(devices=False), force=True)
    body = api.get("/api/health/watch-alarms/").json()
    assert body == {"available": False, "checked_on": athlete.local_today.isoformat(),
                    "alarms": [], "summary": None}


def test_watch_alarm_429_stops_the_slow_fetch(athlete):
    result = garmin_slow.sync_slow(athlete, DeviceClient(fail="get_devices"), force=True)
    assert result["rate_limited"] is True


# --- B3 pushes -------------------------------------------------------------------------

@pytest.fixture
def push_on(settings, athlete, monkeypatch):
    settings.VAPID_PUBLIC_KEY = settings.VAPID_PRIVATE_KEY = "k"
    settings.VAPID_SUBJECT = "mailto:x@example.com"
    PushSubscription.objects.create(athlete=athlete, endpoint="https://p.example.com/1",
                                    p256dh="k", auth="a")
    sent = []
    monkeypatch.setattr("apps.reminders.push.send_to_athlete",
                        lambda a, body: (sent.append(body) or 1, 0))
    return sent


def test_alarm_push_once_at_time(athlete, push_on, monkeypatch):
    from apps.reminders import alarms
    from apps.reminders import tasks as reminder_tasks

    now = athlete.local_now.replace(second=0, microsecond=0)
    Alarm.objects.create(athlete=athlete, time=(now - dt.timedelta(minutes=5)).time(),
                         days=[now.weekday()], enabled=True, push=True)
    reminder_tasks.send_due()
    reminder_tasks.send_due()
    assert [m["tag"] for m in push_on] == ["alarm"]
    assert "not a phone alarm" in push_on[0]["body"]
    # Another weekday: nothing.
    row = Alarm.objects.get()
    row.last_sent, row.days = {}, [(now.weekday() + 1) % 7]
    row.save()
    assert alarms.due_messages(athlete, row, now) == []


def test_bedtime_reminder(athlete, push_on, monkeypatch):
    from apps.reminders import alarms

    row = Alarm.objects.create(athlete=athlete, bedtime_reminder=True)
    evening = athlete.local_now.replace(hour=22, minute=20, second=0, microsecond=0)
    assert alarms.bedtime_minute(athlete, evening) == 22 * 60 + 15     # default plan
    assert alarms.due_messages(athlete, row, evening) == ["bedtime"]
    early = evening.replace(hour=21)
    assert alarms.due_messages(athlete, row, early) == []
    row.last_sent = {"bedtime": evening.date().isoformat()}
    assert alarms.due_messages(athlete, row, evening) == []


# --- isolation, auth, deletion ---------------------------------------------------------

def test_tenant_isolation_for_r12(api, other_api, athlete):
    api.patch("/api/alarm/", {"time": "05:30", "enabled": True}, format="json")
    GarminProfile.objects.create(athlete=athlete, watch_alarms_available=True,
                                 watch_alarms=[{"time": "06:00", "days": [0], "once": False,
                                                "enabled": True, "label": None, "device": None}])
    assert other_api.get("/api/alarm/").json()["time"] is None
    assert other_api.get("/api/health/watch-alarms/").json()["available"] is False
    assert other_api.get("/api/health/wake-plan/").json()["my_alarm"]["enabled"] is False
    for i in range(1, 5):
        metric(athlete, ago(athlete, i), vo2max=45.0, hrv_overnight_avg=40)
    start, end = ago(athlete, 10), ago(athlete, 2)
    assert api.get("/api/health/fitness/", {"start": start, "end": end}).json()["vo2max"]["series"]
    assert other_api.get("/api/health/fitness/", {"start": start, "end": end}
                         ).json()["vo2max"]["series"] == []
    assert other_api.get("/api/insights/", {"start": start, "end": end}).json()["hrv"]["series"] == []


@pytest.mark.parametrize("method,url", [("get", "/api/health/wake-plan/"),
                                        ("get", "/api/health/watch-alarms/"),
                                        ("get", "/api/alarm/"), ("patch", "/api/alarm/")])
def test_r12_endpoints_need_auth(client, db, method, url):
    assert getattr(client, method)(url).status_code == 401


def test_account_deletion_covers_alarm(api, athlete, other_athlete, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.GARMIN_TOKEN_DIR = str(tmp_path / "garmin")
    for a in (athlete, other_athlete):
        Alarm.objects.create(athlete=a, enabled=False)
        GarminProfile.objects.create(athlete=a, watch_alarms=[], watch_alarms_available=True)
    assert api.delete("/api/auth/me/", {"password": PASSWORD}, format="json").status_code == 204
    assert Alarm.objects.get().athlete_id == other_athlete.pk
    assert GarminProfile.objects.get().athlete_id == other_athlete.pk
