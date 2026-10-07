"""R11 endpoints: Day (+ summary, trends), Compare's day metrics, water, run maps,
nudges (settings and the beat) — with tenant isolation, auth and account deletion for
every new model."""

import datetime as dt

import pytest
from django.utils import timezone

from apps.activities.models import ActivityRecord, Segment
from apps.diet.models import WaterLog
from apps.habits.models import HabitLog
from apps.ingest.models import IntradayDay
from apps.reminders import nudges
from apps.reminders.models import PushSubscription, ReminderSettings
from tests.r10_helpers import metric, night, run

PASSWORD = "correct-horse-battery-1"


def ago(athlete, n):
    return athlete.local_today - dt.timedelta(days=n)


def intraday(athlete, day, *, steps=100, stress=30, hr=72, **fields):
    rows = [[m, steps if m >= 420 else 0, "sleeping" if m < 420 else "sedentary"]
            for m in range(0, 1440, 15)]
    defaults = dict(
        hr=[[m, hr] for m in range(0, 1440, 2)], stress=[[m, stress] for m in range(0, 1440, 3)],
        body_battery=[[0, 30], [420, 80], [1380, 35]], steps=rows, fetched_at=timezone.now(),
        steps_total=sum(r[1] for r in rows), stress_avg=stress, awake_hr_avg=hr,
        active_min=30, sedentary_min=600, stress_high_min=5, bb_at_bedtime=35, complete=True)
    defaults.update(fields)
    row, _ = IntradayDay.objects.update_or_create(athlete=athlete, day=day, defaults=defaults)
    return row


# --- F1 day ----------------------------------------------------------------------------

def test_day_full_body(api, athlete):
    day = ago(athlete, 1)
    intraday(athlete, day)
    night(athlete, day, bed=(23, 0), hours=8)          # woke 07:00 on `day`
    night(athlete, athlete.local_today, bed=(22, 30), hours=8)
    activity = run(athlete, day, km=5)
    body = api.get("/api/health/day/", {"date": day.isoformat()}).json()
    assert body["available"] is True and body["is_today"] is False and body["complete"] is True
    assert body["awake"] == {"start": "07:00", "end": "22:30", "source": "sleep"}
    assert body["next_date"] == athlete.local_today.isoformat()
    tl = body["timeline"]
    assert len(tl["hr"]) == 720 and len(tl["steps"]) == 96 and tl["steps"][0] == [0, 0]
    runs = [m for m in tl["markers"] if m["type"] == "run"]
    assert runs and runs[0]["activity_id"] == activity.pk and runs[0]["label"] == "Run · 5.0 km"
    assert {m["type"] for m in tl["markers"]} >= {"sleep", "run"}
    for key in ("steps", "activity", "stress", "body_battery", "heart_rate", "score_card", "now"):
        assert key in body
    assert body["body_battery"]["at_wake"] == 80 and body["body_battery"]["at_bedtime"] == 80
    assert body["stress"]["rest_min"] == 0 and body["stress"]["low_min"] == 1440
    assert body["heart_rate"]["awake_avg"] == 72
    assert body["score_card"]["status"] in {"good", "ok", "low"}


def test_day_without_data_and_validation(api, athlete):
    body = api.get("/api/health/day/").json()
    assert body["available"] is False and body["is_today"] is True and body["next_date"] is None
    assert body["score_card"]["status"] == "no_data" and body["timeline"]["hr"] == []
    for bad in ("2026-13-01", (athlete.local_today + dt.timedelta(days=1)).isoformat(),
                ago(athlete, 400).isoformat()):
        r = api.get("/api/health/day/", {"date": bad})
        assert r.status_code == 400 and "detail" in r.json()


def test_day_habit_markers_and_private_rule(api, athlete):
    day = ago(athlete, 1)
    intraday(athlete, day)
    at = timezone.make_aware(dt.datetime.combine(day, dt.time(20, 0)), athlete.local_now.tzinfo)
    HabitLog.objects.create(athlete=athlete, kind="alcohol", quantity=2, at=at)
    HabitLog.objects.create(athlete=athlete, kind="private", quantity=1, at=at)
    marks = [m for m in api.get("/api/health/day/", {"date": day}).json()["timeline"]["markers"]
             if m["type"] == "habit"]
    assert [(m["kind"], m["label"], m["start_min"]) for m in marks] == [("alcohol", "Drink ×2", 1200)]
    athlete.private_habit_enabled = True
    athlete.save()
    marks = [m for m in api.get("/api/health/day/", {"date": day}).json()["timeline"]["markers"]
             if m["type"] == "habit"]
    assert {m["kind"] for m in marks} == {"alcohol", "private"}


def test_day_steps_goal_garmin_vs_adaptive(api, athlete):
    for i in range(1, 15):
        intraday(athlete, ago(athlete, i), steps=200)       # 11,400/day from 07:00
    body = api.get("/api/health/day/", {"date": ago(athlete, 1)}).json()["steps"]
    assert body["goal_source"] == "adaptive" and body["goal"] == body["adaptive_goal"] == 14300
    metric(athlete, ago(athlete, 1), raw={"stats": {"dailyStepGoal": 7000, "totalSteps": 11400}})
    body = api.get("/api/health/day/", {"date": ago(athlete, 1)}).json()["steps"]
    assert body["goal_source"] == "garmin" and body["goal"] == 7000 and body["met"] is True


# --- F2 summary ------------------------------------------------------------------------

def test_day_summary(api, athlete):
    assert api.get("/api/health/day/summary/").json()["available"] is False
    intraday(athlete, athlete.local_today, complete=False)
    body = api.get("/api/health/day/summary/").json()
    assert body["available"] is True and body["stress"] == 30 and body["stress_at"] == "23:57"
    assert body["body_battery"] == 35 and body["steps"] == 6800
    assert set(body) == {"date", "available", "steps", "step_goal", "goal_source", "pct", "stress",
                         "stress_at", "body_battery", "body_battery_at", "data_as_of", "fetched_at"}


# --- F3 trends -------------------------------------------------------------------------

def test_day_trends(api, athlete):
    for i in range(20):
        intraday(athlete, ago(athlete, i), stress=20 + (i % 2) * 40, hr=70 + i % 3)
        night(athlete, ago(athlete, i), hours=7, sleep_score=70 + (i % 2) * 10)
    body = api.get("/api/health/day/trends/").json()
    assert body["range"] == "4w" and len(body["days"]) == 20
    assert set(body["days"][0]) == {"date", "steps", "step_goal", "active_min", "sedentary_min",
                                    "stress_avg", "stress_high_min", "stressful_min",
                                    "awake_hr_avg", "bb_charged", "bb_drained", "bb_at_wake",
                                    "bb_at_bedtime"}
    assert body["averages"]["stress_avg"] == 40 and body["previous"]["steps"] is None
    assert body["weeks"] and body["awake_hr_trend"]["direction"] in {"flat", "up", "down"}
    assert len(body["weekday_pattern"]["by_weekday"]) == 7
    groups = body["day_night_run"]["groups"]
    assert [g["key"] for g in groups] == ["stress", "steps"]
    sleep = next(r for r in groups[0]["rows"] if r["metric"] == "sleep_score")
    assert sleep["enough_data"] is True
    assert api.get("/api/health/day/trends/", {"range": "2w"}).status_code == 400


# --- F4 compare ------------------------------------------------------------------------

def test_compare_catalogue_has_day_group(api, athlete):
    metrics = {m["key"]: m for m in api.get("/api/health/compare/metrics/").json()["metrics"]}
    for key in ("active_min", "sedentary_min", "stress_high_min", "bb_bedtime", "awake_hr"):
        assert metrics[key]["group"] == "day"
    assert metrics["steps"]["group"] == "wellness"
    for i in range(10):
        intraday(athlete, ago(athlete, i), hr=70 + i, active_min=20 + i * 5)
        metric(athlete, ago(athlete, i), hrv_overnight_avg=50 - i)
    body = api.get("/api/health/compare/", {"x": "active_min", "y": "awake_hr"}).json()
    assert body["n"] == 10 and body["rho"] == 1.0
    assert api.get("/api/health/compare/", {"x": "awake_hr", "y": "hrv", "lag": 1}).json()["n"] == 9


# --- D water ---------------------------------------------------------------------------

def test_water_log_flow(api, athlete):
    day = api.get("/api/diet/water/").json()
    assert day["drunk_ml"] == 0 and day["target_ml"] > 0 and day["quick_add"] == [250, 500]
    r = api.post("/api/diet/water/", {"ml": 250}, format="json")
    assert r.status_code == 201
    body = r.json()
    assert body["log"]["ml"] == 250 and body["day"]["drunk_ml"] == 250
    api.post("/api/diet/water/", {"ml": 500}, format="json")
    day = api.get("/api/diet/water/").json()
    assert day["drunk_ml"] == 750 and len(day["logs"]) == 2
    assert day["remaining_ml"] == max(0, day["target_ml"] - 750)
    diet = api.get("/api/diet/day/").json()
    assert diet["water"]["drunk_ml"] == 750
    assert diet["water"]["target_ml"] == diet["targets"]["water_ml"]
    after = api.delete(f"/api/diet/water/{body['log']['id']}/").json()
    assert after["drunk_ml"] == 500


def test_water_validation_and_backdating(api, athlete):
    for bad in ({}, {"ml": 10}, {"ml": 2500}, {"ml": 250.5}, {"ml": True}, {"ml": "lots"},
                {"ml": 250, "at": "yesterday"},
                {"ml": 250, "at": (timezone.now() + dt.timedelta(hours=1)).isoformat()},
                {"ml": 250, "at": (timezone.now() - dt.timedelta(days=8)).isoformat()}):
        assert api.post("/api/diet/water/", bad, format="json").status_code == 400, bad
    at = timezone.now() - dt.timedelta(days=1, hours=2)
    body = api.post("/api/diet/water/", {"ml": 300, "at": at.isoformat()}, format="json").json()
    assert body["log"]["local_date"] == at.astimezone(athlete.local_now.tzinfo).date().isoformat()
    assert api.get("/api/diet/water/", {"date": "nope"}).status_code == 400


# --- E routes --------------------------------------------------------------------------

def gps_run(athlete, n=900):
    activity = run(athlete, ago(athlete, 1), km=2.7)
    ActivityRecord.objects.bulk_create([
        ActivityRecord(activity=activity, offset_s=i, distance_m=i * 3.0, heart_rate=140,
                       altitude_m=550.0, latitude=18.59, longitude=73.73 + i * 3.0 / 105_000)
        for i in range(n)])
    Segment.objects.create(activity=activity, index=0, kind="run", start_offset_s=0,
                           duration_s=n, distance_m=n * 3.0)
    return activity


def test_route_endpoint_and_privacy_setting(api, athlete, monkeypatch):
    from django.core.cache.backends.locmem import LocMemCache

    from django.core import cache as cache_module
    local = LocMemCache("route-tests", {})
    monkeypatch.setattr(cache_module, "cache", local)
    activity = gps_run(athlete)
    assert api.get("/api/athlete/").json()["map_hide_endpoints"] is True
    body = api.get(f"/api/activities/{activity.pk}/route/").json()
    assert body["activity_id"] == activity.pk and body["available"] is True
    assert body["hidden_endpoints"] is True and body["points"][0]["dist_m"] >= 200
    assert body["points"][0]["segment"] == "run" and body["has_hr"] is True
    assert [k["km"] for k in body["km_markers"]] == [1, 2]
    r = api.patch("/api/athlete/", {"map_hide_endpoints": False}, format="json")
    assert r.status_code == 200, r.content
    athlete.refresh_from_db()           # force_authenticate keeps the same user object
    body = api.get(f"/api/activities/{activity.pk}/route/").json()
    assert body["hidden_endpoints"] is False and body["points"][0]["dist_m"] == 0


def test_route_without_gps(api, athlete):
    activity = run(athlete, ago(athlete, 1))
    body = api.get(f"/api/activities/{activity.pk}/route/").json()
    assert body["available"] is False and body["reason"] == "no_gps" and body["points"] == []


def test_routes_overlay(api, athlete):
    gps_run(athlete)
    run(athlete, ago(athlete, 2))        # no GPS: left out
    body = api.get("/api/activities/routes/").json()
    assert len(body["routes"]) == 1 and len(body["routes"][0]["points"]) <= 150
    assert api.get("/api/activities/routes/", {"limit": 0}).status_code == 400
    assert api.get("/api/activities/routes/", {"limit": "x"}).status_code == 400


# --- C nudges: settings ----------------------------------------------------------------

def test_reminders_include_nudges_and_validate(api, athlete):
    body = api.get("/api/reminders/").json()
    keys = {n["key"]: n for n in body["nudges"]}
    assert set(keys) == {"move", "breathing", "water"}
    assert all(n["enabled"] is False for n in keys.values())
    assert keys["move"]["after_min"] == 60 and keys["move"]["threshold"] is None
    assert keys["breathing"]["threshold"] == 51 and keys["water"]["every_h"] == 2
    assert body["quiet_hours"] == {"start": "22:00", "end": "07:00"}
    assert body["data_as_of"] is None and len(body["reminders"]) == 6   # + R13 two
    r = api.patch("/api/reminders/", {"move": {"enabled": True, "after_min": 75, "start": "08:00"},
                                      "quiet_hours": {"start": "23:00"},
                                      "habit_log": {"enabled": True}}, format="json")
    assert r.status_code == 200
    body = r.json()
    move = next(n for n in body["nudges"] if n["key"] == "move")
    assert move["enabled"] is True and move["after_min"] == 75 and move["start"] == "08:00"
    assert body["quiet_hours"]["start"] == "23:00"
    for bad in ({"move": {"after_min": 30}}, {"move": {"threshold": 60}},
                {"breathing": {"threshold": 40}}, {"water": {"every_h": 9}},
                {"water": {"max_per_day": 0}}, {"move": {"enabled": "yes"}},
                {"move": {"start": "8am"}}, {"quiet_hours": {"start": "x"}},
                {"quiet_hours": {"when": "22:00"}}, {"move": True}):
        assert api.patch("/api/reminders/", bad, format="json").status_code == 400, bad


# --- C nudges: evaluation --------------------------------------------------------------

def at_local(athlete, hour, minute=0):
    return athlete.local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def settings_row(athlete, **kw):
    row, _ = ReminderSettings.objects.update_or_create(athlete=athlete, defaults=kw)
    return row


def sitting_until(athlete, end_min, from_min=420):
    """Today's data up to `end_min`: active before `from_min`, sitting after."""
    rows = [[m, 300 if m < from_min else 0, "active" if m < from_min else "sedentary"]
            for m in range(0, end_min, 15)]
    row, _ = IntradayDay.objects.update_or_create(
        athlete=athlete, day=athlete.local_today,
        defaults={"steps": rows, "stress": [[m, 20] for m in range(0, end_min, 3)]})
    return row


def test_move_nudge_rules(athlete):
    row = settings_row(athlete, move=True, move_after_min=60)
    now = at_local(athlete, 11, 5)
    data = sitting_until(athlete, 660, from_min=570)       # sat 09:30–11:00 (90 min)
    msg, state = nudges.check(athlete, row, "move", now, data)
    assert msg["tag"] == "move" and msg["url"] == "/health/day" and state["stretch"] == 570
    assert not any(ch.isdigit() for ch in msg["body"])      # no numbers in payloads
    row.nudge_state = {"move": state}
    # Same stretch later: deduped (and inside the 60-min gap).
    assert nudges.check(athlete, row, "move", at_local(athlete, 11, 10), data)[0] is None
    row.nudge_state = {"move": {**state, "last_at": at_local(athlete, 9).isoformat()}}
    assert nudges.check(athlete, row, "move", now, data)[0] is None       # same stretch
    # Stale data (latest bucket > 60 min old): nothing.
    row.nudge_state = {}
    assert nudges.check(athlete, row, "move", at_local(athlete, 12, 30), data)[0] is None
    # Too short a stretch for a 90-min setting.
    row.move_after_min = 90
    short = sitting_until(athlete, 660, from_min=600)
    assert nudges.check(athlete, row, "move", now, short)[0] is None


def test_nudges_respect_hours_quiet_and_caps(athlete):
    row = settings_row(athlete, move=True, move_start=dt.time(12, 0), move_end=dt.time(18, 0))
    data = sitting_until(athlete, 660, from_min=540)
    assert nudges.check(athlete, row, "move", at_local(athlete, 11, 5), data)[0] is None  # hours
    row = settings_row(athlete, move=True, move_start=dt.time(0, 0), move_end=dt.time(23, 59),
                       quiet_start=dt.time(10, 0), quiet_end=dt.time(12, 0))
    assert nudges.check(athlete, row, "move", at_local(athlete, 11, 5), data)[0] is None  # quiet
    row = settings_row(athlete, quiet_start=dt.time(22, 0), quiet_end=dt.time(7, 0),
                       move_max_per_day=2,
                       nudge_state={"move": {"date": athlete.local_today.isoformat(), "count": 2}})
    assert nudges.check(athlete, row, "move", at_local(athlete, 11, 5), data)[0] is None  # cap
    row.nudge_state = {"move": {"date": ago(athlete, 1).isoformat(), "count": 2}}
    assert nudges.check(athlete, row, "move", at_local(athlete, 11, 5), data)[0] is not None
    row.move = False
    assert nudges.check(athlete, row, "move", at_local(athlete, 11, 5), data)[0] is None  # off


def test_no_nudge_during_or_just_after_a_run(athlete):
    row = settings_row(athlete, move=True, breathing=True)
    data = sitting_until(athlete, 660, from_min=540)
    now = at_local(athlete, 11, 5)
    activity = run(athlete, athlete.local_today)
    activity.started_at = now - dt.timedelta(minutes=50)
    activity.total_elapsed_s = 1200
    activity.save()
    assert nudges.check(athlete, row, "move", now, data)[0] is None
    activity.started_at = now - dt.timedelta(hours=3)
    activity.save()
    assert nudges.check(athlete, row, "move", now, data)[0] is not None


def test_breathing_nudge(athlete):
    row = settings_row(athlete, breathing=True)
    now = at_local(athlete, 11, 5)
    data, _ = IntradayDay.objects.update_or_create(athlete=athlete, day=athlete.local_today,
        defaults={"steps": [[m, 300, "active"] for m in range(0, 660, 15)],
                  "stress": [[m, 20 if m < 600 else 65] for m in range(0, 663, 3)]})
    msg, state = nudges.check(athlete, row, "breathing", now, data)
    assert msg["url"] == "/health/guides?g=breathing" and state["stretch"] == 600
    row.breathing_threshold = 70
    assert nudges.check(athlete, row, "breathing", now, data)[0] is None
    row.breathing_threshold = 51
    data.stress = [[m, 20 if m < 645 else 65] for m in range(0, 663, 3)]   # only 18 min
    assert nudges.check(athlete, row, "breathing", now, data)[0] is None


def test_water_nudge(athlete):
    row = settings_row(athlete, water=True, water_every_h=2)
    now = at_local(athlete, 11, 0)
    msg, state = nudges.check(athlete, row, "water", now)
    assert msg["tag"] == "water" and state["count"] == 1
    WaterLog.objects.create(athlete=athlete, at=timezone.now() - dt.timedelta(minutes=30),
                            local_date=athlete.local_today, ml=250)
    assert nudges.check(athlete, row, "water", at_local(athlete, 13, 0))[0] is None


def test_send_due_sends_nudges_once(athlete, settings, monkeypatch):
    from apps.reminders import tasks as reminder_tasks

    settings.VAPID_PUBLIC_KEY = settings.VAPID_PRIVATE_KEY = "k"
    settings.VAPID_SUBJECT = "mailto:x@example.com"
    PushSubscription.objects.create(athlete=athlete, endpoint="https://p.example.com/1",
                                    p256dh="k", auth="a")
    settings_row(athlete, water=True, water_start=dt.time(0, 0), water_end=dt.time(23, 59),
                 quiet_start=dt.time(0, 0), quiet_end=dt.time(0, 0))
    sent = []
    monkeypatch.setattr("apps.reminders.push.send_to_athlete",
                        lambda a, body: (sent.append(body) or 1, 0))
    reminder_tasks.send_due()
    reminder_tasks.send_due()
    assert [m["tag"] for m in sent] == ["water"]           # the gap stops the second
    row = ReminderSettings.objects.get(athlete=athlete)
    assert row.nudge_state["water"]["count"] == 1


# --- isolation, auth, deletion ---------------------------------------------------------

def test_tenant_isolation_for_r11_endpoints(api, other_api, athlete):
    day = ago(athlete, 1)
    intraday(athlete, day)
    intraday(athlete, athlete.local_today)
    activity = gps_run(athlete)
    log = api.post("/api/diet/water/", {"ml": 250}, format="json").json()["log"]
    assert other_api.get("/api/health/day/", {"date": day}).json()["available"] is False
    assert other_api.get("/api/health/day/summary/").json()["available"] is False
    assert other_api.get("/api/health/day/trends/").json()["days"] == []
    assert other_api.get(f"/api/activities/{activity.pk}/route/").status_code == 404
    assert other_api.get("/api/activities/routes/").json()["routes"] == []
    assert other_api.get("/api/diet/water/").json()["drunk_ml"] == 0
    assert other_api.delete(f"/api/diet/water/{log['id']}/").status_code == 404
    assert WaterLog.objects.filter(pk=log["id"]).exists()
    assert other_api.get("/api/health/compare/", {"x": "active_min", "y": "awake_hr"}).json()["n"] == 0
    other_api.patch("/api/reminders/", {"move": {"enabled": True}}, format="json")
    mine = {n["key"]: n for n in api.get("/api/reminders/").json()["nudges"]}
    assert mine["move"]["enabled"] is False
    assert other_api.get("/api/reminders/").json()["data_as_of"] is None
    assert api.get("/api/reminders/").json()["data_as_of"] is not None


@pytest.mark.parametrize("method,url", [
    ("get", "/api/health/day/"), ("get", "/api/health/day/summary/"),
    ("get", "/api/health/day/trends/"), ("get", "/api/diet/water/"), ("post", "/api/diet/water/"),
    ("delete", "/api/diet/water/1/"), ("get", "/api/activities/1/route/"),
    ("get", "/api/activities/routes/")])
def test_r11_endpoints_need_auth(client, db, method, url):
    assert getattr(client, method)(url).status_code == 401


def test_account_deletion_covers_r11_models(api, athlete, other_athlete, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.GARMIN_TOKEN_DIR = str(tmp_path / "garmin")
    for a in (athlete, other_athlete):
        intraday(a, ago(a, 1))
        WaterLog.objects.create(athlete=a, at=timezone.now(), local_date=a.local_today, ml=250)
        settings_row(a, move=True)
    assert api.delete("/api/auth/me/", {"password": PASSWORD}, format="json").status_code == 204
    for model in (IntradayDay, WaterLog, ReminderSettings):
        assert model.objects.count() == 1
        assert model.objects.get().athlete_id == other_athlete.pk


def test_deletion_drops_route_cache_keys(athlete):
    from apps.athletes.deletion import _cache_keys

    activity = run(athlete, ago(athlete, 1))
    keys = _cache_keys(athlete.user)
    assert f"route:v1:{activity.pk}:{activity.segmentation_version}:1" in keys
    assert f"route-overlay:v1:{activity.pk}:0" in keys
