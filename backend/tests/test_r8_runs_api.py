"""R8 §A through the API: runs_per_week on the profile re-lays the active plan's future
weeks — same weekly volume, adaptation kept, today / past / race untouched, the watch
follows."""

import datetime as dt
from collections import defaultdict

import pytest

from apps.planning.adaptation import rescale, run_seconds
from apps.planning.models import PlanAdjustment, PlannedWorkout
from apps.planning.plan_store import accept_plan, propose_plan
from tests.test_r7_garmin_send import FakeGarmin, fake  # noqa: F401 — fixture

ALL_DAYS = {str(d): True for d in range(7)}
RUNS = ("RUN_WALK", "EASY", "LONG", "INTERVALS", "TEMPO")


@pytest.fixture
def plan(athlete):
    athlete.available_days = ALL_DAYS
    athlete.save()
    race_day = athlete.local_today + dt.timedelta(weeks=10)
    return accept_plan(propose_plan(athlete, race_name="Test 10K", race_date=race_day,
                                    distance_km=10))


def start_of(plan):
    return plan.phases.order_by("start").first().start


def weekly_run_s(plan):
    start, out = start_of(plan), defaultdict(int)
    for w in plan.workouts.filter(kind__in=RUNS):
        out[(w.date - start).days // 7] += run_seconds(w)
    return out


def future_weeks(plan, athlete):
    start, today = start_of(plan), athlete.local_today
    race = plan.workouts.get(kind="RACE").date
    race_week = (race - start).days // 7
    return [i for i in range(race_week) if start + dt.timedelta(days=7 * i) > today]


def patch(api, **data):
    return api.patch("/api/athlete/", data, format="json")


def test_profile_reports_recommended_and_effective(api, athlete, plan):
    body = api.get("/api/athlete/").json()
    assert body["runs_per_week"] is None
    assert body["runs_per_week_recommended"] == 4            # beginner baseline
    assert body["runs_per_week_effective"] == 4
    body = patch(api, runs_per_week=6).json()
    assert body["runs_per_week"] == 6 and body["runs_per_week_effective"] == 6
    days = {str(d): d in (1, 3, 5) for d in range(7)}
    body = patch(api, available_days=days, long_run_day=5).json()
    assert body["runs_per_week_effective"] == 3              # capped by available days


@pytest.mark.parametrize("bad", [1, 7, "x"])
def test_runs_per_week_validation(api, athlete, bad):
    assert patch(api, runs_per_week=bad).status_code == 400


def test_more_runs_regenerates_future_weeks_with_same_volume(api, athlete, plan):
    today = athlete.local_today
    before_volume = weekly_run_s(plan)
    fixed = {w.pk: (w.date, w.title, w.steps) for w in plan.workouts.filter(date__lte=today)}
    race = plan.workouts.get(kind="RACE")
    r = patch(api, runs_per_week=6)
    assert r.status_code == 200, r.json()
    reflow = r.json()["plan_reflow"]
    assert reflow["regenerated"] > 0 and isinstance(reflow["notes"], list)
    after_volume = weekly_run_s(plan)
    weeks = future_weeks(plan, athlete)
    assert weeks
    start = start_of(plan)
    for i in weeks:
        assert after_volume[i] == pytest.approx(before_volume[i], abs=240), i
        runs = plan.workouts.filter(kind__in=RUNS, date__gte=start + dt.timedelta(days=7 * i),
                                    date__lt=start + dt.timedelta(days=7 * i + 7))
        assert runs.count() <= 6
        assert len({w.date for w in runs}) == runs.count()
        assert all(w.duration_s >= 15 * 60 for w in runs)
    for pk, (date, title, steps) in fixed.items():
        w = PlannedWorkout.objects.get(pk=pk)
        assert (w.date, w.title, w.steps) == (date, title, steps)
    race.refresh_from_db()
    assert race.kind == "RACE" and race.date == plan.race.date
    assert plan.__class__.objects.get(pk=plan.pk).summary["reflows"][-1]["reason"] == \
        "runs per week changed"


def test_fewer_runs_never_adds_volume_and_back_to_auto(api, athlete, plan):
    before = weekly_run_s(plan)
    body = patch(api, runs_per_week=3).json()["plan_reflow"]
    assert body["regenerated"] > 0
    after = weekly_run_s(plan)
    for i in future_weeks(plan, athlete):
        assert after[i] <= before[i] + 240
    assert patch(api, runs_per_week=3).json()["plan_reflow"] is None      # idempotent
    assert patch(api, runs_per_week=None).json()["plan_reflow"]["regenerated"] > 0


def test_adapted_week_keeps_its_scaled_volume(api, athlete, plan):
    start = start_of(plan)
    i = future_weeks(plan, athlete)[0]
    week = plan.workouts.filter(kind__in=RUNS, date__gte=start + dt.timedelta(days=7 * i),
                                date__lt=start + dt.timedelta(days=7 * i + 7))
    for w in week:
        rescale(w, 0.8, athlete)
    PlanAdjustment.objects.create(athlete=athlete, plan=plan, week_start=week[0].date,
                                  reason="test", factor=0.8, planned_run_s=1, actual_run_s=0)
    scaled = weekly_run_s(plan)[i]
    patch(api, runs_per_week=6)
    assert weekly_run_s(plan)[i] == pytest.approx(scaled, abs=240)


def test_days_change_with_explicit_choice_relays(api, athlete, plan):
    patch(api, runs_per_week=5)
    days = {str(d): d in (0, 2, 4, 6) for d in range(7)}
    body = patch(api, available_days=days, long_run_day=6).json()["plan_reflow"]
    assert body is not None
    for w in plan.workouts.filter(kind__in=RUNS, date__gt=athlete.local_today):
        assert days[str(w.date.weekday())], w


def test_changed_synced_workouts_are_resent(api, athlete, plan, fake,
                                            django_capture_on_commit_callbacks):
    start = start_of(plan)
    i = future_weeks(plan, athlete)[0]
    # A non-long session: its length changes when the week is split six ways. (The long
    # run keeps its share of the week, so it is unchanged and stays on the watch as is.)
    target = plan.workouts.filter(kind__in=["EASY", "RUN_WALK"],
                                  date__gte=start + dt.timedelta(days=7 * i)).first()
    long_run = plan.workouts.filter(kind="LONG", date__gte=start + dt.timedelta(days=7 * i)).first()
    assert api.post(f"/api/workouts/{long_run.pk}/garmin/").status_code == 200
    long_run.refresh_from_db()
    assert api.post(f"/api/workouts/{target.pk}/garmin/").status_code == 200
    target.refresh_from_db()
    old_id = target.garmin_workout_id
    fake.calls.clear()
    with django_capture_on_commit_callbacks(execute=True):
        body = patch(api, runs_per_week=6).json()["plan_reflow"]
    assert body["watch_updated"] + body["watch_removed"] >= 1
    assert ("delete", old_id) in fake.calls
    target.refresh_from_db()
    assert target.garmin_workout_id != old_id
    assert ("schedule", target.garmin_workout_id, target.date.isoformat()) in fake.calls
    unchanged = PlannedWorkout.objects.get(pk=long_run.pk)
    assert unchanged.garmin_workout_id == long_run.garmin_workout_id      # not re-sent


def test_new_plan_uses_the_choice(api, athlete):
    athlete.available_days = ALL_DAYS
    athlete.runs_per_week = 6
    athlete.save()
    p = propose_plan(athlete, race_name="R", distance_km=10,
                     race_date=athlete.local_today + dt.timedelta(weeks=10))
    assert p.summary["runs_per_week"] == 6 and "notes" in p.summary
    start = p.phases.order_by("start").first().start
    counts = defaultdict(int)
    for w in p.workouts.filter(kind__in=RUNS):
        counts[(w.date - start).days // 7] += 1
    assert max(counts.values()) > 4


# --- Regression: re-layout must keep each row's identity (and its watch copy) --------
#
# A greedy single-pass pairing let an earlier run/walk session take the long run's row
# when the week had more run/walks than run/walk rows. The long run (unchanged) then got
# a NEW row without a Garmin id, and the old long run's watch copy was replaced by a
# 17 min run/walk on a different day. Whether it happened depended on the weekday the
# plan started on (it starts "tomorrow"), so the clock is pinned explicitly here.

def _pin_clock(monkeypatch, instant):
    from django.utils import timezone as dj_tz

    monkeypatch.setattr(dj_tz, "now", lambda: instant)


def _watch_from(calls):
    """What the watch holds after the fake client's calls: {garmin id: date}."""
    watch = {}
    for call in calls:
        if call[0] == "schedule":
            watch[call[1]] = call[2]
        elif call[0] == "delete":
            watch.pop(call[1], None)
        elif call[0] == "unschedule":
            watch.pop(call[1] - 50000, None)
    return watch


# Sunday 23:50 UTC is Monday 05:20 in Kolkata (the reported failure), plus one instant
# per weekday so the plan starts on every day of the week.
PINNED = [dt.datetime(2026, 10, 11, 23, 50, tzinfo=dt.timezone.utc)] + [
    dt.datetime(2026, 10, 5 + d, 6, 0, tzinfo=dt.timezone.utc) for d in range(7)]


@pytest.mark.parametrize("instant", PINNED, ids=lambda t: t.strftime("%a-%H%M"))
def test_relayout_keeps_long_run_row_and_watch_in_step(api, athlete, fake, monkeypatch,
                                                       django_capture_on_commit_callbacks,
                                                       instant):
    _pin_clock(monkeypatch, instant)
    athlete.timezone = "Asia/Kolkata"
    athlete.available_days = ALL_DAYS
    athlete.save()
    today = athlete.local_today
    plan = accept_plan(propose_plan(athlete, race_name="Test 10K", distance_km=10,
                                    race_date=today + dt.timedelta(weeks=10)))
    start = start_of(plan)
    i = future_weeks(plan, athlete)[0]
    week = plan.workouts.filter(kind__in=RUNS, date__gte=start + dt.timedelta(days=7 * i),
                                date__lt=start + dt.timedelta(days=7 * i + 7))
    long_run = week.get(kind="LONG")
    for w in week:                                           # the whole week on the watch
        assert api.post(f"/api/workouts/{w.pk}/garmin/").status_code == 200
    long_run.refresh_from_db()
    fixed = {w.pk: (w.date, w.title, w.steps) for w in plan.workouts.filter(date__lte=today)}
    calls_before = list(fake.calls)

    with django_capture_on_commit_callbacks(execute=True):
        assert patch(api, runs_per_week=6).status_code == 200

    after = PlannedWorkout.objects.get(pk=long_run.pk)
    assert after.kind == "LONG"                              # the row stays the long run
    if (after.date, after.steps) == (long_run.date, long_run.steps):
        assert after.garmin_workout_id == long_run.garmin_workout_id   # not re-sent
    # Every workout on the watch matches exactly one current row, on its date.
    watch = _watch_from(calls_before + fake.calls)
    rows = {w.garmin_workout_id: w.date.isoformat()
            for w in plan.workouts.filter(garmin_workout_id__isnull=False)}
    assert watch == rows
    for pk, (date, title, steps) in fixed.items():           # today and past untouched
        w = PlannedWorkout.objects.get(pk=pk)
        assert (w.date, w.title, w.steps) == (date, title, steps)


def test_pair_matches_kind_across_the_week_first():
    from types import SimpleNamespace as NS

    from apps.planning.relayout import _pair

    d = dt.date(2026, 10, 13)                                # a Tuesday plan week
    rows = [NS(pk=1, kind="RUN_WALK", date=d + dt.timedelta(days=1)),
            NS(pk=2, kind="RUN_WALK", date=d + dt.timedelta(days=3)),
            NS(pk=3, kind="LONG", date=d + dt.timedelta(days=5)),
            NS(pk=4, kind="RUN_WALK", date=d + dt.timedelta(days=6))]
    sessions = [NS(kind="RUN_WALK", date=d + dt.timedelta(days=k)) for k in (0, 1, 2, 3)] + [
        NS(kind="LONG", date=d + dt.timedelta(days=5)),
        NS(kind="RUN_WALK", date=d + dt.timedelta(days=6))]
    pairs, spare = _pair(sessions, rows)
    got = {(s.kind, s.date): (r.pk if r else None) for s, r in pairs}
    assert got[("LONG", d + dt.timedelta(days=5))] == 3
    assert got[("RUN_WALK", d + dt.timedelta(days=1))] == 1      # same day kept
    assert got[("RUN_WALK", d + dt.timedelta(days=3))] == 2
    assert got[("RUN_WALK", d + dt.timedelta(days=6))] == 4
    assert sorted(r.pk for _, r in pairs if r) == [1, 2, 3, 4] and spare == []
