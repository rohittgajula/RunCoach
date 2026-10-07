"""Garmin watch: a heart-rate target on every step, and one RunCoach copy per day.

1. Walk / warm-up / cool-down steps carry a gentle HR band, so the watch shows the
   target screen for the whole workout, not only the run blocks.
2. Sending (or re-sending) a workout replaces its old Garmin copy and removes any other
   RunCoach-created copy left on that date — identified by the GarminUpload registry,
   never by name, so the athlete's own Garmin Connect workouts are never touched.

Always against a fake client; never the real API.
"""

import datetime as dt
import importlib

import pytest

from apps.planning.models import GarminUpload, PlannedWorkout, StrengthSession
from planning.garmin_workout import (build_payload, gentle_band, payload_hash,
                                     step_band)
from tests.r7_helpers import make_workout, run_walk_steps, tomorrow
from tests.test_r7_garmin_send import FakeGarmin

HR_KEY = "heart.rate.zone"
ATHLETE_HR = {"resting_hr": 58, "hr_easy_min": 130, "hr_easy_max": 145, "hr_ceiling": 155}


def step(kind, seconds, intensity, hr=None, label=""):
    return {"kind": kind, "duration_s": seconds, "intensity": intensity, "label": label,
            "pace_min_s": None, "pace_max_s": None,
            "hr_min": hr[0] if hr else None, "hr_max": hr[1] if hr else None}


def executables(payload):
    out = []
    for s in payload["workoutSegments"][0]["workoutSteps"]:
        out += s["workoutSteps"] if s["type"] == "RepeatGroupDTO" else [s]
    return out


def bands_by_label(payload):
    return {s["description"]: (s["targetValueOne"], s["targetValueTwo"])
            for s in executables(payload)}


# --- 1. targets on every step (pure) -------------------------------------------------

def test_run_walk_every_step_has_an_hr_target_and_runs_are_unchanged():
    steps = [step("warmup", 300, "walk", label="Walk warm-up")]
    for i in range(3):
        steps += [step("run", 240, "easy", (130, 145), f"Run {i}"),
                  step("walk", 120, "walk", label=f"Walk {i}")]
    steps.append(step("cooldown", 120, "walk", label="Walk cool-down"))
    payload = build_payload({"title": "rw", "steps": steps, "hr": ATHLETE_HR})
    for s in executables(payload):
        assert s["targetType"]["workoutTargetTypeKey"] == HR_KEY, s
    bands = bands_by_label(payload)
    assert bands["Run 0"] == (130.0, 145.0)           # run band unchanged
    # resting 58 + 20 = 78 < 90 -> floor 90; top = hr_easy_max 145
    for label in ("Walk warm-up", "Walk 0", "Walk cool-down"):
        assert bands[label] == (90.0, 145.0)


def test_gentle_band_rules():
    # resting + 20 when that is above the 90 floor
    assert gentle_band({**ATHLETE_HR, "resting_hr": 75}, []) == (95, 145)
    # no resting HR -> 90
    assert gentle_band({**ATHLETE_HR, "resting_hr": None}, []) == (90, 145)
    # hr_easy_max missing -> the ceiling
    assert gentle_band({"hr_ceiling": 150}, []) == (90, 150)
    # never higher than the lowest run band in the workout (e.g. a Z2 top below easy max)
    runs = [step("run", 600, "easy", (120, 138)), step("run", 300, "moderate", (145, 155))]
    assert gentle_band(ATHLETE_HR, runs) == (90, 138)
    # no room: keep at least 10 bpm and never above the top
    assert gentle_band({"resting_hr": 85, "hr_easy_max": 100}, []) == (90, 100)
    assert gentle_band({"resting_hr": 85, "hr_easy_max": 105}, []) == (95, 105)
    assert gentle_band({"resting_hr": 90, "hr_easy_max": 100}, []) == (90, 100)
    assert gentle_band({"resting_hr": 95, "hr_easy_max": 100}, []) == (90, 100)
    # nothing to derive from
    assert gentle_band(None, [step("walk", 60, "walk")]) is None


@pytest.mark.parametrize("hr", [
    ATHLETE_HR,
    {"resting_hr": 72, "hr_easy_min": 125, "hr_easy_max": 140, "hr_ceiling": 150},
    {"resting_hr": None, "hr_easy_min": 118, "hr_easy_max": 128, "hr_ceiling": 140},
])
@pytest.mark.parametrize("zones", [True, False])
@pytest.mark.parametrize("kind,run_min,walk_min,phase", [
    ("RUN_WALK", 16, 8, "BASE"), ("EASY", 30, 6, "PEAK"), ("LONG", 60, 8, "BUILD"),
    ("TEMPO", 30, 8, "BUILD"), ("INTERVALS", 24, 10, "SPECIFIC"), ("WALK", 0, 30, "BASE"),
    ("RACE", 40, 5, "RACE"),
])
def test_every_generated_workout_has_a_target_on_every_step(kind, run_min, walk_min, phase,
                                                             zones, hr):
    from planning.generator import Session
    from planning.workouts import Bands, build_workout

    hard = (160, 172) if zones else None
    bands = Bands(easy_pace=(600, 645), moderate_pace=(540, 560), hard_pace=(480, 500),
                  hr_easy=(hr["hr_easy_min"], hr["hr_easy_max"]),
                  hr_moderate=(hr["hr_easy_max"], hr["hr_ceiling"]), hr_hard=hard)
    session = Session(date=dt.date(2026, 10, 10), kind=kind, run_minutes=run_min,
                      walk_minutes=walk_min, target_run_m=5000, purpose="p", effort="easy")
    spec = build_workout(session, bands, phase, race_km=5.0, race_pace_s_per_km=420)
    steps = [s.as_dict() for s in spec.steps]
    payload = build_payload({"title": spec.title, "steps": steps, "hr": hr})
    gentle = gentle_band(hr, steps)
    run_tops = [s["hr_max"] for s in steps if s["intensity"] != "walk" and s["hr_max"]]
    for s, out in zip([s for s in steps if s["duration_s"] > 0], _flat_in_order(payload, steps)):
        assert out["targetType"]["workoutTargetTypeKey"] == HR_KEY, (kind, s)
        low, high = out["targetValueOne"], out["targetValueTwo"]
        assert low < high
        if s["intensity"] == "walk":
            assert (low, high) == tuple(float(v) for v in gentle)
            assert low >= 90 or high - low == 10
            assert high <= hr["hr_easy_max"]
            assert all(high <= top for top in run_tops)       # never above a run band
        elif s["hr_min"] and s["hr_max"]:
            assert (low, high) == (s["hr_min"], s["hr_max"])   # banded steps unchanged
        else:
            assert high <= hr["hr_ceiling"]                    # unbanded: capped


def _flat_in_order(payload, steps):
    """Executable steps expanded back to the original step order (repeats unrolled)."""
    out = []
    for s in payload["workoutSegments"][0]["workoutSteps"]:
        if s["type"] == "RepeatGroupDTO":
            out += s["workoutSteps"] * s["numberOfIterations"]
        else:
            out.append(s)
    assert len(out) == len([s for s in steps if s["duration_s"] > 0])
    return out


def test_unbanded_non_walk_steps_fall_back_to_athlete_ranges():
    assert step_band(step("stride", 30, "hard"), (90, 145), ATHLETE_HR) == (145, 155)
    assert step_band(step("run", 600, "easy"), (90, 145), ATHLETE_HR) == (130, 145)
    assert step_band(step("run", 600, "moderate"), (90, 145), None) is None
    # a walk step that carries its own (harder) band still gets the gentle band
    assert step_band(step("walk", 60, "walk", (140, 160)), (90, 145), ATHLETE_HR) == (90, 145)


def test_strength_payload_stays_without_a_target():
    from planning.garmin_strength import build_payload as strength_payload
    from planning.strength import exercises

    payload = strength_payload({"title": "S", "duration_s": 1200, "exercises": exercises(3)})
    seen = 0
    for s in payload["workoutSegments"][0]["workoutSteps"]:
        for x in [s] + s.get("workoutSteps", []):
            if "targetType" in x:
                seen += 1
                assert x["targetType"]["workoutTargetTypeKey"] == "no.target"
                assert "targetValueOne" not in x
    assert seen


# --- 2. one RunCoach copy per day ------------------------------------------------------

class Calendar(FakeGarmin):
    """FakeGarmin plus strength uploads and a record of what is on the calendar."""

    def __init__(self):
        super().__init__()
        self.on_calendar = {}           # garmin id -> date (includes the athlete's own)

    def upload_strength_workout(self, workout):
        self.next_id += 1
        self.calls.append(("upload_strength", workout.to_dict()))
        return {"workoutId": self.next_id}

    def schedule_workout(self, workout_id, date_str):
        self.on_calendar[workout_id] = date_str
        return super().schedule_workout(workout_id, date_str)

    def delete_workout(self, workout_id):
        self.on_calendar.pop(workout_id, None)
        super().delete_workout(workout_id)

    def deleted(self):
        return [c[1] for c in self.calls if c[0] == "delete"]


@pytest.fixture
def cal(monkeypatch, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    client = Calendar()
    tripped = []
    monkeypatch.setattr("apps.planning.garmin_push._client", lambda athlete: client)
    monkeypatch.setattr("apps.planning.garmin_strength_push._client", lambda athlete: client)
    monkeypatch.setattr("apps.ingest.tasks.garmin_blocked", lambda: False)
    monkeypatch.setattr("apps.ingest.tasks.trip_breaker", lambda reason: tripped.append(reason))
    client.tripped = tripped
    return client


def send(api, workout):
    r = api.post(f"/api/workouts/{workout.pk}/garmin/")
    assert r.status_code == 200, r.json()
    return r.json()


def registered(athlete):
    return sorted(GarminUpload.objects.filter(athlete=athlete)
                  .values_list("garmin_workout_id", "date"))


def test_send_registers_the_upload_and_walk_steps_carry_targets(api, athlete, cal):
    workout = make_workout(athlete, tomorrow(athlete))
    send(api, workout)
    assert registered(athlete) == [(1001, workout.date)]
    upload = GarminUpload.objects.get(athlete=athlete)
    assert upload.workout_id == workout.pk and upload.garmin_schedule_id == 51001
    uploaded = cal.calls[0][1]
    steps = executables(uploaded)
    assert all(s["targetType"]["workoutTargetTypeKey"] == HR_KEY for s in steps)
    walk = next(s for s in steps if s["description"].startswith("Walk"))
    assert (walk["targetValueOne"], walk["targetValueTwo"]) == (90.0, float(athlete.hr_easy_max))


def test_resending_a_changed_workout_replaces_the_old_copy(api, athlete, cal):
    workout = make_workout(athlete, tomorrow(athlete))
    send(api, workout)
    PlannedWorkout.objects.filter(pk=workout.pk).update(title="Changed")
    body = send(api, workout)
    assert body["garmin_result"]["status"] == "updated"
    assert cal.deleted() == [1001] and ("unschedule", 51001) in cal.calls
    assert registered(athlete) == [(1002, workout.date)]
    assert list(cal.on_calendar) == [1002]


def test_send_removes_stale_app_copies_on_the_same_day(api, athlete, cal):
    day = tomorrow(athlete, 2)
    # Left behind: a RunCoach upload whose row is gone, on the same day and on another.
    GarminUpload.objects.create(athlete=athlete, garmin_workout_id=555, garmin_schedule_id=655,
                                date=day)
    GarminUpload.objects.create(athlete=athlete, garmin_workout_id=556, date=day + dt.timedelta(1))
    workout = make_workout(athlete, day)
    send(api, workout)
    assert ("unschedule", 655) in cal.calls and 555 in cal.deleted()
    assert 556 not in cal.deleted()                         # other days are not this send's
    assert registered(athlete) == [(556, day + dt.timedelta(1)), (1001, day)]


def test_unchanged_send_still_cleans_the_day(api, athlete, cal):
    workout = make_workout(athlete, tomorrow(athlete))
    send(api, workout)
    GarminUpload.objects.create(athlete=athlete, garmin_workout_id=700, date=workout.date)
    body = send(api, workout)
    assert body["garmin_result"]["status"] == "unchanged"
    assert cal.deleted() == [700]
    assert registered(athlete) == [(1001, workout.date)]


def test_workouts_the_athlete_made_are_never_touched(api, athlete, other_athlete, cal):
    day = tomorrow(athlete)
    cal.on_calendar[9001] = day.isoformat()                 # made in Garmin Connect
    # Another athlete's RunCoach upload, same day, same ids space: not ours to clean.
    GarminUpload.objects.create(athlete=other_athlete, garmin_workout_id=9002, date=day)
    workout = make_workout(athlete, day)
    send(api, workout)
    PlannedWorkout.objects.filter(pk=workout.pk).update(title="Again")
    send(api, workout)
    api.delete(f"/api/workouts/{workout.pk}/garmin/")
    assert 9001 not in cal.deleted() and 9002 not in cal.deleted()
    assert 9001 in cal.on_calendar
    assert GarminUpload.objects.filter(athlete=other_athlete).count() == 1


def test_other_current_rows_on_the_same_day_are_kept(api, athlete, cal):
    """A run and a strength session (or two runs) on one day: both are current rows."""
    from apps.planning import garmin_strength_push
    from planning.strength import exercises

    day = tomorrow(athlete)
    first = make_workout(athlete, day)
    second = make_workout(athlete, day, steps=run_walk_steps(blocks=2))
    session = StrengthSession.objects.create(athlete=athlete, date=day, title="S", level=1,
                                             exercises=exercises(1))
    send(api, first)
    send(api, second)
    assert garmin_strength_push.run_job(athlete.pk, [session.pk], "send")["ok"]
    PlannedWorkout.objects.filter(pk=first.pk).update(title="Changed")
    send(api, first)
    assert cal.deleted() == [1001]                           # only first's own old copy
    assert sorted(cal.on_calendar) == [1002, 1003, 1004]
    assert GarminUpload.objects.get(garmin_workout_id=1003).source == "strength"


def test_moving_a_workout_removes_it_from_the_old_date(api, athlete, cal):
    old_day, new_day = tomorrow(athlete), tomorrow(athlete, 3)
    workout = make_workout(athlete, old_day)
    send(api, workout)
    # Another leftover on the old day goes too: the old day is swept as well.
    GarminUpload.objects.create(athlete=athlete, garmin_workout_id=800, date=old_day)
    api.patch(f"/api/workouts/{workout.pk}/", {"date": new_day.isoformat()}, format="json")
    body = send(api, workout)
    assert body["garmin_result"]["status"] == "updated"
    assert set(cal.deleted()) == {1001, 800}
    assert cal.on_calendar == {1002: new_day.isoformat()}
    assert registered(athlete) == [(1002, new_day)]


def test_moving_via_patch_queues_the_resync_that_cleans_the_old_date(
        api, athlete, cal, django_capture_on_commit_callbacks):
    old_day, new_day = tomorrow(athlete), tomorrow(athlete, 2)
    workout = make_workout(athlete, old_day)
    send(api, workout)
    with django_capture_on_commit_callbacks(execute=True):
        r = api.patch(f"/api/workouts/{workout.pk}/", {"date": new_day.isoformat()},
                      format="json")
    assert r.status_code == 200
    assert cal.deleted() == [1001]
    assert cal.on_calendar == {1002: new_day.isoformat()}
    assert registered(athlete) == [(1002, new_day)]


def test_a_deleted_row_whose_forget_failed_is_cleaned_by_the_next_send(api, athlete, cal):
    """Plan rebuild / re-layout while the breaker was open: the row is gone, its copy
    stayed. The next send on that day removes it."""
    day = tomorrow(athlete)
    old = make_workout(athlete, day)
    send(api, old)
    PlannedWorkout.objects.filter(pk=old.pk).delete()        # forget never ran
    assert GarminUpload.objects.get(garmin_workout_id=1001).workout_id is None
    new = make_workout(athlete, day)
    send(api, new)
    assert cal.deleted() == [1001]
    assert registered(athlete) == [(1002, day)]


def test_reused_row_overwriting_its_id_leaves_no_orphan(api, athlete, cal):
    """A row whose Garmin id was overwritten (row reuse) no longer holds the old id."""
    day = tomorrow(athlete)
    workout = make_workout(athlete, day)
    send(api, workout)
    PlannedWorkout.objects.filter(pk=workout.pk).update(garmin_workout_id=None,
                                                        garmin_payload_hash="")
    send(api, workout)
    assert cal.deleted() == [1001]
    assert cal.on_calendar == {1002: day.isoformat()}


def test_rest_day_send_still_cleans_the_day(api, athlete, cal):
    day = tomorrow(athlete)
    GarminUpload.objects.create(athlete=athlete, garmin_workout_id=901, date=day)
    rest = make_workout(athlete, day, kind="REST", steps=[])
    r = api.post(f"/api/workouts/{rest.pk}/garmin/")
    assert r.status_code == 409
    assert cal.deleted() == [901] and not registered(athlete)


def test_week_send_cleans_each_day_once_and_is_idempotent(api, athlete, cal):
    days = [tomorrow(athlete, d) for d in (1, 2)]
    for i, d in enumerate(days):
        GarminUpload.objects.create(athlete=athlete, garmin_workout_id=300 + i, date=d)
        make_workout(athlete, d)
    r = api.post("/api/plans/active/garmin/", {"days": 7}, format="json")
    assert r.status_code == 200
    assert sorted(cal.deleted()) == [300, 301]
    calls = len(cal.calls)
    again = api.post("/api/plans/active/garmin/", {"days": 7}, format="json").json()
    assert {x["status"] for x in again["results"]} == {"unchanged"}
    assert len(cal.calls) == calls                          # nothing more on Garmin


def test_rate_limit_while_cleaning_trips_the_breaker_and_keeps_the_registry(
        api, athlete, cal):
    day = tomorrow(athlete)
    GarminUpload.objects.create(athlete=athlete, garmin_workout_id=400, date=day)

    def limited(workout_id):
        raise Exception("429 Too Many Requests")

    cal.delete_workout = limited
    workout = make_workout(athlete, day)
    r = api.post(f"/api/workouts/{workout.pk}/garmin/")
    assert r.status_code == 502 and cal.tripped
    assert registered(athlete) == [(400, day)]               # retried on the next send
    assert cal.uploads == 0


def test_other_errors_while_cleaning_do_not_block_the_send(api, athlete, cal):
    day = tomorrow(athlete)
    GarminUpload.objects.create(athlete=athlete, garmin_workout_id=401, date=day)
    real_delete = cal.delete_workout

    def flaky(workout_id):
        if workout_id == 401:
            raise Exception("500 Server Error")
        real_delete(workout_id)

    cal.delete_workout = flaky
    workout = make_workout(athlete, day)
    assert send(api, workout)["garmin_result"]["status"] == "uploaded"
    assert registered(athlete) == [(401, day), (1001, day)]


def test_already_gone_copies_are_dropped_from_the_registry(api, athlete, cal):
    day = tomorrow(athlete)
    GarminUpload.objects.create(athlete=athlete, garmin_workout_id=402, date=day)

    def gone(workout_id):
        raise Exception("404 Not Found")

    cal.delete_workout = gone
    send(api, make_workout(athlete, day))
    assert registered(athlete) == [(1001, day)]


def test_schedule_failure_leaves_nothing_registered(api, athlete, cal):
    def broken(workout_id, date_str):
        raise Exception("500 Server Error")

    cal.schedule_workout = broken
    workout = make_workout(athlete, tomorrow(athlete))
    assert api.post(f"/api/workouts/{workout.pk}/garmin/").status_code == 502
    assert cal.deleted() == [1001] and not registered(athlete)


def test_remove_and_forget_drop_registry_rows(api, athlete, cal):
    from apps.planning.garmin_push import forget_remote

    a = make_workout(athlete, tomorrow(athlete))
    b = make_workout(athlete, tomorrow(athlete, 2))
    send(api, a)
    send(api, b)
    api.delete(f"/api/workouts/{a.pk}/garmin/")
    assert registered(athlete) == [(1002, b.date)]
    refs = [[b.garmin_workout_id or 1002, 51002]]
    PlannedWorkout.objects.filter(pk=b.pk).delete()
    assert forget_remote(athlete.pk, refs)["removed"] == [1002]
    assert not registered(athlete)


def test_strength_resend_replaces_and_cleans(athlete, cal):
    from apps.planning import garmin_strength_push
    from planning.strength import exercises

    day = tomorrow(athlete)
    GarminUpload.objects.create(athlete=athlete, garmin_workout_id=600, date=day,
                                source="strength")
    session = StrengthSession.objects.create(athlete=athlete, date=day, title="S", level=1,
                                             exercises=exercises(1))
    assert garmin_strength_push.run_job(athlete.pk, [session.pk], "send")["ok"]
    StrengthSession.objects.filter(pk=session.pk).update(title="S2")
    result = garmin_strength_push.run_job(athlete.pk, [session.pk], "send")
    assert result["results"][0]["status"] == "updated"
    assert cal.deleted() == [600, 1001]
    assert registered(athlete) == [(1002, day)]


# --- deploy: already-synced workouts --------------------------------------------------

def test_workouts_synced_before_the_change_show_changed_and_resync_once(
        athlete, cal, django_capture_on_commit_callbacks):
    """The walk targets change the payload, so a copy sent by the old code hashes
    differently: it shows "changed" (Update on watch) and is re-sent once, then is
    "synced" again."""
    from apps.planning.garmin_sync import resync_on_garmin
    from apps.planning.presenters import _garmin_source, garmin_status

    athlete.resting_hr = 75                                   # walk band 95–145
    athlete.save()
    workout = make_workout(athlete, tomorrow(athlete))
    new_payload = build_payload(_garmin_source(workout))
    old_payload = build_payload(_garmin_source(workout))
    for s in executables(old_payload):                        # what the old code sent
        if s["description"].startswith("Walk"):
            for key in ("targetValueOne", "targetValueTwo"):
                s.pop(key)
            s["targetType"] = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target",
                               "displayOrder": 1}
    assert old_payload != new_payload
    PlannedWorkout.objects.filter(pk=workout.pk).update(
        garmin_workout_id=42, garmin_schedule_id=43,
        garmin_payload_hash=payload_hash(old_payload, workout.date.isoformat()))
    GarminUpload.objects.create(athlete=athlete, garmin_workout_id=42, garmin_schedule_id=43,
                                date=workout.date)
    workout.refresh_from_db()
    assert garmin_status(workout) == "changed"
    with django_capture_on_commit_callbacks(execute=True):
        assert resync_on_garmin(athlete, [workout.pk]) == 1
    workout.refresh_from_db()
    assert garmin_status(workout) == "synced" and workout.garmin_workout_id == 1001
    assert cal.deleted() == [42] and registered(athlete) == [(1001, workout.date)]
    with django_capture_on_commit_callbacks(execute=True):
        assert resync_on_garmin(athlete, [workout.pk]) == 0      # once only


def test_profile_hr_change_marks_synced_workouts_changed(api, athlete, cal):
    workout = make_workout(athlete, tomorrow(athlete))
    send(api, workout)
    assert api.get(f"/api/workouts/{workout.pk}/").json()["garmin_status"] == "synced"
    athlete.resting_hr = 80
    athlete.save()
    assert api.get(f"/api/workouts/{workout.pk}/").json()["garmin_status"] == "changed"


def test_migration_backfills_the_registry_from_current_rows(athlete):
    from django.apps import apps as django_apps

    migration = importlib.import_module("apps.planning.migrations.0007_garmin_upload_registry")
    workout = make_workout(athlete, tomorrow(athlete))
    PlannedWorkout.objects.filter(pk=workout.pk).update(garmin_workout_id=71,
                                                        garmin_schedule_id=72)
    session = StrengthSession.objects.create(athlete=athlete, date=tomorrow(athlete, 2),
                                             title="S", garmin_workout_id=73)
    make_workout(athlete, tomorrow(athlete, 3))                      # never sent
    migration.backfill(django_apps, None)
    migration.backfill(django_apps, None)                            # idempotent
    rows = {u.garmin_workout_id: u for u in GarminUpload.objects.filter(athlete=athlete)}
    assert set(rows) == {71, 73}
    assert rows[71].workout_id == workout.pk and rows[71].garmin_schedule_id == 72
    assert rows[73].strength_id == session.pk and rows[73].source == "strength"
