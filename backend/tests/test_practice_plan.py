"""Training with no race on the calendar.

Rohit: "completely forget about race day, i am not participating in any race
now, i need practice only, i want to see improvement on myself."

The app's answer was to keep running his October race plan — a taper and a race
week on 11 January for an event he had deleted — and his own coach said so in
the UI: "The current planner cannot create a formal no-race plan."
"""

from __future__ import annotations

import datetime as dt

import pytest

from planning.generator import Baseline, PlanConfig
from planning.practice import (
    HORIZON_WEEKS, MILESTONES_S, generate_practice, milestone_for, passed,
)

START = dt.date(2026, 11, 13)


def baseline(**overrides) -> Baseline:
    defaults = dict(
        run_km_per_week=1.6,
        longest_run_s=392.0,            # Rohit's 9 Nov block: 6:32
        demonstrated_longest_s=837.0,   # his 20 Aug best: 13:57
        run_pace_s_per_km=604.0,
        walk_pace_s_per_km=700.0,
        available_days={"0": True, "1": True, "2": False, "3": True,
                        "4": False, "5": True, "6": True},
        long_run_day=6,
    )
    return Baseline(**{**defaults, **overrides})


# --- milestones -------------------------------------------------------------


def test_the_next_milestone_is_strictly_above_what_has_been_held():
    """A milestone you have already passed is not a target.

    Showing one is how an app ends up congratulating somebody for standing still.
    """
    assert milestone_for(392, 604).seconds == 10 * 60      # held 6:32 → aim at 10
    assert milestone_for(600, 604).seconds == 15 * 60      # held exactly 10 → aim at 15
    assert milestone_for(601, 604).seconds == 15 * 60


def test_the_ladder_tops_out_and_says_so():
    """Past an hour the question stops being "can you keep running"."""
    top = milestone_for(99_999, 604)
    assert top.reached is True
    assert top.seconds == MILESTONES_S[-1]


def test_a_milestone_carries_the_distance_it_implies_at_this_athletes_pace():
    """The target is the minutes; the distance is what they will say out loud."""
    m = milestone_for(392, 604)
    assert 950 < m.distance_m < 1050      # 10 min at 10:04/km ≈ 0.99 km


def test_passed_lists_what_has_actually_been_done():
    assert passed(392) == [300]
    assert passed(837) == [300, 600]


# --- the plan ---------------------------------------------------------------


def test_there_is_no_taper_and_no_race_week():
    """The entire point. A race plan's shape is wrong when there is no race."""
    plan = generate_practice(START, baseline(), PlanConfig())
    phases = {week.phase for week in plan.weeks}
    assert "TAPER" not in phases
    assert "RACE" not in phases
    kinds = {s.kind for week in plan.weeks for s in week.sessions}
    assert "RACE" not in kinds


def test_it_still_obeys_the_safety_rules_a_race_plan_obeys():
    """No race does not mean no rules.

    The weekly increase cap and the cutback every fourth week are the two that
    keep somebody uninjured, and they are not features of racing.
    """
    config = PlanConfig()
    plan = generate_practice(START, baseline(), config)
    loading = [w for w in plan.weeks if not w.is_cutback]

    for previous, current in zip(loading, loading[1:]):
        rise = (current.planned_run_km - previous.planned_run_km) / previous.planned_run_km
        assert rise <= config.max_weekly_increase_pct / 100 + 0.01

    assert any(w.is_cutback for w in plan.weeks), "a down week must appear"


def test_ground_already_held_comes_back_faster_than_new_ground():
    """Rohit held 11:39 in October and came back at 6:32 after four weeks off.

    Rebuilding to it at the normal cap takes about eight weeks of training to
    arrive back where he already was. That is the difference between a plan
    that matches his experience and one he stops believing.
    """
    returning = generate_practice(START, baseline(demonstrated_longest_s=837.0), PlanConfig())
    fresh = generate_practice(START, baseline(demonstrated_longest_s=392.0), PlanConfig())

    def week_reaching(plan, seconds):
        return next((w.index for w in plan.weeks if w.continuous_target_s >= seconds), None)

    back = week_reaching(returning, 699)     # his October best
    first_time = week_reaching(fresh, 699)
    assert back is not None
    assert first_time is None or back < first_time


def test_the_volume_ceiling_follows_where_the_block_is_going():
    """Not where the athlete is standing today.

    Pinning the ceiling to the current milestone capped Rohit at 2.8 km a week
    when he ran 5.3 in August — he passes three rungs inside one horizon.
    """
    plan = generate_practice(START, baseline(), PlanConfig())
    assert plan.ideal_peak_run_km > 5.0
    # And the ceiling must not be what binds: the weekly cap should.
    assert plan.peak_run_km < plan.ideal_peak_run_km


def test_the_horizon_is_finite_and_honest():
    """An open-ended plan that projects a year out is a year of fiction."""
    plan = generate_practice(START, baseline(), PlanConfig())
    assert plan.weeks_available == HORIZON_WEEKS
    assert len(plan.weeks) == HORIZON_WEEKS


def test_nothing_in_it_can_be_failed():
    """No deadline is attached to the milestone.

    The honest answer to "when will I run for thirty minutes" is a projection,
    and a projection presented as a deadline is a race with extra steps.
    """
    plan = generate_practice(START, baseline(), PlanConfig())
    text = " ".join(plan.warnings).lower()
    assert "deadline" in text or "when you pass it" in text
    assert plan.race_needs_continuous_s == 10 * 60    # the milestone, not a race


def test_a_complete_beginner_still_gets_a_plan():
    """No history, no demonstrated best, no division by zero."""
    plan = generate_practice(
        START, baseline(longest_run_s=0.0, demonstrated_longest_s=0.0), PlanConfig(),
    )
    assert len(plan.weeks) == HORIZON_WEEKS
    assert all(w.planned_run_km > 0 for w in plan.weeks)
    assert plan.peak_continuous_s > 0


# --- a distance by a date, with no race -------------------------------------


def test_an_impossible_date_is_refused_with_the_possible_one():
    """The whole reason this mode differs from a race plan.

    A race date is a fact, so a plan to it is built and warned about. A
    self-set date is a wish, and the useful answer to an impossible wish is the
    possible one beside it — "no" on its own just makes somebody pick another
    number.
    """
    from planning.practice import assess_goal

    soon = assess_goal(START, START + dt.timedelta(days=90), 5.0, baseline(), PlanConfig())
    assert soon.achievable is False
    assert soon.earliest_date is not None
    assert soon.earliest_date > START + dt.timedelta(days=90)


def test_the_earliest_date_does_not_depend_on_what_was_asked():
    """It drifted by days with the requested date in the first version.

    "The honest date" that changes depending on the question looks like a guess,
    because it is one.
    """
    from planning.practice import assess_goal

    answers = {
        assess_goal(START, START + dt.timedelta(days=days), 5.0,
                    baseline(), PlanConfig()).earliest_date
        for days in (60, 90, 180, 210, 365)
    }
    assert len(answers) == 1


def test_a_realistic_date_is_confirmed_rather_than_hedged():
    from planning.practice import assess_goal, generate_goal

    far = START + dt.timedelta(days=300)
    verdict = assess_goal(START, far, 5.0, baseline(), PlanConfig())
    assert verdict.achievable is True

    plan, _ = generate_goal(START, far, 5.0, baseline(), PlanConfig())
    assert "realistic" in plan.warnings[0]


def test_a_goal_plan_still_has_no_race_week():
    """A date is not a race. No taper, no race session, no entry."""
    from planning.practice import generate_goal

    plan, _ = generate_goal(START, START + dt.timedelta(days=300), 5.0,
                            baseline(), PlanConfig())
    phases = {w.phase for w in plan.weeks}
    assert "TAPER" not in phases and "RACE" not in phases


def test_a_distance_beyond_the_continuous_ceiling_says_so_without_a_date():
    """10 km nonstop at 10:04/km is 100 minutes; the generator caps at 75.

    Returning a confident date for something the plan will never prescribe
    would be the worst possible answer.
    """
    from planning.practice import assess_goal

    verdict = assess_goal(START, START + dt.timedelta(days=700), 10.0,
                          baseline(), PlanConfig())
    assert verdict.achievable is False
    assert verdict.earliest_date is None
