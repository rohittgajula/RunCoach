"""R13 §1 auto-adjust, §2 race-day plan, §4 strength sessions — services and API,
including tenant isolation."""

import datetime as dt

import pytest

from apps.planning import auto_adjust
from apps.planning.models import PlannedWorkout, Race, StrengthSession, WorkoutAdjustment
from planning import strength
from tests.r10_helpers import run
from tests.r7_helpers import active_plan, make_workout, wellness


def easy_steps(run_s=1800):
    return [{"kind": "run", "duration_s": run_s, "intensity": "easy", "label": "Easy run",
             "pace_min_s": 600, "pace_max_s": 645, "hr_min": 130, "hr_max": 145}]


def day(athlete, offset):
    return athlete.local_today + dt.timedelta(days=offset)


def done_run(athlete, offset=-1, hr=140, kind="EASY", run_s=1600):
    """A run `offset` days from today that completed a planned workout of `kind`."""
    activity = run(athlete, day(athlete, offset), hr=hr)
    workout = make_workout(athlete, day(athlete, offset), kind=kind, steps=easy_steps(run_s),
                           status="completed")
    workout.completed_activity = activity
    workout.save()
    return activity


@pytest.fixture
def future(athlete):
    """Tomorrow's and the day after's easy sessions."""
    return [make_workout(athlete, day(athlete, 1), kind="EASY", steps=easy_steps()),
            make_workout(athlete, day(athlete, 2), kind="EASY", steps=easy_steps())]


# --- §1 -----------------------------------------------------------------------------

def test_high_hr_shortens_next_session_and_records_it(athlete, future):
    activity = done_run(athlete, hr=153)          # Z2 cap 145 -> 8 bpm high
    created = auto_adjust.evaluate(athlete, trigger="run", activity=activity)
    assert len(created) == 1
    adj = created[0]
    workout = PlannedWorkout.objects.get(pk=future[0].pk)
    assert workout.adjusted_by == "auto" and adj.action == "shorten"
    assert auto_adjust._run_s(workout.steps) < 1800
    assert sum(s["duration_s"] for s in workout.steps) == workout.duration_s
    assert adj.chip.startswith("Adjusted: shortened to ")
    assert "your HR ran 8 bpm high yesterday" in adj.chip
    assert adj.before["duration_s"] == 1800 and adj.after["duration_s"] == workout.duration_s
    # The second session is untouched for a mild signal; evaluating again changes nothing.
    assert PlannedWorkout.objects.get(pk=future[1].pk).adjusted_by == ""
    assert auto_adjust.evaluate(athlete, trigger="checkin", activity=activity) == []


def test_setting_off_changes_nothing(athlete, future):
    athlete.auto_adjust_plan = False
    athlete.save()
    activity = done_run(athlete, hr=170)
    assert auto_adjust.evaluate(athlete, trigger="run", activity=activity) == []
    assert not WorkoutAdjustment.objects.exists()


def test_old_runs_never_trigger(athlete, future):
    activity = done_run(athlete, offset=-5, hr=170)
    assert auto_adjust.evaluate(athlete, trigger="run", activity=activity) == []


def test_protected_sessions_untouched(athlete):
    race = make_workout(athlete, day(athlete, 1), kind="RACE", steps=easy_steps())
    moved = make_workout(athlete, day(athlete, 2), kind="EASY", steps=easy_steps())
    moved.moved_from = day(athlete, 3)
    moved.save()
    checkin = make_workout(athlete, day(athlete, 3), kind="EASY", steps=easy_steps())
    checkin.adjusted_by = "checkin"
    checkin.save()
    skipped = make_workout(athlete, day(athlete, 1), kind="EASY", steps=easy_steps(),
                           status="skipped")
    activity = done_run(athlete, hr=175)
    assert auto_adjust.evaluate(athlete, trigger="run", activity=activity) == []
    for w in (race, moved, checkin, skipped):
        w.refresh_from_db()
        assert w.adjusted_by in ("", "checkin") and w.duration_s == 1800


def test_strain_converts_hard_session_and_reaches_two_sessions(athlete):
    hard = make_workout(athlete, day(athlete, 1), kind="INTERVALS", steps=easy_steps())
    easy = make_workout(athlete, day(athlete, 2), kind="EASY", steps=easy_steps())
    activity = done_run(athlete, hr=175)          # 30 bpm high -> weight 2 -> moderate
    created = auto_adjust.evaluate(athlete, trigger="run", activity=activity)
    assert [a.action for a in created] == ["easier", "shorten"]
    hard.refresh_from_db()
    easy.refresh_from_db()
    assert hard.kind == "EASY" and hard.target_zone == "Z2"
    assert auto_adjust._run_s(easy.steps) < 1800


def test_pain_report_rests_next_session(athlete, future):
    from apps.health.models import PainReport

    for offset, severity in ((0, 3), (-1, 2)):
        PainReport.objects.create(athlete=athlete, date=day(athlete, offset), location="knee",
                                  side="left", severity=severity)
    created = auto_adjust.evaluate(athlete, trigger="pain")
    assert created and created[0].action == "rest"
    workout = PlannedWorkout.objects.get(pk=future[0].pk)
    assert workout.kind == "REST" and workout.steps == [] and workout.duration_s == 0
    assert "physio" in workout.description
    assert "knee" in created[0].chip.lower()


def test_extend_only_within_week_room_and_eased_first(athlete):
    # Three easy-and-good runs, and an earlier auto-shortened session freed room.
    target = make_workout(athlete, day(athlete, 1), kind="EASY", steps=easy_steps(2400))
    for offset in (-5, -3, -1):
        last = done_run(athlete, offset=offset, hr=135)
    room_before = auto_adjust.week_room(active_plan(athlete), day(athlete, 1))
    assert room_before == 0
    assert auto_adjust.evaluate(athlete, trigger="run", activity=last) == []

    # Give the week 3 minutes of room (an earlier shortened session in the same week).
    other = make_workout(athlete, day(athlete, 2), kind="EASY", steps=easy_steps(1800))
    WorkoutAdjustment.objects.create(
        athlete=athlete, plan=other.plan, workout=other, trigger="run", action="shorten",
        reason="r", chip="c", before={**auto_adjust.snapshot(other), "steps": easy_steps(1980)},
        after=auto_adjust.snapshot(other))
    other.adjusted_by = "auto"
    other.save()
    if day(athlete, 1).isocalendar()[1] != day(athlete, 2).isocalendar()[1]:
        pytest.skip("tomorrow and the day after are in different weeks today")
    created = auto_adjust.evaluate(athlete, trigger="run", activity=last)
    assert [a.action for a in created] == ["extend"]
    target.refresh_from_db()
    assert auto_adjust._run_s(target.steps) == 2400 + 120      # 5 % of 40 min, whole minutes
    assert created[0].chip.startswith("Adjusted: extended to")
    # A later strain signal reverts the extension and eases the session instead.
    strained = done_run(athlete, offset=0, hr=170)
    eased = auto_adjust.evaluate(athlete, trigger="checkin", activity=strained)
    target.refresh_from_db()
    assert eased and auto_adjust._run_s(target.steps) < 2400
    assert WorkoutAdjustment.objects.get(pk=created[0].pk).status == "undone"


def test_api_list_undo_and_isolation(api, other_api, athlete, future):
    activity = done_run(athlete, hr=153)
    adj = auto_adjust.evaluate(athlete, trigger="run", activity=activity)[0]
    body = api.get("/api/adjustments/").json()
    assert body["enabled"] is True and len(body["adjustments"]) == 1
    row = body["adjustments"][0]
    assert set(row) == {"id", "workout_id", "workout_date", "workout_title", "activity_id",
                        "trigger", "action", "reason", "chip", "signals", "before", "after",
                        "group", "status", "undoable", "created_at", "undone_at"}
    assert row["undoable"] is True and row["signals"][0]["key"] == "hr_high"
    # The workout JSON carries the chip.
    workout = api.get(f"/api/workouts/{future[0].pk}/").json()
    assert workout["auto_adjustment"]["id"] == adj.pk and workout["adjusted_by"] == "auto"
    # Another athlete can neither see nor undo it.
    assert other_api.get("/api/adjustments/").json()["adjustments"] == []
    assert other_api.post(f"/api/adjustments/{adj.pk}/undo/").status_code == 404
    r = api.post(f"/api/adjustments/{adj.pk}/undo/")
    assert r.status_code == 200 and r.json()["status"] == "undone"
    w = PlannedWorkout.objects.get(pk=future[0].pk)
    assert w.duration_s == 1800 and w.adjusted_by == "kept" and w.steps == easy_steps()
    assert api.post(f"/api/adjustments/{adj.pk}/undo/").status_code == 409
    # Kept sessions are never auto-adjusted again.
    assert auto_adjust.evaluate(athlete, trigger="checkin", activity=activity) == [] or \
        all(a.workout_id != w.pk for a in WorkoutAdjustment.objects.filter(status="applied"))
    assert api.get("/api/adjustments/?limit=0").status_code == 400


def test_undo_refused_after_the_athlete_changed_it(api, athlete, future):
    activity = done_run(athlete, hr=153)
    adj = auto_adjust.evaluate(athlete, trigger="run", activity=activity)[0]
    api.patch(f"/api/workouts/{future[0].pk}/", {"date": day(athlete, 3).isoformat()},
              format="json")
    assert api.post(f"/api/adjustments/{adj.pk}/undo/").status_code == 409


def test_watch_copy_resent_after_adjust(athlete, future, monkeypatch,
                                        django_capture_on_commit_callbacks):
    from apps.planning import tasks

    sent = []
    monkeypatch.setattr(tasks.garmin_push_task, "delay", lambda *a: sent.append(a))
    future[0].garmin_workout_id = 555
    future[0].garmin_payload_hash = "old"
    future[0].save()
    activity = done_run(athlete, hr=153)
    with django_capture_on_commit_callbacks(execute=True):
        auto_adjust.evaluate(athlete, trigger="run", activity=activity)
    assert sent == [(athlete.pk, [future[0].pk], "send")]


def test_after_run_task_builds_review_and_adjusts(athlete, future):
    from apps.activities.models import RunReview
    from apps.planning.tasks import after_run_task

    activity = done_run(athlete, hr=153)
    result = after_run_task.run(activity.pk)
    assert result["adjusted"] == 1 and result["review"]
    assert RunReview.objects.filter(activity=activity).exists()


def test_checkin_queues_after_checkin(api, athlete, no_real_r13_queue,
                                      django_capture_on_commit_callbacks):
    activity = done_run(athlete)
    with django_capture_on_commit_callbacks(execute=True):
        r = api.post(f"/api/activities/{activity.pk}/checkin/", {"rpe": 9}, format="json")
    assert r.status_code == 201
    assert ("after_checkin_task", (activity.pk,), {}) in no_real_r13_queue


def test_morning_checkin_pain_signal(api, athlete):
    from apps.health.models import PainReport

    make_workout(athlete, athlete.local_today, kind="EASY", steps=easy_steps())
    for offset in (0, -1):
        PainReport.objects.create(athlete=athlete, date=day(athlete, offset), location="shin",
                                  side="right", severity=2)
    body = api.get("/api/today/").json()
    pain = [r for r in body["reasons"] if r["signal"] == "pain"]
    assert pain and pain[0]["status"] == "watch" and pain[0]["label"] == "Shin (right) sore 2 days"
    assert body["verdict"] == "easy"
    assert body["injury"]["risk"] == "moderate" and body["mood"] is None


# --- §2 -----------------------------------------------------------------------------

def test_race_plan_with_goal(api, other_api, athlete):
    race = Race.objects.create(athlete=athlete, name="City 10K", date=day(athlete, 30),
                               distance_km=10)
    r = api.patch(f"/api/races/{race.pk}/", {"goal_time_s": 3000, "start_time": "07:15"},
                  format="json")
    assert r.status_code == 200 and r.json()["start_time"] == "07:15"
    body = api.get(f"/api/races/{race.pk}/plan/?strategy=negative").json()
    assert body["available"] is True and body["target"]["source"] == "goal"
    assert body["start_time"] == "07:15" and body["start_time_source"] == "race"
    assert len(body["splits"]) == 10 and body["splits"][-1]["elapsed_s"] == 3000
    assert body["weather"] is None                  # > 7 days away
    assert {i["key"] for i in body["taper"]["items"]} == {"sleep", "carbs", "kit", "route",
                                                          "bib", "shoes"}
    assert body["morning"][-1] == {"time": "07:15", "label": "Start",
                                   "detail": "Run your plan, not the crowd."}
    assert body["fueling"]["carbs_g_per_h"] == 0
    assert api.get(f"/api/races/{race.pk}/plan/?strategy=fast").status_code == 400
    assert other_api.get(f"/api/races/{race.pk}/plan/").status_code == 404
    assert api.patch(f"/api/races/{race.pk}/", {"goal_time_s": 10}, format="json") \
        .status_code == 400


def test_race_plan_without_any_target(api, athlete):
    race = Race.objects.create(athlete=athlete, name="Half", date=day(athlete, 3),
                               distance_km=21.1)
    body = api.get(f"/api/races/{race.pk}/plan/").json()
    assert body["available"] is False and body["reason"] == "no_target"
    assert body["splits"] == [] and body["taper"]["in_taper"] is True
    assert body["weather"] is None                  # no location in tests


def test_race_plan_uses_garmin_prediction(api, athlete):
    wellness(athlete, race_pred_10k_s=3000, race_pred_5k_s=1440)
    race = Race.objects.create(athlete=athlete, name="5K", date=day(athlete, 20), distance_km=5)
    body = api.get(f"/api/races/{race.pk}/plan/").json()
    assert body["target"]["source"] == "garmin" and body["target"]["time_s"] == 1440


# --- §4 -----------------------------------------------------------------------------

@pytest.fixture
def plan_weeks(athlete):
    """Two weeks of a plan: easy runs Tue/Thu, long Sun."""
    plan = active_plan(athlete)
    start = athlete.local_today + dt.timedelta(days=1)
    for i in range(14):
        d = start + dt.timedelta(days=i)
        if d.weekday() in (1, 3):
            make_workout(athlete, d, kind="EASY", steps=easy_steps())
        elif d.weekday() == 6:
            make_workout(athlete, d, kind="LONG", steps=easy_steps(3600))
    return plan


def test_strength_choice_places_sessions(api, other_api, athlete, plan_weeks):
    r = api.patch("/api/athlete/", {"strength_per_week": 2}, format="json")
    assert r.status_code == 200, r.json()
    assert r.json()["strength_per_week"] == 2 and r.json()["strength_per_week_suggested"] == 2
    assert r.json()["strength_reflow"]["created"] >= 2
    athlete.refresh_from_db()       # request.user.athlete is this cached instance in tests
    sessions = list(StrengthSession.objects.filter(athlete=athlete))
    run_days = {w.date: w.kind for w in PlannedWorkout.objects.filter(athlete=athlete)}
    for s in sessions:
        assert run_days.get(s.date + dt.timedelta(days=1)) not in ("LONG", "INTERVALS", "TEMPO")
        assert s.date > athlete.local_today and s.duration_s == strength.DURATION_S
    body = api.get("/api/strength/").json()
    assert body["per_week"] == 2 and body["can_send_to_watch"] is False
    first = body["sessions"][0]
    assert first["exercises"][0]["key"] == "calf" and first["garmin_status"] == "none"
    # Calendar items.
    cal = api.get(f"/api/calendar/?start={first['date']}&end={first['date']}").json()
    assert any(i["type"] == "strength" for i in cal["days"][0]["items"])
    month = api.get(f"/api/calendar/month/?month={first['date'][:7]}").json()
    assert any(d["strength"] and d["strength"]["id"] == first["id"] for d in month["days"])
    # Isolation.
    assert other_api.get("/api/strength/").json()["sessions"] == []
    assert other_api.patch(f"/api/strength/{first['id']}/", {"status": "skipped"},
                           format="json").status_code == 404
    assert api.patch("/api/athlete/", {"strength_per_week": 4}, format="json").status_code == 400
    # Turning it off removes the future planned ones.
    r = api.patch("/api/athlete/", {"strength_per_week": 0}, format="json")
    assert r.json()["strength_reflow"]["removed"] == len(sessions)
    athlete.refresh_from_db()
    assert not StrengthSession.objects.filter(athlete=athlete).exists()


def test_strength_patch_and_watch_rules(api, athlete, plan_weeks):
    athlete.strength_per_week = 1
    athlete.save()
    from apps.planning.strength_service import place_for

    place_for(athlete)
    session = StrengthSession.objects.filter(athlete=athlete).first()
    r = api.patch(f"/api/strength/{session.pk}/", {"status": "completed"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "completed"
    assert api.patch(f"/api/strength/{session.pk}/", {"date": "2020-01-01"},
                     format="json").status_code == 400
    assert api.patch(f"/api/strength/{session.pk}/", {"title": "x"},
                     format="json").status_code == 400
    assert api.post(f"/api/strength/{session.pk}/garmin/").status_code == 409   # no Garmin
    athlete.garmin_connected = True
    athlete.save()
    assert api.post(f"/api/strength/{session.pk}/garmin/").status_code == 409   # completed
    api.patch(f"/api/strength/{session.pk}/", {"status": "planned"}, format="json")
    assert api.post(f"/api/strength/{session.pk}/garmin/").status_code == 202


def test_strength_auto_completed_by_garmin_activity(athlete, plan_weeks):
    from apps.planning.strength_service import complete_from_activity

    athlete.strength_per_week = 1
    athlete.save()
    from apps.planning.strength_service import place_for

    place_for(athlete)
    session = StrengthSession.objects.filter(athlete=athlete).first()
    activity = run(athlete, session.date)
    activity.sport = "strength_training"
    activity.save()
    assert complete_from_activity(activity) == session
    session.refresh_from_db()
    assert session.status == "completed" and session.auto_completed
    activity.sport = "running"
    assert complete_from_activity(activity) is None


def test_garmin_catalogue_pairs_exist_and_payload_validates():
    from garminconnect.exercises import EXERCISES
    from garminconnect.workout import StrengthWorkout

    from planning import strength
    from planning.garmin_strength import CATALOGUE, build_payload

    known = {(e["category"], e["exercise"]) for e in EXERCISES}
    assert set(CATALOGUE.values()) <= known, "every mapping must be a real Garmin exercise"
    # Every pattern, at every rung, has somewhere to go. A gap here is a session
    # that arrives on the watch missing a movement.
    assert set(CATALOGUE) == {
        (key, level)
        for key in strength.PATTERNS
        for level in range(1, strength.MAX_LEVEL + 1)
    }
    payload = build_payload({"title": "S", "duration_s": 1200, "exercises": strength.exercises(4)})
    workout = StrengthWorkout.model_validate(payload)
    assert workout.to_dict()["sportType"]["sportTypeKey"] == "strength_training"


class FakeStrengthGarmin:
    def __init__(self):
        self.calls = []

    def upload_strength_workout(self, workout):
        from garminconnect.workout import StrengthWorkout

        assert isinstance(workout, StrengthWorkout)
        self.calls.append("upload")
        return {"workoutId": 77}

    def schedule_workout(self, workout_id, date_str):
        self.calls.append(("schedule", workout_id, date_str))
        return {"workoutScheduleId": 88}

    def unschedule_workout(self, schedule_id):
        self.calls.append("unschedule")

    def delete_workout(self, workout_id):
        self.calls.append("delete")


def test_strength_push_job_uses_existing_client_and_breaker(athlete, monkeypatch):
    from apps.planning import garmin_strength_push

    session = StrengthSession.objects.create(athlete=athlete, date=day(athlete, 1), title="S",
                                             level=1, exercises=__import__(
                                                 "planning.strength").strength.exercises(1))
    fake = FakeStrengthGarmin()
    monkeypatch.setattr("apps.planning.garmin_strength_push._client", lambda a: fake)
    monkeypatch.setattr("apps.ingest.tasks.garmin_blocked", lambda: True)
    assert garmin_strength_push.run_job(athlete.pk, [session.pk], "send")["code"] == "rate_limited"
    assert fake.calls == []
    monkeypatch.setattr("apps.ingest.tasks.garmin_blocked", lambda: False)
    result = garmin_strength_push.run_job(athlete.pk, [session.pk], "send")
    assert result["ok"] and result["results"][0]["status"] == "uploaded"
    session.refresh_from_db()
    assert session.garmin_workout_id == 77 and session.garmin_schedule_id == 88
    again = garmin_strength_push.run_job(athlete.pk, [session.pk], "send")
    assert again["results"][0]["status"] == "unchanged"
    removed = garmin_strength_push.run_job(athlete.pk, [session.pk], "delete")
    assert removed["results"][0]["status"] == "removed"
    assert fake.calls[-2:] == ["unschedule", "delete"]
