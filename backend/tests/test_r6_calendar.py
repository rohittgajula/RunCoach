"""R6 §2 unplanned runs, §3 actual vs planned, §4 the month calendar."""

import datetime as dt

import pytest

from apps.planning.models import PlannedWorkout
from apps.planning.plan_store import accept_plan
from tests.r6_helpers import make_activity

ACTUAL_KEYS = {"activity_id", "duration_s", "distance_m", "run_distance_m", "walk_distance_m",
               "run_fraction", "longest_run_s", "avg_hr", "max_hr", "avg_cadence_spm",
               "avg_pace_s_per_km", "time_in_zone", "steps"}
REVIEW_KEYS = {"status", "summary_md", "went_well", "to_improve"}


@pytest.fixture
def active(athlete, proposed_plan):
    return accept_plan(proposed_plan)


def free_day(athlete, active, after=None):
    """A date inside the plan with no workout."""
    days = set(active.workouts.values_list("date", flat=True))
    day = after or athlete.local_today + dt.timedelta(days=1)
    while day in days:
        day += dt.timedelta(days=1)
    return day


def first_workout(active):
    return active.workouts.exclude(kind="RACE").order_by("date").first()


def test_unplanned_run_shows_and_counts(api, athlete, active):
    day = free_day(athlete, active)
    PlannedWorkout.objects.filter(athlete=athlete, date=day).delete()
    run = make_activity(athlete, day, minutes=40, load=70)
    body = api.get("/api/calendar/", {"start": str(day), "end": str(day)}).json()
    item = body["days"][0]["items"][0]
    assert item["type"] == "activity" and item["unplanned"] is True
    assert item["activity"]["unplanned"] is True and item["activity"]["id"] == run.pk
    week = body["weeks"][0]
    assert week["actual_s"] == 2400 and week["actual_load"] == 70


def test_linked_run_is_not_extra_and_carries_actual(api, athlete, active):
    workout = first_workout(active)
    run = make_activity(athlete, workout.date, blocks=[{"duration_s": 600, "hr_avg": 140,
                                                      "hr_max": 150}])
    workout.refresh_from_db()
    assert workout.completed_activity_id == run.pk            # auto-linked by the signal
    body = api.get(f"/api/workouts/{workout.pk}/").json()
    assert set(body["actual"]) >= ACTUAL_KEYS
    assert body["actual"]["activity_id"] == run.pk
    assert 0 <= body["compliance"]["score"] <= 100
    assert {c["key"] for c in body["compliance"]["checks"]} >= {"duration", "run_time"}
    for check in body["compliance"]["checks"]:
        assert set(check) == {"key", "label", "status", "planned", "actual", "note"}
        assert check["status"] in ("hit", "close", "missed")
    assert set(body["review"]) >= REVIEW_KEYS and body["review"]["status"] == "none"
    detail = api.get(f"/api/activities/{run.pk}/").json()
    assert detail["unplanned"] is False and detail["workout_id"] == workout.pk


def test_planned_workout_without_activity_has_null_blocks(api, active):
    workout = first_workout(active)
    body = api.get(f"/api/workouts/{workout.pk}/").json()
    assert body["actual"] is None and body["compliance"] is None and body["review"] is None


def test_unplanned_activity_detail_has_actual_and_review(api, athlete, active):
    day = free_day(athlete, active)
    run = make_activity(athlete, day)
    body = api.get(f"/api/activities/{run.pk}/").json()
    assert body["unplanned"] is True and set(body["actual"]) >= ACTUAL_KEYS
    assert body["review"]["status"] == "none" and body["compliance"] is None
    assert "segments" in body and "name" in body       # old detail + ActivityCard keys


def _mock_ai(monkeypatch):
    from apps.coaching import services
    from apps.coaching.schemas import InsightsSummary, WorkoutReview

    def fake_complete(*, operation, schema, **kwargs):
        stats = {"model": "test-model", "input_tokens": 1, "output_tokens": 1,
                 "latency_ms": 1, "retry_count": 0, "estimated_cost_usd": 0.0}
        if schema is WorkoutReview:
            return WorkoutReview(summary_md="Good easy run.", went_well=["Even pacing"],
                                 to_improve=["Walk sooner on hills"]), stats
        return InsightsSummary(markdown="You are running well."), stats

    monkeypatch.setattr(services, "complete", fake_complete)
    monkeypatch.setattr(services, "model_for", lambda op: "test-model")


def test_workout_review_is_generated_and_cached(api, athlete, active, monkeypatch):
    from apps.coaching.models import AIRequestLog

    _mock_ai(monkeypatch)
    workout = first_workout(active)
    make_activity(athlete, workout.date)
    r = api.post(f"/api/workouts/{workout.pk}/review/")
    assert r.status_code == 200
    assert r.json()["review"]["status"] == "ready"
    assert r.json()["review"]["went_well"] == ["Even pacing"]
    api.post(f"/api/workouts/{workout.pk}/review/")
    assert AIRequestLog.objects.filter(athlete=athlete, operation="workout_review").count() == 1
    assert api.get(f"/api/workouts/{workout.pk}/").json()["review"]["status"] == "ready"


def test_review_needs_a_linked_activity(api, active):
    workout = first_workout(active)
    assert api.post(f"/api/workouts/{workout.pk}/review/").status_code == 409


def test_review_503_when_ai_unavailable(api, athlete, active, monkeypatch):
    from apps.coaching import services
    from apps.coaching.client import AIUnavailable

    def boom(**kwargs):
        raise AIUnavailable("No OPENAI_API_KEY configured.")

    monkeypatch.setattr(services, "complete", boom)
    monkeypatch.setattr(services, "model_for", lambda op: "test-model")
    run = make_activity(athlete, free_day(athlete, active))
    r = api.post(f"/api/activities/{run.pk}/ai-review/")
    assert r.status_code == 503 and "detail" in r.json()


# --- month calendar ----------------------------------------------------------

def test_month_shape_and_statuses(api, athlete, active):
    today = athlete.local_today
    workouts = list(active.workouts.order_by("date"))
    # Pretend two workouts were in the past: one done (good), one missed.
    done, missed = workouts[0], workouts[1]
    for w, back in ((done, 3), (missed, 2)):
        PlannedWorkout.objects.filter(pk=w.pk).update(date=today - dt.timedelta(days=back))
    done.refresh_from_db()
    missed.refresh_from_db()
    run = make_activity(athlete, done.date, minutes=round(done.duration_s / 60),
                        run_s=sum(s["duration_s"] for s in done.steps if s["intensity"] != "walk"))
    PlannedWorkout.objects.filter(pk=done.pk).update(status="completed", completed_activity=run)
    extra_day = today - dt.timedelta(days=5)
    PlannedWorkout.objects.filter(athlete=athlete, date=extra_day).delete()
    make_activity(athlete, extra_day)

    month = today.strftime("%Y-%m")
    body = api.get("/api/calendar/month/", {"month": month}).json()
    assert set(body) == {"month", "today", "days", "totals"}
    assert body["month"] == month
    assert set(body["totals"]) >= {"planned_s", "actual_s", "runs_done", "runs_planned",
                                   "runs_missed"}
    by_date = {d["date"]: d for d in body["days"]}
    for day in body["days"]:
        assert set(day) == {"date", "planned", "status", "activities"}
        assert day["status"] in (None, "done", "missed", "partial", "planned", "rest",
                                 "extra", "today")
        if day["planned"]:
            assert set(day["planned"]) == {"kind", "title", "duration_s"}
        for activity in day["activities"]:
            assert set(activity) == {"id", "sport", "duration_s", "distance_m"}

    def status_on(day):
        return by_date[str(day)]["status"] if str(day) in by_date else None

    if done.date.month == today.month:
        assert status_on(done.date) in ("done", "partial")
    if missed.date.month == today.month:
        assert status_on(missed.date) == "missed"
    if extra_day.month == today.month:
        assert status_on(extra_day) == "extra"


def test_month_future_planned_and_partial(api, athlete, active):
    workout = first_workout(active)
    month = workout.date.strftime("%Y-%m")
    body = api.get("/api/calendar/month/", {"month": month}).json()
    day = next(d for d in body["days"] if d["date"] == str(workout.date))
    assert day["status"] in ("planned", "today")

    # A linked run that missed most of the prescription is "partial".
    PlannedWorkout.objects.filter(pk=workout.pk).update(
        date=athlete.local_today - dt.timedelta(days=1))
    run = make_activity(athlete, athlete.local_today - dt.timedelta(days=1), minutes=3,
                        run_s=60, walk_s=60)
    PlannedWorkout.objects.filter(pk=workout.pk).update(status="completed",
                                                        completed_activity=run)
    month = (athlete.local_today - dt.timedelta(days=1)).strftime("%Y-%m")
    body = api.get("/api/calendar/month/", {"month": month}).json()
    day = next(d for d in body["days"]
               if d["date"] == str(athlete.local_today - dt.timedelta(days=1)))
    assert day["status"] == "partial"


def test_month_bad_param(api):
    assert api.get("/api/calendar/month/", {"month": "2026-13"}).status_code == 400


# --- tenant isolation of every new endpoint --------------------------------------

def test_new_endpoints_are_tenant_isolated(api, other_api, athlete, active, monkeypatch):
    _mock_ai(monkeypatch)
    workout = first_workout(active)
    run = make_activity(athlete, workout.date)
    month = workout.date.strftime("%Y-%m")
    assert other_api.get(f"/api/workouts/{workout.pk}/").status_code == 404
    assert other_api.post(f"/api/workouts/{workout.pk}/review/").status_code == 404
    assert other_api.get(f"/api/activities/{run.pk}/").status_code == 404
    assert other_api.post(f"/api/activities/{run.pk}/ai-review/").status_code == 404
    theirs = other_api.get("/api/calendar/month/", {"month": month}).json()
    assert all(d["planned"] is None and not d["activities"] for d in theirs["days"])
    assert theirs["totals"]["runs_planned"] == 0
    insights = other_api.get("/api/insights/").json()
    assert insights["running"]["runs"] == 0
    other_api.post("/api/insights/summary/")
    from apps.coaching.models import AIAnalysis

    assert not AIAnalysis.objects.filter(athlete=athlete).exists()
