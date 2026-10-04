"""R6 §2: weekly adaptation — repeat (<60 %), cap (>130 %), follow; idempotent."""

import datetime as dt

import pytest
from django.utils import timezone

from apps.planning.adaptation import adapt_week, run_seconds
from apps.planning.models import PlanAdjustment, PlannedWorkout
from apps.planning.plan_store import accept_plan
from planning.adaptation import decide
from tests.r6_helpers import make_activity


def test_decide_rules():
    assert decide(3600, 1800, 4000).rule == "repeat"
    assert decide(3600, 1800, 4000).factor == pytest.approx(3600 / 4000, abs=0.001)
    assert decide(3600, 5000, 4000).rule == "cap" and decide(3600, 5000, 4000).factor == 1.0
    assert decide(3600, 3600, 4000).rule == "follow" and decide(3600, 3600, 4000).factor == 1.0
    assert decide(3600, 1000, 3000).factor == 1.0      # next week already not bigger
    assert decide(0, 1000, 3000).rule == "none"


@pytest.fixture
def plan_in_week_two(athlete, proposed_plan):
    """An accepted plan whose first week is now 'last week' (dates shifted back)."""
    plan = accept_plan(proposed_plan)
    today = athlete.local_today
    this_monday = today - dt.timedelta(days=today.weekday())
    first = plan.workouts.order_by("date").first().date
    first_monday = first - dt.timedelta(days=first.weekday())
    shift = first_monday - (this_monday - dt.timedelta(days=7))
    for workout in plan.workouts.all():
        PlannedWorkout.objects.filter(pk=workout.pk).update(date=workout.date - shift)
    plan.accepted_at = timezone.now() - dt.timedelta(days=30)
    plan.save(update_fields=["accepted_at"])
    return plan


def week(plan, monday):
    return list(plan.workouts.filter(date__gte=monday, date__lt=monday + dt.timedelta(days=7))
                .exclude(status="skipped"))


def mondays(athlete):
    today = athlete.local_today
    this_monday = today - dt.timedelta(days=today.weekday())
    return this_monday - dt.timedelta(days=7), this_monday


def run_last_week(athlete, plan, fraction):
    last, _ = mondays(athlete)
    planned = sum(run_seconds(w) for w in week(plan, last))
    make_activity(athlete, last + dt.timedelta(days=1), run_s=round(planned * fraction),
                  walk_s=0)
    return planned


def test_low_week_repeats_volume(athlete, plan_in_week_two):
    plan = plan_in_week_two
    last, this = mondays(athlete)
    planned_last = run_last_week(athlete, plan, 0.4)
    # Make this week bigger than last so "repeat" has something to shrink.
    for w in week(plan, this):
        if w.kind != "RACE":
            PlannedWorkout.objects.filter(pk=w.pk).update(
                steps=[{**s, "duration_s": s["duration_s"] * 2} for s in w.steps])
    future_before = {w.pk: run_seconds(w) for w in week(plan, this)}
    assert future_before
    adjustment = adapt_week(athlete, today=mondays(athlete)[1])
    assert adjustment is not None and adjustment.factor < 1.0
    assert adjustment.week_start == this and "repeats" in adjustment.reason
    assert adjustment.planned_run_s == planned_last
    for w in week(plan, this):
        if w.pk in future_before and w.kind != "RACE":
            assert run_seconds(w) < future_before[w.pk]
            assert sum(s["duration_s"] for s in w.steps) == w.duration_s


def test_high_week_caps_and_normal_follows(athlete, plan_in_week_two):
    plan = plan_in_week_two
    _, this = mondays(athlete)
    run_last_week(athlete, plan, 1.5)
    before = {w.pk: w.steps for w in week(plan, this)}
    adjustment = adapt_week(athlete, today=mondays(athlete)[1])
    assert adjustment.factor == 1.0 and "does not increase" in adjustment.reason
    assert {w.pk: w.steps for w in week(plan, this)} == before


def test_normal_week_follows_plan(athlete, plan_in_week_two):
    plan = plan_in_week_two
    _, this = mondays(athlete)
    run_last_week(athlete, plan, 1.0)
    before = {w.pk: w.steps for w in week(plan, this)}
    adjustment = adapt_week(athlete, today=mondays(athlete)[1])
    assert adjustment.factor == 1.0 and "On track" in adjustment.reason
    assert {w.pk: w.steps for w in week(plan, this)} == before


def test_adapt_is_idempotent_per_week(athlete, plan_in_week_two):
    plan = plan_in_week_two
    _, this = mondays(athlete)
    run_last_week(athlete, plan, 0.3)
    first = adapt_week(athlete, today=mondays(athlete)[1])
    after_first = {w.pk: w.steps for w in week(plan, this)}
    second = adapt_week(athlete, today=mondays(athlete)[1])
    assert first.pk == second.pk
    assert PlanAdjustment.objects.filter(plan=plan).count() == 1
    assert {w.pk: w.steps for w in week(plan, this)} == after_first


def test_unplanned_runs_count_towards_actual(athlete, plan_in_week_two):
    plan = plan_in_week_two
    last, _ = mondays(athlete)
    planned = sum(run_seconds(w) for w in week(plan, last))
    workout_days = {w.date for w in week(plan, last)}
    free = next(last + dt.timedelta(days=i) for i in range(7)
                if last + dt.timedelta(days=i) not in workout_days)
    make_activity(athlete, free, run_s=planned, walk_s=0)        # all of it "extra"
    assert adapt_week(athlete, today=mondays(athlete)[1]).actual_run_s == planned


def test_no_active_plan_is_a_noop(athlete):
    assert adapt_week(athlete) is None


def test_plan_detail_lists_adjustments(api, athlete, plan_in_week_two):
    run_last_week(athlete, plan_in_week_two, 1.0)
    adapt_week(athlete, today=mondays(athlete)[1])
    body = api.get(f"/api/plans/{plan_in_week_two.pk}/").json()
    assert len(body["adjustments"]) == 1
    assert set(body["adjustments"][0]) == {"week_start", "reason", "factor", "created_at"}
