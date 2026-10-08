"""R16 §A: edit a workout / a week (API + service). Garmin is always the fake client."""

import datetime as dt

import pytest

from apps.planning.models import GarminUpload, PlannedWorkout
from tests.r7_helpers import active_plan, make_workout, run_walk_steps, tomorrow
from tests.test_r7_garmin_send import FakeGarmin, fake  # noqa: F401 — fixture


def edit(api, w, **body):
    return api.patch(f"/api/workouts/{w.pk}/edit/", body, format="json")


def run_s(steps):
    return sum(s["duration_s"] for s in steps if s["intensity"] != "walk")


def easy_steps(minutes=30, hr=(130, 145)):
    return [{"kind": "run", "duration_s": minutes * 60, "intensity": "easy",
             "label": f"Easy run {minutes}:00", "pace_min_s": 600, "pace_max_s": 645,
             "hr_min": hr[0], "hr_max": hr[1]}]


def test_editor_model(api, athlete):
    w = make_workout(athlete, tomorrow(athlete))
    body = api.get(f"/api/workouts/{w.pk}/edit/").json()
    assert body["editable"] is True and body["notes_only"] is False and body["reason"] is None
    assert body["total_s"] == w.duration_s and body["run_s"] == 720
    assert body["steps"][1]["repeat"] == 3
    assert body["limits"]["total_min_s"] == 300 and body["limits"]["hr_min"] == 40
    assert body["hr"]["ceiling"] == 155 and body["pace"] == {"easy_low": 600, "easy_high": 645}
    assert body["planned"] is None and body["edited_by"] is None


def test_add_minutes_saves_marks_and_keeps_generated_version(api, athlete):
    w = make_workout(athlete, tomorrow(athlete))
    w.title = "23m run/walk"
    w.save()
    r = edit(api, w, add_minutes=4)
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["edited_by"] == "user" and body["edited_via"] == "app" and body["edited_at"]
    assert body["duration_s"] == w.duration_s + 240 and body["title"] == "27m run/walk"
    assert body["planned"] == {"title": "23m run/walk", "kind": "RUN_WALK",
                               "duration_s": w.duration_s, "run_s": 720}
    assert body["can_edit"] and body["can_undo_edit"]
    assert body["edit"]["changed"] and not body["edit"]["dry_run"]
    assert body["edit"]["summary"].endswith("23 → 27 min")
    assert body["warnings"] == [{"key": "run_increase", "text": body["warnings"][0]["text"]}]
    assert body["watch"] == {"was_on_watch": False, "status": "not_on_watch", "detail": ""}
    w.refresh_from_db()
    assert w.edited_by == "user" and w.pre_edit["steps"] == run_walk_steps()
    assert w.load > 30.0 or w.load > 0 and w.fueling
    # A second edit keeps the ORIGINAL generated version as the baseline.
    edit(api, w, add_minutes=1)
    w.refresh_from_db()
    assert w.pre_edit["duration_s"] == sum(s["duration_s"] for s in run_walk_steps())


def test_dry_run_previews_without_saving(api, athlete):
    w = make_workout(athlete, tomorrow(athlete))
    r = edit(api, w, total_minutes=40, dry_run=True)
    assert r.status_code == 200 and r.json()["edit"]["dry_run"] is True
    assert r.json()["duration_s"] == 2400 and r.json()["warnings"]
    w.refresh_from_db()
    assert w.edited_by == "" and w.duration_s != 2400 and w.pre_edit is None


def test_full_steps_replace_with_targets(api, athlete):
    w = make_workout(athlete, tomorrow(athlete))
    steps = [{"kind": "warmup", "duration_s": 300},
             {"repeat": 3, "steps": [{"kind": "run", "duration_s": 180, "hr_low": 125,
                                      "hr_high": 140},
                                     {"kind": "walk", "duration_s": 60}]},
             {"kind": "run", "duration_s": 300, "pace_low": 600, "pace_high": 660,
              "note": "relaxed"},
             {"kind": "cooldown", "duration_s": 300}]
    body = edit(api, w, steps=steps, notes="Flat route").json()
    assert body["duration_s"] == 300 + 3 * 240 + 600 and body["notes"] == "Flat route"
    assert body["steps"][1]["target"] == "hr" and body["steps"][7]["target"] == "pace"
    assert body["steps"][7]["label"] == "Run 5:00 · relaxed"
    editor = api.get(f"/api/workouts/{w.pk}/edit/").json()
    assert editor["steps"][1]["repeat"] == 3 and editor["edited_by"] == "user"
    assert editor["planned"]["duration_s"] == sum(s["duration_s"] for s in run_walk_steps())


@pytest.mark.parametrize("body", [
    {}, {"total_minutes": 2}, {"add_minutes": "x"}, {"apply_to": "legs", "add_minutes": 1},
    {"hr_low": 100}, {"hr_low": 120, "hr_high": 240},
    {"steps": [{"kind": "run", "duration_s": 3}]}, {"add_minutes": -30},
    {"notes": "x" * 1001},
])
def test_invalid_edits_are_400(api, athlete, body):
    w = make_workout(athlete, tomorrow(athlete))
    r = edit(api, w, **body)
    assert r.status_code == 400 and r.json()["detail"]
    w.refresh_from_db()
    assert w.edited_by == ""


def test_not_editable_is_409(api, athlete):
    past = make_workout(athlete, athlete.local_today - dt.timedelta(days=1))
    done = make_workout(athlete, tomorrow(athlete), status="completed")
    skipped = make_workout(athlete, tomorrow(athlete, 2), status="skipped")
    for w in (past, done, skipped):
        r = edit(api, w, add_minutes=2)
        assert r.status_code == 409 and r.json()["detail"]
        assert api.get(f"/api/workouts/{w.pk}/").json()["can_edit"] is False
    race = make_workout(athlete, tomorrow(athlete, 3), kind="RACE")
    assert edit(api, race, add_minutes=2).status_code == 409
    body = edit(api, race, notes="Bib 512").json()
    assert body["notes"] == "Bib 512" and body["can_edit"] and body["can_undo_edit"]
    assert api.get(f"/api/workouts/{race.pk}/edit/").json()["notes_only"] is True


def test_today_is_editable(api, athlete):
    w = make_workout(athlete, athlete.local_today)
    assert edit(api, w, add_minutes=-2).status_code == 200


def test_undo_restores_the_generated_version(api, athlete):
    w = make_workout(athlete, tomorrow(athlete))
    original = (w.title, w.duration_s, w.steps)
    assert api.post(f"/api/workouts/{w.pk}/edit/undo/").status_code == 409   # nothing to undo
    edit(api, w, add_walk_breaks=1, notes="hm")
    r = api.post(f"/api/workouts/{w.pk}/edit/undo/")
    assert r.status_code == 200
    body = r.json()
    assert body["edited_by"] is None and body["planned"] is None and body["notes"] == ""
    assert body["warnings"] == [] and "back to the plan" in body["edit"]["summary"]
    w.refresh_from_db()
    assert (w.title, w.duration_s, w.steps) == original and w.pre_edit is None


def test_hard_neighbour_and_ceiling_warnings(api, athlete):
    day = tomorrow(athlete, 2)
    make_workout(athlete, day + dt.timedelta(days=1), kind="INTERVALS")
    w = make_workout(athlete, day)
    body = edit(api, w, hr_low=150, hr_high=170).json()
    keys = {x["key"] for x in body["warnings"]}
    assert {"hr_above_ceiling", "hard_days_in_a_row"} <= keys
    assert PlannedWorkout.objects.get(pk=w.pk).edited_by == "user"       # never blocked


def test_tenant_isolation(api, other_api, athlete, other_athlete):
    w = make_workout(athlete, tomorrow(athlete))
    assert other_api.get(f"/api/workouts/{w.pk}/edit/").status_code == 404
    assert other_api.patch(f"/api/workouts/{w.pk}/edit/", {"add_minutes": 2},
                           format="json").status_code == 404
    assert other_api.post(f"/api/workouts/{w.pk}/edit/undo/").status_code == 404
    monday = tomorrow(athlete) - dt.timedelta(days=tomorrow(athlete).weekday())
    r = other_api.post("/api/plan/week-edit/", {"week_start": str(monday),
                                                "action": "add_minutes", "value": 2},
                       format="json")
    assert r.status_code == 404                          # no active plan of their own
    active_plan(other_athlete)
    r = other_api.post("/api/plan/week-edit/", {"week_start": str(monday),
                                                "action": "add_minutes", "value": 2},
                       format="json")
    assert r.status_code == 200 and r.json()["changed"] == []
    w.refresh_from_db()
    assert w.edited_by == ""


def _next_week(athlete):
    today = athlete.local_today
    return today + dt.timedelta(days=7 - today.weekday())


def test_week_edit(api, athlete):
    monday = _next_week(athlete)
    a = make_workout(athlete, monday)
    b = make_workout(athlete, monday + dt.timedelta(days=2), kind="EASY", steps=easy_steps(30))
    long = make_workout(athlete, monday + dt.timedelta(days=5), kind="LONG",
                        steps=easy_steps(60))
    rest = make_workout(athlete, monday + dt.timedelta(days=3), kind="REST", steps=[])
    later = make_workout(athlete, monday + dt.timedelta(days=8))
    r = api.post("/api/plan/week-edit/", {"week_start": str(monday), "action": "add_minutes",
                                          "value": 2, "kinds": ["RUN_WALK", "EASY"]},
                 format="json")
    assert r.status_code == 200, r.json()
    body = r.json()
    assert [c["workout_id"] for c in body["changed"]] == [a.pk, b.pk]
    assert body["watch"]["not_on_watch"] == 2 and body["dry_run"] is False
    for w in (a, b, long, rest, later):
        w.refresh_from_db()
    assert a.edited_by == b.edited_by == "user" and a.duration_s == 1380 + 120
    assert long.edited_by == rest.edited_by == later.edited_by == ""

    r = api.post("/api/plan/week-edit/", {"week_start": str(monday), "action": "add_walk_breaks",
                                          "value": 10}, format="json").json()
    assert {c["workout_id"] for c in r["changed"]} == {b.pk, long.pk}
    assert {s["workout_id"] for s in r["skipped"]} == {a.pk}            # nothing to break up
    r = api.post("/api/plan/week-edit/", {"week_start": str(monday), "action": "set_hr_range",
                                          "value": {"hr_low": 120, "hr_high": 140},
                                          "dry_run": True}, format="json").json()
    assert r["dry_run"] and len(r["changed"]) == 3
    a.refresh_from_db()
    assert all(s["hr_max"] != 140 for s in a.steps if s["intensity"] != "walk")
    r = api.post("/api/plan/week-edit/", {"week_start": str(monday), "action": "scale",
                                          "value": 1.5}, format="json").json()
    assert {w["key"] for w in r["warnings"]} >= {"run_increase"}, r


@pytest.mark.parametrize("body", [
    {"week_start": "nope", "action": "scale", "value": 1.1},
    {"week_start": "2026-10-12", "action": "explode", "value": 1},
    {"week_start": "2026-10-12", "action": "scale", "value": 9},
    {"week_start": "2026-10-12", "action": "set_hr_range", "value": 5},
    {"week_start": "2026-10-12", "action": "add_minutes", "value": 2, "kinds": "EASY"},
])
def test_week_edit_400(api, athlete, body):
    active_plan(athlete)
    assert api.post("/api/plan/week-edit/", body, format="json").status_code == 400


# --- watch ------------------------------------------------------------------------------------

def test_edit_resends_to_the_watch(api, athlete, fake):
    w = make_workout(athlete, tomorrow(athlete))
    assert api.post(f"/api/workouts/{w.pk}/garmin/").status_code == 200
    w.refresh_from_db()
    old_id = w.garmin_workout_id
    fake.calls.clear()
    body = edit(api, w, steps=[{"kind": "warmup", "duration_s": 300},
                               {"kind": "run", "duration_s": 1200, "pace_low": 600,
                                "pace_high": 660},
                               {"kind": "cooldown", "duration_s": 300}]).json()
    assert body["watch"]["was_on_watch"] is True and body["watch"]["status"] == "updated"
    assert body["garmin_status"] == "synced" and body["garmin_workout_id"] != old_id
    assert ("delete", old_id) in fake.calls and fake.kinds().count("upload") == 1
    uploaded = next(c[1] for c in fake.calls if c[0] == "upload")
    run = uploaded["workoutSegments"][0]["workoutSteps"][1]
    assert run["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    assert run["targetValueOne"] == round(1000 / 660, 4)
    # one RunCoach copy on the day, registered
    assert list(GarminUpload.objects.filter(athlete=athlete).values_list(
        "garmin_workout_id", flat=True)) == [body["garmin_workout_id"]]
    # Undo re-sends the generated version too.
    fake.calls.clear()
    body = api.post(f"/api/workouts/{w.pk}/edit/undo/").json()
    assert body["watch"]["status"] == "updated" and fake.kinds().count("upload") == 1
    # dry-run never touches Garmin
    fake.calls.clear()
    body = edit(api, w, add_minutes=1, dry_run=True).json()
    assert body["watch"]["status"] == "pending" and fake.calls == []


def test_edit_notes_go_into_the_garmin_description(api, athlete, fake):
    w = make_workout(athlete, tomorrow(athlete))
    api.post(f"/api/workouts/{w.pk}/garmin/")
    fake.calls.clear()
    edit(api, w, notes="Bring a gel")
    uploaded = next(c[1] for c in fake.calls if c[0] == "upload")
    assert uploaded["description"].endswith("Notes: Bring a gel")


def test_edit_with_breaker_open_still_saves(api, athlete, fake, monkeypatch):
    w = make_workout(athlete, tomorrow(athlete))
    api.post(f"/api/workouts/{w.pk}/garmin/")
    monkeypatch.setattr("apps.ingest.tasks.garmin_blocked", lambda: True)
    body = edit(api, w, add_minutes=2).json()
    assert body["watch"]["status"] == "failed" and body["garmin_status"] == "changed"
    assert body["edited_by"] == "user"


def test_queue_timeout_is_pending(api, athlete, monkeypatch):
    from apps.planning import tasks

    w = make_workout(athlete, tomorrow(athlete))
    PlannedWorkout.objects.filter(pk=w.pk).update(garmin_workout_id=77, garmin_payload_hash="x")
    monkeypatch.setattr(tasks, "run_garmin_push",
                        lambda *a, **k: {"ok": False, "code": "queue", "results": []})
    body = edit(api, w, add_minutes=2).json()
    assert body["watch"]["status"] == "pending"


# --- the plan's own changes leave edited sessions alone -------------------------------------------

def test_auto_adjust_never_touches_an_edited_session(athlete):
    from apps.planning import auto_adjust

    plan = active_plan(athlete)
    w = make_workout(athlete, tomorrow(athlete))
    PlannedWorkout.objects.filter(pk=w.pk).update(edited_by="user")
    w.refresh_from_db()
    [up] = [u for u in auto_adjust.upcoming(athlete, plan, athlete.local_today, True)
            if u.id == w.pk]
    assert up.adjusted_by == "user"
    assert auto_adjust._eligible_now(w, athlete.local_today, True) is False


def test_weekly_adaptation_skips_edited(athlete):
    from apps.planning.adaptation import adapt_week

    today = athlete.local_today
    monday = today - dt.timedelta(days=today.weekday())
    make_workout(athlete, monday - dt.timedelta(days=3))           # planned last week, not run
    keep = make_workout(athlete, today)
    shrink = make_workout(athlete, today)
    PlannedWorkout.objects.filter(pk=keep.pk).update(edited_by="user")
    adjustment = adapt_week(athlete, today)
    assert adjustment is not None and adjustment.factor < 1
    keep.refresh_from_db()
    shrink.refresh_from_db()
    assert keep.steps == run_walk_steps() and shrink.duration_s < keep.duration_s


def test_weather_swap_never_moves_an_edited_session(api, athlete, monkeypatch):
    from tests.test_r14_api import ALL_DAYS, bad_run_day, forecast
    from apps.athletes.models import Athlete
    from apps.ingest import weather

    Athlete.objects.filter(pk=athlete.pk).update(
        location_lat=17.39, location_lon=78.49, location_name="Hyderabad",
        location_source="city", location_city="Hyderabad", available_days=ALL_DAYS)
    athlete.refresh_from_db()
    day = bad_run_day(athlete)
    monkeypatch.setattr(weather, "_get_json", lambda url, params: (
        forecast(athlete, {day})[1] if "air-quality" in url else forecast(athlete, {day})[0]))
    w = make_workout(athlete, day, kind="EASY")
    PlannedWorkout.objects.filter(pk=w.pk).update(edited_by="user")
    assert api.post("/api/plan/weather-suggestions/check/").json()["created"] == 0
    PlannedWorkout.objects.filter(pk=w.pk).update(edited_by="")
    assert api.post("/api/plan/weather-suggestions/check/").json()["created"] == 1
    [s] = api.get("/api/plan/weather-suggestions/").json()["suggestions"]
    PlannedWorkout.objects.filter(pk=w.pk).update(edited_by="user")      # edited meanwhile
    assert api.post(f"/api/plan/weather-suggestions/{s['id']}/apply/").status_code == 409


def test_relayout_keeps_a_week_with_an_edited_session(athlete, proposed_plan):
    from apps.planning.plan_store import accept_plan
    from apps.planning.relayout import relayout_active_plan

    plan = accept_plan(proposed_plan)
    today = athlete.local_today
    future = list(plan.workouts.filter(date__gt=today + dt.timedelta(days=14),
                                       kind__in=["EASY", "RUN_WALK", "LONG"])
                  .order_by("date"))
    target = future[0]
    week = [w.pk for w in plan.workouts.filter(
        date__gte=target.date - dt.timedelta(days=6), date__lte=target.date + dt.timedelta(days=6))]
    PlannedWorkout.objects.filter(pk=target.pk).update(edited_by="user", notes="mine")
    before = (target.date, target.steps)
    athlete.runs_per_week = 2
    athlete.save()
    relayout_active_plan(athlete)
    target.refresh_from_db()
    assert (target.date, target.steps) == before and target.notes == "mine"
    assert PlannedWorkout.objects.filter(pk__in=week).exists()
