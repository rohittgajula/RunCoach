"""R14 API: Today layout, weather report + smart reschedule, calendar feed, experiments,
goals, heart adaptation, account deletion. Network is faked; dates are relative to the
athlete's own today so the suite passes under any clock."""

import datetime as dt

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.activities.models import Activity, ActivityRecord, Segment
from apps.athletes.models import Athlete, MetricEntry
from apps.habits.models import HabitLog
from apps.health.models import (
    Achievement, ActivityWeather, Experiment, Goal, RunHeartStats,
)
from apps.planning.models import (
    CalendarFeed, CalendarFeedItem, PlannedWorkout, WeatherSuggestion,
)
from tests.r7_helpers import active_plan, make_workout, wellness

ALL_DAYS = {str(d): True for d in range(7)}


# --- §1 today_layout ------------------------------------------------------------------------

def test_today_layout_round_trip(api):
    r = api.patch("/api/athlete/", {"today_layout": ["weather", "log", "fuel"]}, format="json")
    assert r.status_code == 200 and r.json()["today_layout"] == ["weather", "log", "fuel"]
    assert api.get("/api/athlete/").json()["today_layout"] == ["weather", "log", "fuel"]
    assert api.patch("/api/athlete/", {"today_layout": None}, format="json").json()[
        "today_layout"] is None
    for bad in (["Weather"], ["a", "a"], "weather", [1], ["x" * 40], ["k"] * 31):
        r = api.patch("/api/athlete/", {"today_layout": bad}, format="json")
        assert r.status_code == 400 and "today_layout" in r.json(), bad
    r = api.patch("/api/athlete/", {"weather_auto_apply": True}, format="json")
    assert r.json()["weather_auto_apply"] is True


def test_admin_budget_is_not_writable_by_the_athlete(api, athlete):
    api.patch("/api/athlete/", {"ai_call_budget": 99999}, format="json")
    athlete.refresh_from_db()
    assert athlete.ai_call_budget is None
    assert "ai_call_budget" not in api.get("/api/athlete/").json()


# --- §3 weather -------------------------------------------------------------------------------

def forecast(athlete, bad: set, good_feels=25.0, aqi=40):
    start = athlete.local_today
    dates = [start + dt.timedelta(days=i) for i in range(7)]
    times, feels = [], []
    for d in dates:
        for h in range(24):
            times.append(f"{d.isoformat()}T{h:02d}:00")
            feels.append(36.0 if d in bad else good_feels)
    n = len(times)
    fc = {"hourly": {"time": times, "temperature_2m": [f - 2 for f in feels],
                     "apparent_temperature": feels, "relative_humidity_2m": [60] * n,
                     "dew_point_2m": [17] * n, "precipitation_probability": [10] * n,
                     "wind_speed_10m": [8] * n, "uv_index": [3] * n, "weather_code": [1] * n},
          "current": {"time": times[0], "temperature_2m": 24, "apparent_temperature": 26,
                      "relative_humidity_2m": 60, "dew_point_2m": 17, "weather_code": 1,
                      "wind_speed_10m": 8, "uv_index": 4},
          "daily": {"time": [d.isoformat() for d in dates],
                    "temperature_2m_max": [30] * 7, "temperature_2m_min": [22] * 7,
                    "apparent_temperature_max": [36 if d in bad else 28 for d in dates],
                    "precipitation_probability_max": [10] * 7, "precipitation_sum": [0] * 7,
                    "weather_code": [1] * 7, "uv_index_max": [7] * 7,
                    "sunrise": [f"{d.isoformat()}T06:05" for d in dates],
                    "sunset": [f"{d.isoformat()}T18:02" for d in dates]}}
    aq = {"hourly": {"time": times[:120], "us_aqi": [aqi] * 120, "pm2_5": [12] * 120},
          "current": {"us_aqi": aqi, "pm2_5": 12}}
    return fc, aq


@pytest.fixture
def located(athlete):
    Athlete.objects.filter(pk=athlete.pk).update(
        location_lat=17.39, location_lon=78.49, location_name="Hyderabad",
        location_source="city", location_city="Hyderabad", available_days=ALL_DAYS)
    athlete.refresh_from_db()
    return athlete


@pytest.fixture
def sky(monkeypatch, located):
    from apps.ingest import weather

    state = {"bad": set(), "calls": 0}

    def get(url, params):
        state["calls"] += 1
        fc, aq = forecast(located, state["bad"])
        return aq if "air-quality" in url else fc

    monkeypatch.setattr(weather, "_get_json", get)
    return state


def bad_run_day(athlete) -> dt.date:
    """A day in today+1 … today+3 whose next day is in the same Mon–Sun week."""
    today = athlete.local_today
    return next(today + dt.timedelta(days=i) for i in (1, 2, 3)
                if (today + dt.timedelta(days=i)).weekday() < 6)


def run_on(athlete, day, kind="EASY"):
    w = make_workout(athlete, day, kind=kind)
    return w


def test_weather_report_without_location(api):
    body = api.get("/api/weather/report/").json()
    assert body["available"] is False and body["reason"] == "no_location"
    assert body["hourly"] == [] and body["daily"] == [] and body["suggestions"] == []


def test_weather_report_outage(api, located):
    body = api.get("/api/weather/report/").json()
    assert body["available"] is False and body["reason"] == "unavailable"


def test_weather_report_shape(api, located, sky):
    day = bad_run_day(located)
    run_on(located, day)
    sky["bad"] = {day}
    body = api.get("/api/weather/report/").json()
    assert body["available"] is True
    assert body["now"]["aqi_level"] == "good" and body["now"]["uv_level"] == "moderate"
    assert body["now"]["aqi_meaning"]
    assert 24 <= len(body["hourly"]) <= 48
    assert {"run", "best"} <= set(body["hourly"][0])
    assert len(body["daily"]) == 7 and body["daily"][0]["sunrise"] == "06:05"
    assert body["sun"] == {"sunrise": "06:05", "sunset": "18:02"}
    bad = next(d for d in body["daily"] if d["date"] == day.isoformat())
    assert bad["run_verdict"] == "bad" and bad["reasons"]
    [run] = [r for r in body["runs"] if r["date"] == day.isoformat()]
    assert run["verdict"] == "bad" and run["suggestion_id"] is not None
    assert body["suggestions"][0]["id"] == run["suggestion_id"]
    assert all(set(w) >= {"date", "start", "end", "reason"} for w in body["best_windows"])
    assert body["hydration"] is not None and isinstance(body["advisories"], list)


def test_suggestion_apply_moves_the_run_and_resyncs_the_watch(
        api, located, sky, monkeypatch, django_capture_on_commit_callbacks):
    from apps.planning import tasks
    from apps.planning.presenters import _garmin_source
    from planning.garmin_workout import build_payload, payload_hash

    day = bad_run_day(located)
    w = run_on(located, day)
    w.garmin_workout_id = 555
    w.garmin_payload_hash = payload_hash(build_payload(_garmin_source(w)), w.date.isoformat())
    w.save()
    before = (w.title, w.kind, w.duration_s, w.steps)
    sky["bad"] = {day}
    r = api.post("/api/plan/weather-suggestions/check/")
    assert r.status_code == 200 and r.json()["created"] == 1
    listed = api.get("/api/plan/weather-suggestions/").json()
    assert listed["auto_apply"] is False
    [s] = listed["suggestions"]
    assert s["from_date"] == day.isoformat() and s["action"] == "move"
    assert s["text"].startswith("Weather: move ") and s["reasons"][0]["key"] == "heat"
    assert s["from_weather"]["verdict"] == "bad" and s["to_weather"]["verdict"] == "good"
    w.refresh_from_db()
    assert w.date == day                                     # nothing moved yet

    sent = []
    monkeypatch.setattr(tasks.garmin_push_task, "delay", lambda *a: sent.append(a))
    with django_capture_on_commit_callbacks(execute=True):
        r = api.post(f"/api/plan/weather-suggestions/{s['id']}/apply/")
    assert r.status_code == 200 and r.json()["status"] == "applied"
    w.refresh_from_db()
    assert w.date.isoformat() == s["to_date"] and w.moved_from == day
    assert (w.title, w.kind, w.duration_s, w.steps) == before          # never harder
    assert sent == [(located.pk, [w.pk], "send")]
    assert api.post(f"/api/plan/weather-suggestions/{s['id']}/apply/").status_code == 409
    # Checking again does not suggest the same move twice.
    assert api.post("/api/plan/weather-suggestions/check/").json()["created"] == 0


def test_dismissed_is_not_suggested_again(api, located, sky):
    day = bad_run_day(located)
    run_on(located, day)
    sky["bad"] = {day}
    [s] = api.post("/api/plan/weather-suggestions/check/").json()["suggestions"]
    r = api.post(f"/api/plan/weather-suggestions/{s['id']}/dismiss/")
    assert r.json()["status"] == "dismissed"
    assert api.post("/api/plan/weather-suggestions/check/").json()["created"] == 0
    assert api.get("/api/plan/weather-suggestions/").json()["suggestions"] == []
    assert len(api.get("/api/plan/weather-suggestions/?status=all").json()["suggestions"]) == 1
    assert api.post(f"/api/plan/weather-suggestions/{s['id']}/dismiss/").status_code == 409


def test_apply_refuses_when_the_workout_changed(api, located, sky):
    day = bad_run_day(located)
    w = run_on(located, day)
    sky["bad"] = {day}
    [s] = api.post("/api/plan/weather-suggestions/check/").json()["suggestions"]
    PlannedWorkout.objects.filter(pk=w.pk).update(status="completed")
    assert api.post(f"/api/plan/weather-suggestions/{s['id']}/apply/").status_code == 409
    w.refresh_from_db()
    assert w.date == day


def test_apply_refuses_when_the_target_day_is_taken(api, located, sky):
    day = bad_run_day(located)
    run_on(located, day)
    sky["bad"] = {day}
    [s] = api.post("/api/plan/weather-suggestions/check/").json()["suggestions"]
    run_on(located, dt.date.fromisoformat(s["to_date"]))
    assert api.post(f"/api/plan/weather-suggestions/{s['id']}/apply/").status_code == 409


def test_auto_apply_setting(api, located, sky):
    located.weather_auto_apply = True
    located.save()
    day = bad_run_day(located)
    w = run_on(located, day)
    sky["bad"] = {day}
    api.get("/api/weather/report/")
    s = WeatherSuggestion.objects.get(workout=w)
    assert s.status == "applied" and s.auto_applied is True
    w.refresh_from_db()
    assert w.date == s.to_date


def test_today_is_never_moved(api, located, sky):
    run_on(located, located.local_today)
    sky["bad"] = {located.local_today}
    assert api.post("/api/plan/weather-suggestions/check/").json()["created"] == 0


def test_suggestions_are_private(api, other_api, located, sky):
    day = bad_run_day(located)
    run_on(located, day)
    sky["bad"] = {day}
    [s] = api.post("/api/plan/weather-suggestions/check/").json()["suggestions"]
    assert other_api.post(f"/api/plan/weather-suggestions/{s['id']}/apply/").status_code == 404
    assert other_api.get("/api/plan/weather-suggestions/").json()["suggestions"] == []


def test_stale_suggestions_expire(api, located, sky):
    day = bad_run_day(located)
    w = run_on(located, day)
    sky["bad"] = {day}
    [s] = api.post("/api/plan/weather-suggestions/check/").json()["suggestions"]
    PlannedWorkout.objects.filter(pk=w.pk).update(date=day + dt.timedelta(days=1))
    assert api.get("/api/plan/weather-suggestions/").json()["suggestions"] == []
    assert WeatherSuggestion.objects.get(pk=s["id"]).status == "expired"


# --- §5 calendar feed -------------------------------------------------------------------------

def test_calendar_feed_lifecycle(api, athlete):
    anon = APIClient()
    assert api.get("/api/calendar-feed/").json()["enabled"] is False
    r = api.post("/api/calendar-feed/")
    assert r.status_code == 201
    feed = r.json()
    assert feed["url"].startswith("http") and feed["path"].startswith("/api/cal/")
    assert feed["webcal_url"].startswith("webcal://")
    assert feed["google_url"].startswith("https://calendar.google.com/")
    token = CalendarFeed.objects.get(athlete=athlete).token
    assert len(token) >= 40

    w = make_workout(athlete, athlete.local_today + dt.timedelta(days=2), kind="EASY")
    r = anon.get(feed["path"])
    assert r.status_code == 200 and r["Content-Type"].startswith("text/calendar")
    body = r.content.decode()
    assert f"UID:workout-{w.pk}@runcoach" in body and "SEQUENCE:0" in body
    assert "Walk warm-up" in body                                   # steps in DESCRIPTION
    etag, modified = r["ETag"], r["Last-Modified"]
    assert anon.get(feed["path"], HTTP_IF_NONE_MATCH=etag).status_code == 304

    PlannedWorkout.objects.filter(pk=w.pk).update(date=w.date + dt.timedelta(days=1))
    r = anon.get(feed["path"], HTTP_IF_NONE_MATCH=etag)
    assert r.status_code == 200 and r["ETag"] != etag
    assert "SEQUENCE:1" in r.content.decode()
    assert modified

    new = api.post("/api/calendar-feed/").json()
    assert new["path"] != feed["path"]
    assert anon.get(feed["path"]).status_code == 404
    assert anon.get(new["path"]).status_code == 200
    assert api.delete("/api/calendar-feed/").status_code == 204
    assert anon.get(new["path"]).status_code == 404
    assert api.get("/api/calendar-feed/").json()["enabled"] is False


def test_calendar_feed_has_no_health_data_and_only_own_items(api, athlete, other_athlete):
    from apps.planning.models import Race, StrengthSession

    make_workout(athlete, athlete.local_today + dt.timedelta(days=1), kind="EASY")
    make_workout(other_athlete, other_athlete.local_today + dt.timedelta(days=1), kind="EASY")
    Race.objects.create(athlete=athlete, name="City 10K",
                        date=athlete.local_today + dt.timedelta(days=30), distance_km=10,
                        start_time=dt.time(6, 30))
    StrengthSession.objects.create(athlete=athlete, date=athlete.local_today + dt.timedelta(days=3),
                                   title="Strength & drills", exercises=[
                                       {"name": "Calf raises", "sets": 2, "reps": 12}])
    HabitLog.objects.create(athlete=athlete, kind="smoke", at=timezone.now(),
                            local_date=athlete.local_today, quantity=4)
    wellness(athlete, resting_hr=57, hrv_overnight_avg=61)
    MetricEntry.objects.create(athlete=athlete, kind="weight", value=81.3,
                               recorded_at=timezone.now())
    path = api.post("/api/calendar-feed/").json()["path"]
    body = APIClient().get(path).content.decode()
    assert body.count("BEGIN:VEVENT") == 3
    assert "Calf raises" in body and "City 10K" in body
    assert "DTSTART:" in body and "Z\r\n" in body               # timed race in UTC
    for leak in ("81.3", "smoke", "cigarette", "HRV", "resting", "weight", "Intruder"):
        assert leak not in body, leak


def test_calendar_feed_needs_sign_in_to_manage(client, db):
    assert client.get("/api/calendar-feed/").status_code == 401
    assert client.get("/api/cal/" + "x" * 43 + ".ics").status_code == 404


# --- §7 experiments ----------------------------------------------------------------------------

def test_experiment_lifecycle(api, athlete, other_api):
    templates = api.get("/api/experiments/templates/").json()
    assert {t["kind"] for t in templates} == {"no_alcohol", "no_late_caffeine", "no_sugar",
                                              "smoke_free", "bed_by", "steps", "custom"}
    r = api.post("/api/experiments/", {"kind": "no_alcohol", "days": 14}, format="json")
    assert r.status_code == 201, r.json()
    exp = r.json()
    assert exp["status"] == "active" and exp["days"] == 14
    assert exp["progress"]["day"] == 1 and exp["result"]["final"] is False
    assert exp["chip"].startswith("No alcohol · day 1/14")
    # R17: several may run at once (up to 3); the same template overlapping → 400.
    assert api.post("/api/experiments/", {"kind": "no_alcohol"}, format="json").status_code == 400
    second = api.post("/api/experiments/", {"kind": "no_sugar"}, format="json")
    assert second.status_code == 201
    assert api.delete(f"/api/experiments/{second.json()['id']}/").status_code == 204

    HabitLog.objects.create(athlete=athlete, kind="alcohol", at=timezone.now(),
                            local_date=athlete.local_today, quantity=1)
    active = api.get("/api/experiments/active/").json()["experiment"]
    assert active["id"] == exp["id"] and active["adherence"]["today"] is False
    assert other_api.get(f"/api/experiments/{exp['id']}/").status_code == 404

    r = api.post(f"/api/experiments/{exp['id']}/stop/")
    assert r.json()["status"] == "stopped" and r.json()["result"]["final"] is True
    assert api.post(f"/api/experiments/{exp['id']}/stop/").status_code == 409
    r = api.patch(f"/api/experiments/{exp['id']}/", {"decision": "stop"}, format="json")
    assert r.json()["decision"] == "stop"
    assert api.delete(f"/api/experiments/{exp['id']}/").status_code == 204


def test_experiment_validation(api, athlete):
    assert api.post("/api/experiments/", {"kind": "nope"}, format="json").status_code == 400
    assert api.post("/api/experiments/", {"kind": "no_sugar", "days": 6},
                    format="json").status_code == 400
    assert api.post("/api/experiments/", {"kind": "no_sugar", "days": 43},
                    format="json").status_code == 400
    r = api.post("/api/experiments/", {"kind": "custom", "rule": {"habit": "private",
                                                                  "max_per_day": 1}},
                 format="json")
    assert r.status_code == 400
    r = api.post("/api/experiments/", {"kind": "no_sugar",
                                       "start": str(athlete.local_today - dt.timedelta(days=1))},
                 format="json")
    assert r.status_code == 400
    r = api.post("/api/experiments/", {"kind": "steps", "rule": {"min_steps": 8000},
                                       "start": str(athlete.local_today + dt.timedelta(days=3))},
                 format="json")
    assert r.status_code == 201
    assert r.json()["status"] == "scheduled" and r.json()["title"] == "8k steps a day"
    assert r.json()["progress"]["day"] == 0


def test_completed_experiment_result_compares_before_and_during(api, athlete):
    from apps.health.models import MoodLog

    today = athlete.local_today
    start, end = today - dt.timedelta(days=20), today - dt.timedelta(days=7)
    exp = Experiment.objects.create(athlete=athlete, kind="no_alcohol", title="No alcohol",
                                    start=start, end=end,
                                    rule={"habit": "alcohol", "max_per_day": 0})
    for i in range(1, 30):
        day = today - dt.timedelta(days=i)
        during = start < day <= end + dt.timedelta(days=1)     # mornings after rule days
        wellness(athlete, day, hrv_overnight_avg=55 if during else 46, resting_hr=58,
                 sleep_score=80)
    for i in range(14):
        MoodLog.objects.create(athlete=athlete, date=start + dt.timedelta(days=i), mood=4,
                               energy=4)
    from zoneinfo import ZoneInfo

    HabitLog.objects.create(athlete=athlete, kind="alcohol", quantity=2, at=dt.datetime.combine(
        start + dt.timedelta(days=3), dt.time(20, 0), tzinfo=ZoneInfo(athlete.timezone)))
    body = api.get(f"/api/experiments/{exp.pk}/").json()
    assert body["status"] == "completed"
    result = body["result"]
    assert result["final"] is True and result["adherence_pct"] == 93     # 13 of 14
    metrics = {m["key"]: m for m in result["metrics"]}
    assert metrics["hrv"]["direction"] == "better" and metrics["hrv"]["n_during"] == 14
    assert metrics["rhr"]["direction"] == "no_clear_difference"
    assert metrics["mood"]["enough_data"] is False                      # nothing before
    assert "not that it caused" in result["caveat"]
    assert result["share"]["lines"][0] == "14-day experiment: No alcohol"
    chip = api.get("/api/experiments/active/").json()["experiment"]
    assert chip["id"] == exp.pk                     # ended within 7 days, no decision yet


def test_bedtime_experiment_reads_garmin_sleep(api, athlete):
    from tests.r10_helpers import night

    today = athlete.local_today
    exp = Experiment.objects.create(athlete=athlete, kind="bed_by", title="Bed by 22:30",
                                    start=today - dt.timedelta(days=3), end=today + dt.timedelta(days=10),
                                    rule={"bedtime": "22:30"})
    night(athlete, today - dt.timedelta(days=2), bed=(22, 0))    # slept on day −3: kept
    night(athlete, today - dt.timedelta(days=1), bed=(23, 30))   # day −2: not kept
    body = api.get(f"/api/experiments/{exp.pk}/").json()
    series = body["adherence"]["series"]
    assert [d["kept"] for d in series[:2]] == [True, False]
    assert series[1]["display"] == "23:30"


# --- §8 goals ------------------------------------------------------------------------------------

def test_weight_goal_progress_milestones_and_badge(api, athlete, other_api):
    now = timezone.now()
    MetricEntry.objects.create(athlete=athlete, kind="weight", value=80.0,
                               recorded_at=now - dt.timedelta(days=1))
    r = api.post("/api/goals/", {"kind": "weight", "target": 70}, format="json")
    assert r.status_code == 201, r.json()
    goal = r.json()
    assert goal["start_value"] == 80.0 and goal["direction"] == "down"
    assert goal["progress_pct"] == 0 and goal["title"] == "Reach 70 kg"
    assert goal["projection"]["label"] == "estimate"
    MetricEntry.objects.create(athlete=athlete, kind="weight", value=74.5, recorded_at=now)
    goal = api.get(f"/api/goals/{goal['id']}/").json()
    assert goal["progress_pct"] == 55 and goal["display"]["current"] == "74.5 kg"
    reached = {m["pct"]: m["reached_on"] for m in goal["milestones"]}
    assert reached[25] and reached[50] and reached[75] is None
    keys = set(Achievement.objects.filter(athlete=athlete).values_list("key", flat=True))
    assert {f"goal_{goal['id']}_25", f"goal_{goal['id']}_50"} <= keys
    assert other_api.get(f"/api/goals/{goal['id']}/").status_code == 404
    MetricEntry.objects.create(athlete=athlete, kind="weight", value=69.8,
                               recorded_at=now + dt.timedelta(seconds=1))
    goal = api.get(f"/api/goals/{goal['id']}/").json()
    assert goal["status"] == "achieved" and goal["progress_pct"] == 100
    assert api.get("/api/goals/").json() == []
    assert len(api.get("/api/goals/?status=achieved").json()) == 1


def test_race_time_goal_from_garmin_predictions(api, athlete):
    today = athlete.local_today
    r = api.post("/api/goals/", {"kind": "race_time", "target": 3000}, format="json")
    assert r.status_code == 400                               # distance_km required
    r = api.post("/api/goals/", {"kind": "race_time", "target": 3000, "distance_km": 10},
                 format="json")
    assert r.status_code == 400 and "start_value" in r.json()["detail"]
    wellness(athlete, today - dt.timedelta(days=1), race_pred_10k_s=3600)
    r = api.post("/api/goals/", {"kind": "race_time", "target": 3000, "distance_km": 10,
                                 "target_date": str(today + dt.timedelta(days=120))},
                 format="json")
    goal = r.json()
    assert goal["title"] == "10K in 50:00" and goal["display"]["start"] == "1:00:00"
    wellness(athlete, today, race_pred_10k_s=3300)
    goal = api.get(f"/api/goals/{goal['id']}/").json()
    assert goal["progress_pct"] == 50 and goal["current_source"] == "garmin_prediction"


def test_custom_goal_values_and_chip(api, athlete):
    r = api.post("/api/goals/", {"kind": "custom", "target": 20, "unit": "push-ups"},
                 format="json")
    assert r.status_code == 400
    goal = api.post("/api/goals/", {"kind": "custom", "target": 20, "unit": "push-ups",
                                    "start_value": 5, "title": "20 push-ups"},
                    format="json").json()
    r = api.post(f"/api/goals/{goal['id']}/values/", {"value": 11}, format="json")
    assert r.status_code == 201 and r.json()["progress_pct"] == 40
    chip = api.get("/api/goals/chip/").json()
    assert chip["goal"]["id"] == goal["id"] and chip["text"].startswith("20 push-ups: 40%")
    weight = api.post("/api/goals/", {"kind": "weight", "target": 70, "start_value": 80},
                      format="json").json()
    assert api.post(f"/api/goals/{weight['id']}/values/", {"value": 1},
                    format="json").status_code == 400
    r = api.patch(f"/api/goals/{goal['id']}/", {"status": "abandoned"}, format="json")
    assert r.json()["status"] == "abandoned"
    assert api.delete(f"/api/goals/{goal['id']}/").status_code == 204


def test_distance_and_weekly_km_goals(api, athlete):
    from tests.r10_helpers import run

    today = athlete.local_today
    run(athlete, today - dt.timedelta(days=10), km=4.0)
    distance = api.post("/api/goals/", {"kind": "distance", "target": 10}, format="json").json()
    assert distance["start_value"] == 4.0
    run(athlete, today, km=7.0)
    distance = api.get(f"/api/goals/{distance['id']}/").json()
    assert distance["current"] == 7.0 and distance["progress_pct"] == 50
    weekly = api.post("/api/goals/", {"kind": "weekly_km", "target": 20}, format="json").json()
    assert weekly["current"] == 7.0


# --- §9 heart ---------------------------------------------------------------------------------------

def make_run(athlete, day, *, hr_run=150, warm=None, minutes=30, speed=1000 / 600, cap_from=None):
    """A run with 1 Hz records: `minutes` of steady running at `speed`, HR `hr_run`
    (or crossing 160 from second `cap_from`)."""
    started = timezone.make_aware(dt.datetime.combine(day, dt.time(6, 30)))
    activity = Activity.objects.create(athlete=athlete, source="garmin_sync", sport="running",
                                       started_at=started, local_date=day,
                                       total_timer_s=minutes * 60,
                                       total_distance_m=speed * minutes * 60,
                                       segmentation_version=1)
    seconds = minutes * 60
    records = []
    for t in range(seconds):
        hr = hr_run if cap_from is None or t < cap_from else 160
        records.append(ActivityRecord(activity=activity, offset_s=t, heart_rate=hr,
                                      speed_mps=speed, distance_m=speed * t,
                                      latitude=17.4 if t == 0 else None,
                                      longitude=78.5 if t == 0 else None))
    ActivityRecord.objects.bulk_create(records)
    Segment.objects.create(activity=activity, index=0, kind="run", start_offset_s=0,
                           duration_s=seconds, distance_m=speed * seconds)
    return activity


def test_heart_endpoint(api, athlete, no_real_r13_queue):
    today = athlete.local_today
    caps = [300, 360, 480, 600, 660]
    for i, cap in enumerate(caps):
        make_run(athlete, today - dt.timedelta(days=20 - 4 * i), hr_run=148, cap_from=cap,
                 minutes=15)
    r = api.get("/api/health/heart/?range=3m")
    assert r.status_code == 200
    body = r.json()
    assert body["ref_hr"] == 150 and body["ref_pace_s_per_km"] == 622
    assert len(body["runs"]) == 5
    assert [run["duration_under_cap_s"] for run in body["runs"]] == pytest.approx(
        [c + 5 for c in caps], abs=6)
    assert body["since_day1"] is not None
    assert body["headline"].startswith("Day 1 (")
    assert body["headline"].endswith("Now: 11 min.")
    assert len(body["key_numbers"]) == 4 and body["key_numbers"][0]["better"] is True
    assert body["weather_pending"] is True
    assert any(name == "heart_weather_task" for name, *_ in no_real_r13_queue)
    assert RunHeartStats.objects.filter(activity__athlete=athlete).count() == 5
    assert "not why" in body["caveat"]
    assert api.get("/api/health/heart/?ref_hr=90").status_code == 400
    assert api.get("/api/health/heart/?range=2d").status_code == 400
    custom = api.get("/api/health/heart/?ref_hr=148&ref_pace=600").json()
    assert custom["runs"][-1]["pace_at_ref_hr"] == 600


def test_heart_weather_fill_flags_hot_runs(api, athlete, monkeypatch):
    from apps.health.heart import fill_weather
    from apps.ingest import weather

    today = athlete.local_today
    old = make_run(athlete, today - dt.timedelta(days=30), hr_run=150, minutes=12)
    new = make_run(athlete, today - dt.timedelta(days=1), hr_run=150, minutes=12)

    def get(url, params):
        lat, lon = params["latitude"], params["longitude"]
        assert (lat, lon) == (17.4, 78.5)
        times, feels = [], []
        for a in (old, new):
            at = a.started_at.astimezone(dt.timezone.utc).replace(minute=0)
            times.append(at.strftime("%Y-%m-%dT%H:00"))
            feels.append(33.0 if a is old else 24.0)
        return {"hourly": {"time": times, "temperature_2m": feels,
                           "apparent_temperature": feels, "dew_point_2m": [20, 20],
                           "relative_humidity_2m": [70, 70]}}

    monkeypatch.setattr(weather, "_get_json", get)
    assert fill_weather(athlete) == 2
    assert ActivityWeather.objects.get(activity=old).feels_like_c == 33.0
    body = api.get("/api/health/heart/?range=3m").json()
    hot = {run["activity_id"]: run["hot"] for run in body["runs"]}
    assert hot == {old.pk: True, new.pk: False}
    assert body["weather_pending"] is False
    assert len(body["trend_cool"]) == 1


def test_heart_is_private(api, other_api, athlete):
    make_run(athlete, athlete.local_today, minutes=12)
    assert other_api.get("/api/health/heart/").json()["runs"] == []


# --- account deletion ----------------------------------------------------------------------------

def test_account_deletion_removes_r14_rows(api, athlete, other_athlete):
    day = athlete.local_today + dt.timedelta(days=1)
    w = make_workout(athlete, day, kind="EASY")
    WeatherSuggestion.objects.create(athlete=athlete, workout=w, workout_title="x",
                                     workout_kind="EASY", from_date=day, to_date=day,
                                     action="move", text="t", reason="r")
    CalendarFeed.objects.create(athlete=athlete, token="t" * 43)
    CalendarFeedItem.objects.create(athlete=athlete, uid="workout-1@runcoach",
                                    content_hash="h", updated_at=timezone.now())
    Experiment.objects.create(athlete=athlete, kind="no_sugar", title="x", start=day, end=day,
                              rule={})
    Goal.objects.create(athlete=athlete, kind="weight", title="x", target=70,
                        start_date=day)
    run = make_run(athlete, athlete.local_today, minutes=11)
    ActivityWeather.objects.create(activity=run, feels_like_c=30)
    RunHeartStats.objects.create(activity=run, key="k", payload={})
    Goal.objects.create(athlete=other_athlete, kind="weight", title="keep", target=70,
                        start_date=day)
    assert api.delete("/api/auth/me/", {"password": "correct-horse-battery-1"},
                      format="json").status_code == 204
    for model in (WeatherSuggestion, CalendarFeed, CalendarFeedItem, Experiment):
        assert not model.objects.filter(athlete_id=athlete.pk).exists(), model
    assert list(Goal.objects.values_list("title", flat=True)) == ["keep"]
    assert not ActivityWeather.objects.exists() and not RunHeartStats.objects.exists()
    assert active_plan  # helper import kept for readers
