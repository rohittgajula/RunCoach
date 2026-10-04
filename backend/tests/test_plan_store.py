"""Persisted plans: materialisation from the generator, accept, decline."""

import datetime as dt

import pytest

from apps.planning.models import PlannedWorkout, PlanPhase, Race, TrainingPlan
from apps.planning.plan_store import accept_plan, decline_plan, link_activity, propose_plan
from planning.generator import Baseline, Session, generate_plan
from planning.workouts import Bands, build_workout

BANDS = Bands(easy_pace=(600, 645), moderate_pace=(525, 555), hard_pace=(480, 510),
              hr_easy=(130, 145), hr_moderate=(145, 155), hr_hard=None)


def test_proposal_creates_phases_and_workouts(athlete, proposed_plan):
    plan = proposed_plan
    assert plan.status == TrainingPlan.Status.PROPOSED
    assert plan.race.name == "Test 10K"
    phases = list(plan.phases.order_by("order"))
    assert phases and phases[-1].kind == "race"
    workouts = list(plan.workouts.all())
    assert workouts
    start = athlete.local_today + dt.timedelta(days=1)
    race_day = plan.race.date
    assert all(start <= w.date <= race_day for w in workouts)
    assert [w.kind for w in workouts if w.date == race_day] == ["RACE"]
    assert all(w.fueling.get("before") for w in workouts)


def test_phases_merge_consecutive_generator_weeks(athlete, proposed_plan):
    phases = list(proposed_plan.phases.order_by("order"))
    labels = [p.generator_phase for p in phases]
    assert all(a != b for a, b in zip(labels, labels[1:])), "consecutive phases must differ"
    # And the merged phases cover the generator's weeks exactly.
    generated = generate_plan(
        athlete.local_today + dt.timedelta(days=1), proposed_plan.race.date, 10.0,
        Baseline(1.0, 0, 480, 700, athlete.available_days, athlete.long_run_day),
    )
    distinct = [w.phase for i, w in enumerate(generated.weeks)
                if i == 0 or w.phase != generated.weeks[i - 1].phase]
    assert labels == distinct
    for a, b in zip(phases, phases[1:]):
        assert b.start == a.end + dt.timedelta(days=1)


def test_model_phase_names_used_only_when_count_matches(athlete):
    day = athlete.local_today + dt.timedelta(weeks=10)
    plan = propose_plan(athlete, race_name="A", race_date=day, distance_km=10,
                        phase_names_and_descriptions=[{"name": "Only one", "description": "x"}])
    assert "Only one" not in [p.name for p in plan.phases.all()]
    count = plan.phases.count()
    names = [{"name": f"P{i}", "description": f"d{i}"} for i in range(count)]
    plan2 = propose_plan(athlete, race_name="A", race_date=day, distance_km=10,
                         phase_names_and_descriptions=names)
    assert [p.name for p in plan2.phases.order_by("order")] == [f"P{i}" for i in range(count)]


def test_step_durations_sum_to_workout_duration(proposed_plan):
    for workout in proposed_plan.workouts.all():
        assert sum(s["duration_s"] for s in workout.steps) == workout.duration_s, workout.title
        assert all(s["duration_s"] > 0 for s in workout.steps)
        assert {s["intensity"] for s in workout.steps} <= {"walk", "easy", "moderate", "hard"}


@pytest.mark.parametrize("kind,phase", [
    ("EASY", "AEROBIC"), ("EASY", "PEAK"), ("RUN_WALK", "FOUNDATION"), ("LONG", "SPECIFIC"),
    ("INTERVALS", "AEROBIC"), ("TEMPO", "PEAK"),
])
@pytest.mark.parametrize("run_min,walk_min", [(12.0, 9.0), (35.0, 11.0), (64.3, 4.1), (25.0, 0.0)])
def test_builder_preserves_generator_minutes(kind, phase, run_min, walk_min):
    session = Session(date=dt.date(2026, 1, 1), kind=kind, run_minutes=run_min,
                      walk_minutes=walk_min, target_run_m=0, purpose="p", effort="e",
                      continuous_target_s=600 if kind == "LONG" else None)
    spec = build_workout(session, BANDS, phase)
    # Whole minutes (R6 §7): the generator minutes, each rounded to the nearest minute.
    assert spec.duration_s == 60 * round(run_min) + 60 * round(walk_min)
    assert sum(s.duration_s for s in spec.steps) == spec.duration_s


def test_titles():
    def title(kind, phase="AEROBIC", run=40.0, walk=0.0):
        s = Session(dt.date(2026, 1, 1), kind, run, walk, 0, "p", "e")
        return build_workout(s, BANDS, phase).title
    assert title("EASY") == "40m easy aerobic run"
    assert title("EASY", "PEAK", 30.0, 10.0) == "Easy run + 4 relaxed strides"
    assert title("LONG", run=60.0) == "Long run 60m"


def test_accept_archives_previous_and_deletes_its_future(athlete, proposed_plan):
    first = accept_plan(proposed_plan)
    assert first.status == TrainingPlan.Status.ACTIVE
    assert first.race.is_target
    today = athlete.local_today
    PlannedWorkout.objects.filter(plan=first).update(date=today)  # one stays "today"
    PlannedWorkout.objects.create(
        athlete=athlete, plan=first, date=today + dt.timedelta(days=3), title="future",
        kind="EASY", duration_s=600, load=10)

    second = propose_plan(athlete, race_name="B", race_date=today + dt.timedelta(weeks=12),
                          distance_km=5)
    accept_plan(second)
    first.refresh_from_db()
    assert first.status == TrainingPlan.Status.ARCHIVED
    assert not first.workouts.filter(date__gt=today).exists()
    assert first.workouts.filter(date=today).exists()
    assert TrainingPlan.objects.filter(athlete=athlete, status="active").count() == 1


def test_decline_removes_workouts_and_created_race(athlete, proposed_plan):
    race_id = proposed_plan.race_id
    decline_plan(proposed_plan)
    proposed_plan.refresh_from_db()
    assert proposed_plan.status == TrainingPlan.Status.DECLINED
    assert not proposed_plan.workouts.exists()
    assert not Race.objects.filter(pk=race_id).exists()


def test_synced_run_completes_the_days_workout(athlete, proposed_plan):
    from django.utils import timezone

    from apps.activities.models import Activity

    accept_plan(proposed_plan)
    workout = proposed_plan.workouts.order_by("date").first()
    activity = Activity.objects.create(
        athlete=athlete, source="fit_upload", sport="running",
        started_at=timezone.now(), local_date=workout.date, total_timer_s=1800,
    )
    workout.refresh_from_db()
    assert workout.status == "completed" and workout.completed_activity_id == activity.pk
    assert link_activity(activity) is None   # idempotent


def test_race_in_the_past_is_refused(athlete):
    from apps.planning.plan_store import PlanError

    with pytest.raises(PlanError):
        propose_plan(athlete, race_name="x", race_date=athlete.local_today, distance_km=10)
    assert not PlanPhase.objects.exists()


def test_empty_history_gets_beginner_sized_sessions(athlete, proposed_plan):
    """A new account has no runs. Sessions must still be real sessions, not 4 minutes."""
    assert proposed_plan.summary["baseline_source"] == "beginner_defaults"
    first_week = proposed_plan.workouts.order_by("date")[:4]
    assert all(w.duration_s >= 15 * 60 for w in first_week)
    assert any("beginner defaults" in w for w in proposed_plan.summary["warnings"])


# --- rebuild from the current profile -------------------------------------------------

def test_rebuild_uses_new_training_days_and_same_race(api, athlete, proposed_plan):
    from apps.planning.models import PlannedWorkout, TrainingPlan

    accept_plan(proposed_plan)
    old_race = proposed_plan.race_id
    athlete.available_days = {str(d): True for d in range(7)}
    athlete.long_run_day = 5
    athlete.save()

    r = api.post("/api/plans/active/rebuild/")
    assert r.status_code == 200, r.json()
    new = TrainingPlan.objects.get(pk=r.json()["id"])
    assert new.status == "active" and new.race_id == old_race and new.pk != proposed_plan.pk
    proposed_plan.refresh_from_db()
    assert proposed_plan.status == "archived"

    # Seven available days → still at most 4 runs in any week (beginner), never 7.
    from collections import Counter
    runs = PlannedWorkout.objects.filter(plan=new).exclude(kind__in=["WALK", "REST"])
    per_week = Counter(w.date.isocalendar()[:2] for w in runs)
    assert per_week and max(per_week.values()) <= 4


def test_rebuild_without_active_plan_is_409(api, athlete):
    assert api.post("/api/plans/active/rebuild/").status_code == 409


def test_rebuild_is_tenant_scoped(api, other_api, athlete, other_athlete, proposed_plan):
    accept_plan(proposed_plan)
    assert other_api.post("/api/plans/active/rebuild/").status_code == 409
