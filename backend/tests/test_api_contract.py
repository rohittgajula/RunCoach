"""Spec §5 shapes. The frontend is built against these keys, so they are asserted
exactly rather than loosely."""

import datetime as dt

import pytest
from django.utils import timezone

from apps.activities.models import Activity, ActivityMetrics
from apps.planning.plan_store import accept_plan

WORKOUT_KEYS = {"id", "date", "title", "kind", "phase", "duration_s", "load", "steps",
                "description", "purpose", "target_zone", "fueling", "status",
                "completed_activity_id", "actual", "compliance", "review",
                # R7
                "guard", "adjusted_by", "original_steps", "original",
                "garmin_workout_id", "garmin_synced_at", "garmin_status"}
STEP_KEYS = {"kind", "duration_s", "intensity", "label", "pace_min_s", "pace_max_s",
             "hr_min", "hr_max"}
FUEL_KEYS = {"before", "during", "after", "carbs_g_during_per_h"}
CARD_KEYS = {"id", "name", "sport", "device", "start", "duration_s", "distance_m", "load",
             "run_distance_m", "walk_distance_m", "run_fraction", "longest_run_s", "steps",
             "journalled", "reviewed_thread_id", "unplanned"}
SUMMARY_KEYS = {"id", "name", "goal", "status", "race", "phase_count", "start", "end",
                "current_phase_id", "phases"}
PHASE_KEYS = {"id", "order", "name", "kind", "start", "end", "description"}
MEAL_KEYS = {"id", "eaten_at", "local_date", "meal_type", "description", "photo_url", "items",
             "kcal", "carbs_g", "protein_g", "fat_g", "source", "ai_confidence"}


@pytest.fixture
def active(athlete, proposed_plan):
    return accept_plan(proposed_plan)


def make_run(athlete, day, minutes=30):
    activity = Activity.objects.create(
        athlete=athlete, source="garmin_sync", sport="running", started_at=timezone.now(),
        local_date=day, total_timer_s=minutes * 60, total_distance_m=4000, calories=300)
    ActivityMetrics.objects.create(
        activity=activity, run_distance_m=3000, walk_distance_m=1000, run_fraction=0.75,
        run_duration_s=1500, walk_duration_s=300, stop_duration_s=0, run_block_count=3,
        longest_run_m=1200, longest_run_s=480, custom_load=55, algorithm_version=1)
    return activity


def test_calendar_shape(api, athlete, active):
    today = athlete.local_today
    make_run(athlete, today)
    r = api.get("/api/calendar/", {"start": str(today - dt.timedelta(days=2)),
                                   "end": str(today + dt.timedelta(days=12))})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"today", "days", "weeks"}
    assert body["today"] == str(today)
    assert len(body["days"]) == 15
    for day in body["days"]:
        assert set(day) == {"date", "items", "rest"}
        assert (day["rest"] is None) == bool(day["items"])
        assert day["rest"] in (None, "Rest", "Recovery day")
        for item in day["items"]:
            assert item["type"] in ("workout", "activity")
            if item["type"] == "workout":
                assert set(item["workout"]) == WORKOUT_KEYS
                assert set(item["workout"]["fueling"]) == FUEL_KEYS
                assert set(item["workout"]["phase"]) == {"id", "name", "kind"}
                for step in item["workout"]["steps"]:
                    assert set(step) == STEP_KEYS
            else:
                assert set(item["activity"]) == CARD_KEYS
    assert any(i["type"] == "workout" for d in body["days"] for i in d["items"])
    assert any(i["type"] == "activity" for d in body["days"] for i in d["items"])
    for week in body["weeks"]:
        assert set(week) == {"start", "end", "planned_s", "planned_load", "actual_s", "actual_load"}
        assert dt.date.fromisoformat(week["start"]).weekday() == 0


def test_calendar_range_limit(api, athlete):
    r = api.get("/api/calendar/", {"start": "2026-01-01", "end": "2026-03-15"})
    assert r.status_code == 400 and "detail" in r.json()


def test_proposed_plans_stay_off_the_calendar(api, athlete, proposed_plan):
    r = api.get("/api/calendar/")
    assert not any(i["type"] == "workout" for d in r.json()["days"] for i in d["items"])


def test_plan_endpoints(api, athlete, proposed_plan):
    assert api.get("/api/plans/active/").status_code == 404
    listed = api.get("/api/plans/", {"status": "proposed"}).json()
    assert [p["id"] for p in listed] == [proposed_plan.pk]
    assert set(listed[0]) == SUMMARY_KEYS
    assert set(listed[0]["phases"][0]) == PHASE_KEYS
    r = api.post(f"/api/plans/{proposed_plan.pk}/accept/")
    assert r.status_code == 200
    plan = r.json()
    assert set(plan) == SUMMARY_KEYS | {"summary", "weeks", "adjustments"}
    assert plan["status"] == "active" and plan["phase_count"] == len(plan["phases"])
    assert plan["current_phase_id"] == plan["phases"][0]["id"]
    for week in plan["weeks"]:
        assert set(week) == {"start", "end", "planned_minutes", "planned_load", "phase_id"}
    assert api.get("/api/plans/active/").json()["id"] == proposed_plan.pk
    assert api.post(f"/api/plans/{proposed_plan.pk}/decline/").status_code == 409


def test_workout_patch_move_and_skip(api, athlete, active):
    workout = active.workouts.order_by("date").first()
    new_day = workout.date + dt.timedelta(days=1)
    r = api.patch(f"/api/workouts/{workout.pk}/", {"date": str(new_day)}, format="json")
    assert r.status_code == 200 and r.json()["date"] == str(new_day)
    workout.refresh_from_db()
    assert workout.moved_from is not None
    r = api.patch(f"/api/workouts/{workout.pk}/", {"status": "skipped"}, format="json")
    assert r.json()["status"] == "skipped"
    assert api.patch(f"/api/workouts/{workout.pk}/", {"date": "2000-01-01"},
                     format="json").status_code == 400


def test_diet_day_shape(api, athlete, active):
    athlete.weight_kg = 70
    athlete.save()
    day = active.workouts.order_by("date").first().date
    r = api.post("/api/diet/meals/", {
        "meal_type": "breakfast", "eaten_at": f"{day}T08:00:00+05:30", "description": "idli",
        "items": [{"name": "idli", "quantity": "3", "kcal": 180, "carbs_g": 36,
                   "protein_g": 6, "fat_g": 1}], "source": "manual"}, format="json")
    assert r.status_code == 201, r.content
    assert set(r.json()) == MEAL_KEYS and r.json()["kcal"] == 180
    body = api.get("/api/diet/day/", {"date": str(day)}).json()
    # R8 §D added weather_tips and targets.water_bonus_ml (0 without weather).
    assert set(body) == {"date", "targets", "eaten", "burn", "meals", "fueling",
                         "missing_profile", "weather_tips"}
    assert set(body["targets"]) == {"kcal", "carbs_g", "protein_g", "fat_g", "water_ml",
                                    "water_bonus_ml", "rationale"}
    assert set(body["eaten"]) == {"kcal", "carbs_g", "protein_g", "fat_g"}
    assert set(body["burn"]) == {"bmr", "non_exercise", "exercise", "exercise_source"}
    assert body["eaten"]["kcal"] == 180
    assert body["burn"]["exercise_source"] == "planned"
    assert set(body["fueling"][0]) == {"workout_id", "title", "weather_note"} | FUEL_KEYS
    assert set(body["missing_profile"]) == {"height_cm", "sex", "date_of_birth"}

    meal_id = body["meals"][0]["id"]
    r = api.patch(f"/api/diet/meals/{meal_id}/", {"items": []}, format="json")
    assert r.json()["kcal"] == 0
    assert api.delete(f"/api/diet/meals/{meal_id}/").status_code == 204


def test_diet_trend_shape(api, athlete):
    body = api.get("/api/diet/trend/", {"range": "3m"}).json()
    assert len(body["series"]) == 91
    assert set(body["series"][0]) == {"date", "intake_kcal", "target_kcal", "weight_kg"}
    assert set(body["summary"]) == {"avg_balance_kcal", "predicted_kg_per_week",
                                    "actual_kg_per_week", "logged_days_last_7"}


def test_meal_estimate_without_ai_is_503(api, settings):
    from apps.coaching import client

    settings.OPENAI_API_KEY = ""
    client._CLIENTS.clear()
    r = api.post("/api/diet/meals/estimate/", {"text": "2 dosa"}, format="multipart")
    assert r.status_code == 503 and "detail" in r.json()


def test_profile_summary_and_fitness(api, athlete, active):
    make_run(athlete, athlete.local_today - dt.timedelta(days=3))
    body = api.get("/api/profile/summary/").json()
    assert set(body) == {"athlete", "wellness", "fitness", "status_spark", "active_plan", "memory_count"}
    assert set(body["athlete"]) == {"display_name", "threshold_pace_s", "weight_kg",
                                    "easy_pace_min", "easy_pace_max"}
    assert set(body["fitness"]) == {"value", "fatigue", "form", "status", "spark"}
    assert len(body["fitness"]["spark"]) == 42 and len(body["status_spark"]) == 42
    assert body["fitness"]["status"] == "insufficient_data"
    assert body["active_plan"]["id"] == active.pk
    fit = api.get("/api/metrics/fitness/", {"range": "6m"}).json()
    assert len(fit["series"]) == 182
    assert set(fit["current"]) == {"fitness", "fatigue", "form", "status"}


def test_metric_entries_mirror_weight(api, athlete):
    r = api.post("/api/metrics/entries/", {"kind": "weight", "value": 71.5}, format="json")
    assert r.status_code == 201 and set(r.json()) == {"id", "value", "recorded_at", "source"}
    api.post("/api/metrics/entries/", {"kind": "weight", "value": 80,
                                       "recorded_at": "2020-01-01"}, format="json")
    athlete.refresh_from_db()
    assert athlete.weight_kg == 71.5           # back-fill does not overwrite current
    body = api.get("/api/metrics/entries/", {"kind": "weight", "range": "1y"}).json()
    assert body["kind"] == "weight" and body["current"]["value"] == 71.5
    assert len(body["entries"]) == 1           # the 2020 one is outside the range
    assert api.post("/api/metrics/entries/", {"kind": "weight", "value": 720},
                    format="json").status_code == 400
    assert api.delete(f"/api/metrics/entries/{r.json()['id']}/").status_code == 204
    athlete.refresh_from_db()
    assert athlete.weight_kg == 80


def test_memory_endpoints(api):
    r = api.post("/api/memory/", {"text": "Has a sore left knee."}, format="json")
    assert r.status_code == 201
    assert set(r.json()) == {"id", "text", "source", "created_at"}
    assert api.post("/api/memory/", {"text": "has a sore left knee"}, format="json").status_code == 200
    assert len(api.get("/api/memory/").json()) == 1
    assert api.delete(f"/api/memory/{r.json()['id']}/").status_code == 204
