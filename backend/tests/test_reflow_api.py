"""Changing training days re-flows the active plan (PATCH /api/athlete/), and every
change to a workout that is on the watch replaces the watch copy."""

import datetime as dt

import pytest

from apps.planning.models import PlannedWorkout
from apps.planning.plan_store import accept_plan, propose_plan
from tests.r7_helpers import make_workout, tomorrow, wellness
from tests.test_r7_garmin_send import FakeGarmin, fake  # noqa: F401 — fixture

# Default profile days are Tue/Thu/Sat/Sun with the long run on Sunday.
NEW_DAYS = {"0": True, "1": False, "2": True, "3": False, "4": True, "5": False, "6": True}
UNCHANGED = ("title", "kind", "duration_s", "load", "steps", "description", "status")


def next_monday(athlete):
    today = athlete.local_today
    return today + dt.timedelta(days=7 - today.weekday())


def movers(athlete, plan):
    """Future workouts after this week on a day that is no longer available."""
    return [w for w in plan.workouts.filter(date__gte=next_monday(athlete)).exclude(kind="RACE")
            if not NEW_DAYS[str(w.date.weekday())]]


def snapshot(plan):
    return {w.pk: {f: getattr(w, f) for f in ("date", *UNCHANGED)} for w in plan.workouts.all()}


@pytest.fixture
def plan(athlete):
    race_day = athlete.local_today + dt.timedelta(weeks=10)
    return accept_plan(propose_plan(athlete, race_name="Test 10K", race_date=race_day,
                                    distance_km=10))


def patch_days(api, days=NEW_DAYS, long_day=6):
    return api.patch("/api/athlete/", {"available_days": days, "long_run_day": long_day},
                     format="json")


# --- the re-flow through the API ------------------------------------------------

def test_patching_days_moves_future_workouts_and_reports_it(api, athlete, plan):
    today = athlete.local_today
    before = snapshot(plan)
    r = patch_days(api)
    assert r.status_code == 200, r.json()
    reflow = r.json()["plan_reflow"]
    assert reflow["moved"] > 0
    assert reflow["watch_updated"] == 0 and reflow["watch_removed"] == 0

    after = snapshot(plan)
    assert set(after) <= set(before)                         # nothing added
    gone = set(before) - set(after)
    # Same number of days: only this week (fewer future days left) can lose a session.
    assert len(gone) == reflow["dropped"]
    assert all(today < before[pk]["date"] < next_monday(athlete)
               and before[pk]["kind"] in ("EASY", "RUN_WALK") for pk in gone)
    for pk, row in after.items():
        assert all(row[f] == before[pk][f] for f in UNCHANGED)   # only dates change
        if before[pk]["date"] <= today:
            assert row["date"] == before[pk]["date"]
    for w in plan.workouts.filter(date__gt=today).exclude(kind="RACE"):
        assert NEW_DAYS[str(w.date.weekday())], w
        if w.kind == "LONG":
            assert w.date.weekday() == 6
        if w.date != before[w.pk]["date"]:
            assert w.moved_from == before[w.pk]["date"]
            assert w.phase is None or w.phase.start <= w.date <= w.phase.end
    race = plan.workouts.get(kind="RACE")
    assert race.date == before[race.pk]["date"]
    assert plan.__class__.objects.get(pk=plan.pk).summary["reflows"][-1]["reason"] == \
        "training days changed"


def test_patching_the_same_days_again_is_a_noop(api, athlete, plan):
    patch_days(api)
    before = snapshot(plan)
    r = patch_days(api)
    assert r.json()["plan_reflow"] is None
    assert snapshot(plan) == before


def test_unrelated_profile_edit_has_null_plan_reflow(api, athlete, plan):
    before = snapshot(plan)
    r = api.patch("/api/athlete/", {"weight_kg": 70}, format="json")
    assert r.status_code == 200 and r.json()["plan_reflow"] is None
    assert snapshot(plan) == before


def test_no_active_plan_gives_null(api, athlete):
    r = patch_days(api)
    assert r.status_code == 200 and r.json()["plan_reflow"] is None


def test_fewer_days_drops_easy_sessions_only(api, athlete, plan):
    two = {str(d): d in (2, 6) for d in range(7)}
    before = snapshot(plan)
    r = patch_days(api, two)
    assert r.json()["plan_reflow"]["dropped"] > 0
    gone = set(before) - set(snapshot(plan))
    assert gone and all(before[pk]["kind"] in ("EASY", "RUN_WALK") for pk in gone)
    assert plan.workouts.filter(kind="LONG", date__gt=athlete.local_today).count() == \
        sum(1 for row in before.values() if row["kind"] == "LONG"
            and row["date"] > athlete.local_today)


def test_invalid_days_change_nothing(api, athlete, plan):
    before = snapshot(plan)
    r = patch_days(api, NEW_DAYS, long_day=1)                # long day not available
    assert r.status_code == 400
    assert snapshot(plan) == before


def test_tenant_isolation(api, athlete, plan, other_athlete):
    theirs = accept_plan(propose_plan(other_athlete, race_name="X",
                                      race_date=other_athlete.local_today + dt.timedelta(weeks=9),
                                      distance_km=10))
    before = snapshot(theirs)
    patch_days(api)
    assert snapshot(theirs) == before


# --- the watch follows --------------------------------------------------------

def send(api, workout):
    r = api.post(f"/api/workouts/{workout.pk}/garmin/")
    assert r.status_code == 200, r.json()
    workout.refresh_from_db()
    return workout


def test_moved_synced_workout_is_replaced_on_the_watch(api, athlete, plan, fake,
                                                       django_capture_on_commit_callbacks):
    today = athlete.local_today
    moving = movers(athlete, plan)[:2]
    staying = plan.workouts.filter(date__gt=today, kind="LONG").first()
    synced = [send(api, w) for w in [*moving, staying]]
    old = {w.pk: (w.garmin_workout_id, w.garmin_schedule_id) for w in synced}
    fake.calls.clear()

    with django_capture_on_commit_callbacks(execute=True):
        r = patch_days(api)
    assert r.json()["plan_reflow"]["watch_updated"] == len(moving)
    for w in moving:
        w.refresh_from_db()
        gid, sid = old[w.pk]
        assert ("unschedule", sid) in fake.calls and ("delete", gid) in fake.calls
        assert ("schedule", w.garmin_workout_id, w.date.isoformat()) in fake.calls
        assert fake.calls.index(("delete", gid)) < fake.calls.index(
            ("schedule", w.garmin_workout_id, w.date.isoformat()))
        assert api.get(f"/api/workouts/{w.pk}/").json()["garmin_status"] == "synced"
    staying.refresh_from_db()
    assert staying.garmin_workout_id == old[staying.pk][0]       # not touched


def test_dropped_synced_workout_is_removed_from_the_watch(api, athlete, plan, fake,
                                                          django_capture_on_commit_callbacks):
    today = athlete.local_today
    easy = [send(api, w) for w in plan.workouts.filter(date__gt=today,
                                                       kind__in=["EASY", "RUN_WALK"])[:6]]
    refs = {w.pk: (w.garmin_workout_id, w.garmin_schedule_id) for w in easy}
    fake.calls.clear()
    with django_capture_on_commit_callbacks(execute=True):
        body = patch_days(api, {str(d): d in (2, 6) for d in range(7)}).json()["plan_reflow"]
    dropped = [pk for pk in refs if not PlannedWorkout.objects.filter(pk=pk).exists()]
    assert dropped and body["watch_removed"] == len(dropped)
    for pk in dropped:
        assert ("delete", refs[pk][0]) in fake.calls and ("unschedule", refs[pk][1]) in fake.calls


def test_unsynced_workouts_are_never_uploaded(api, athlete, plan, fake,
                                              django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        r = patch_days(api)
    assert r.json()["plan_reflow"]["moved"] > 0
    assert fake.calls == []


def test_breaker_open_makes_no_calls_and_leaves_status_changed(
        api, athlete, plan, fake, monkeypatch, django_capture_on_commit_callbacks):
    moving = movers(athlete, plan)[0]
    send(api, moving)
    fake.calls.clear()
    monkeypatch.setattr("apps.ingest.tasks.garmin_blocked", lambda: True)
    with django_capture_on_commit_callbacks(execute=True):
        r = patch_days(api)
    assert r.status_code == 200 and r.json()["plan_reflow"]["watch_updated"] == 1
    assert fake.calls == []
    body = api.get(f"/api/workouts/{moving.pk}/").json()
    assert body["garmin_status"] == "changed" and body["date"] != str(moving.date)


def test_queue_failure_does_not_break_the_save(api, athlete, plan, fake, monkeypatch,
                                                django_capture_on_commit_callbacks):
    from apps.planning import tasks

    moving = movers(athlete, plan)[0]
    send(api, moving)

    def broken(*args):
        raise ConnectionError("broker down")
    monkeypatch.setattr(tasks.garmin_push_task, "delay", broken)
    with django_capture_on_commit_callbacks(execute=True):
        r = patch_days(api)
    assert r.status_code == 200
    assert api.get(f"/api/workouts/{moving.pk}/").json()["garmin_status"] == "changed"


# --- other edits of a synced workout -------------------------------------------

def test_workout_patch_date_resends_and_skip_removes(api, athlete, fake,
                                                     django_capture_on_commit_callbacks):
    workout = send(api, make_workout(athlete, tomorrow(athlete)))
    first = (workout.garmin_workout_id, workout.garmin_schedule_id)
    fake.calls.clear()
    new_day = tomorrow(athlete, 3).isoformat()
    with django_capture_on_commit_callbacks(execute=True):
        api.patch(f"/api/workouts/{workout.pk}/", {"date": new_day}, format="json")
    assert fake.kinds() == ["unschedule", "delete", "upload", "schedule"]
    assert fake.calls[1] == ("delete", first[0]) and fake.calls[-1][2] == new_day

    fake.calls.clear()
    with django_capture_on_commit_callbacks(execute=True):
        r = api.patch(f"/api/workouts/{workout.pk}/", {"status": "skipped"}, format="json")
    assert fake.kinds() == ["unschedule", "delete"]
    assert r.status_code == 200
    workout.refresh_from_db()
    assert workout.garmin_workout_id is None and workout.status == "skipped"


def test_workout_patch_of_unsynced_workout_makes_no_calls(api, athlete, fake,
                                                          django_capture_on_commit_callbacks):
    workout = make_workout(athlete, tomorrow(athlete))
    with django_capture_on_commit_callbacks(execute=True):
        api.patch(f"/api/workouts/{workout.pk}/", {"date": tomorrow(athlete, 2).isoformat()},
                  format="json")
        api.patch(f"/api/workouts/{workout.pk}/", {"status": "skipped"}, format="json")
    assert fake.calls == []


def test_chat_move_skip_and_clear_day_follow_on_the_watch(athlete, fake,
                                                          django_capture_on_commit_callbacks):
    from apps.coaching.tools import ToolRunner

    tools = ToolRunner(athlete)
    from apps.planning.garmin_push import run_job

    a = make_workout(athlete, tomorrow(athlete))
    b = make_workout(athlete, tomorrow(athlete, 2))
    c = make_workout(athlete, tomorrow(athlete, 4))
    run_job(athlete.pk, [a.pk, b.pk, c.pk], "send")
    ids = {w.pk: PlannedWorkout.objects.get(pk=w.pk).garmin_workout_id for w in (a, b, c)}
    fake.calls.clear()

    with django_capture_on_commit_callbacks(execute=True):
        tools("move_workout", {"id": a.pk, "new_date": tomorrow(athlete, 5).isoformat()})
    assert ("delete", ids[a.pk]) in fake.calls
    assert fake.calls[-1][0] == "schedule" and fake.calls[-1][2] == tomorrow(athlete, 5).isoformat()

    fake.calls.clear()
    with django_capture_on_commit_callbacks(execute=True):
        tools("skip_workout", {"id": b.pk, "reason": "tired"})
    assert fake.kinds() == ["unschedule", "delete"] and fake.calls[1] == ("delete", ids[b.pk])

    fake.calls.clear()
    with django_capture_on_commit_callbacks(execute=True):
        tools("clear_day", {"date": c.date.isoformat(), "reason": "travel"})
    assert fake.kinds() == ["unschedule", "delete"] and fake.calls[1] == ("delete", ids[c.pk])
    assert PlannedWorkout.objects.get(pk=c.pk).garmin_workout_id is None


def test_today_apply_replaces_the_watch_copy(api, athlete, fake,
                                             django_capture_on_commit_callbacks):
    workout = make_workout(athlete)                      # today
    send(api, workout)
    gid = PlannedWorkout.objects.get(pk=workout.pk).garmin_workout_id
    fake.calls.clear()
    wellness(athlete, sleep_seconds=5 * 3600)
    with django_capture_on_commit_callbacks(execute=True):
        r = api.post("/api/today/apply/")
    assert r.status_code == 200
    assert fake.kinds() == ["unschedule", "delete", "upload", "schedule"]
    assert fake.calls[1] == ("delete", gid)
    assert api.get(f"/api/workouts/{workout.pk}/").json()["garmin_status"] == "synced"
