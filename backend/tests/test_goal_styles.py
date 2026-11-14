"""A distance by a date means two different things, and the app knew only one.

Rohit: "5k between march and april with breaks."

The dated goal mode planned for running the distance WITHOUT STOPPING and had
no way to express anything else, so his request would have been answered with a
refusal — accurate about running 5 km unbroken, and about a question he had not
asked. These tests pin the difference between the two readings, because the
whole risk in this feature is the two being quietly confused for each other.
"""

from __future__ import annotations

import datetime as dt

import pytest

from planning.generator import Baseline, PlanConfig
from planning.practice import (
    assess_goal, blended_pace_s_per_km, coverage_factor, generate_goal,
    weekly_volume_for_coverage,
)

START = dt.date(2026, 11, 14)


def baseline(**overrides) -> Baseline:
    """Rohit in November 2026, at the beginner weekly floor.

    run_km_per_week is 5.0 because that is the floor `from_history` applies to
    everybody; a lower figure cannot reach a Baseline through the app, and a
    test written around one measures a state that does not occur.
    """
    defaults = dict(
        run_km_per_week=5.0,
        longest_run_s=392.0,            # 9 Nov: 6:32 unbroken
        demonstrated_longest_s=837.0,   # 20 Aug: 13:57
        run_pace_s_per_km=604.0,        # 10:04/km running
        walk_pace_s_per_km=700.0,       # 11:40/km walking
        demonstrated_covered_m=2500.0,  # 9 Nov: 2.5 km covered in 32 minutes
        available_days={"0": True, "1": True, "2": False, "3": True,
                        "4": False, "5": True, "6": True},
        long_run_day=6,
    )
    return Baseline(**{**defaults, **overrides})


# --- the coverage maths -----------------------------------------------------


def test_walking_counts_toward_distance_covered_and_not_toward_the_block():
    """The one fact the whole mode rests on.

    At a FOUNDATION session's 60 % walking, Rohit covers 2.29 metres for every
    metre he runs. Ignoring that is why 5 km looked two years away.
    """
    factor = coverage_factor(0.4, 604.0, 700.0)
    assert 2.25 < factor < 2.35
    # Running every step covers exactly what you run, and nothing extra.
    assert coverage_factor(1.0, 604.0, 700.0) == 1.0


def test_the_blended_pace_sits_between_the_two_real_paces():
    """A session that is part run and part walk cannot be faster than the
    running or slower than the walking, and a formula that lets it be either is
    wrong in a way nobody would notice from the plan."""
    pace = blended_pace_s_per_km(0.55, 604.0, 700.0)
    assert 604.0 < pace < 700.0
    # The ends are the paces themselves.
    assert blended_pace_s_per_km(1.0, 604.0, 700.0) == pytest.approx(604.0)
    assert blended_pace_s_per_km(0.001, 604.0, 700.0) == pytest.approx(700.0, rel=1e-2)


def test_the_volume_ceiling_rounds_up_so_the_ramp_actually_arrives():
    """Every other figure in the volume curve rounds DOWN, because rounding up
    lets a 10 % cap print an 11 % step. A ceiling is not a step: 5 km needs
    7.711 km a week, and truncating it to 7.7 tops the ramp out covering
    4.99 km — seven metres short of the entire point of the plan."""
    needed = weekly_volume_for_coverage(5.0, "AEROBIC", baseline(), PlanConfig())
    assert needed >= 5.0 / (0.38 * coverage_factor(0.55, 604.0, 700.0))
    assert needed == pytest.approx(7.8)


# --- the two readings are genuinely different -------------------------------


def test_breaks_turn_an_impossible_date_into_a_comfortable_one():
    """Rohit's actual request. The two answers are five months apart."""
    march = dt.date(2027, 3, 31)
    nonstop = assess_goal(START, march, 5.0, baseline(), PlanConfig(), style="nonstop")
    run_walk = assess_goal(START, march, 5.0, baseline(), PlanConfig(), style="run_walk")

    assert nonstop.achievable is False
    assert run_walk.achievable is True
    assert run_walk.earliest_date < nonstop.earliest_date


def test_ten_km_has_no_nonstop_date_at_all_and_a_perfectly_ordinary_one_with_breaks():
    """The continuous curve ceilings at 75 minutes, so 10 km unbroken at a
    beginner's pace has no honest date — the old mode's only possible answer.
    Walking is not capped at 75 minutes, and the ceiling must not be borrowed
    across to a question it does not govern."""
    far = dt.date(2028, 12, 31)
    nonstop = assess_goal(START, far, 10.0, baseline(), PlanConfig(), style="nonstop")
    run_walk = assess_goal(START, far, 10.0, baseline(), PlanConfig(), style="run_walk")

    assert nonstop.earliest_date is None
    assert run_walk.earliest_date is not None


def test_the_refused_nonstop_goal_points_at_the_one_that_works():
    """"No" on its own just makes somebody pick another number."""
    plan, verdict = generate_goal(START, dt.date(2028, 12, 31), 10.0, baseline(),
                                  PlanConfig(), style="nonstop")
    assert verdict.earliest_date is None
    assert "breaks" in plan.warnings[0]


# --- the two must not be mixed up -------------------------------------------


def test_each_style_leaves_the_other_style_numbers_empty():
    """They are measured in different units — seconds of unbroken running
    against metres covered in one session. A plausible number in the wrong unit
    is how this goes wrong silently, so the unused pair stays at zero."""
    march = dt.date(2027, 3, 31)
    nonstop = assess_goal(START, march, 5.0, baseline(), PlanConfig(), style="nonstop")
    run_walk = assess_goal(START, march, 5.0, baseline(), PlanConfig(), style="run_walk")

    assert nonstop.needs_s > 0 and nonstop.needs_m == 0
    assert run_walk.needs_m > 0 and run_walk.needs_s == 0
    assert nonstop.governs != run_walk.governs
    assert run_walk.label.endswith("with walk breaks")
    assert nonstop.label.endswith("without stopping")


def test_a_run_walk_goal_leaves_the_milestone_ladder_alone():
    """The unbroken block still progresses underneath a run-walk goal, so the
    plan's continuous yardstick must stay the milestone rather than being
    overwritten with a distance nobody is trying to run unbroken."""
    march = dt.date(2027, 3, 31)
    plan, _ = generate_goal(START, march, 5.0, baseline(), PlanConfig(), style="run_walk")
    # 5 km at 10:04/km would be 3020 s if the nonstop yardstick leaked in.
    assert plan.race_needs_continuous_s < 3020


# --- the projection must match the plan it belongs to -----------------------


def test_the_projection_does_not_overshoot_the_plan_it_describes():
    """It did, and it read as confidence: searching with an unbounded ceiling
    projected the long run covering 11.6 km for a 5 km goal, because nothing
    stopped the ramp once it passed the target."""
    verdict = assess_goal(START, dt.date(2027, 3, 31), 5.0, baseline(), PlanConfig(),
                          style="run_walk")
    assert verdict.reaches_m < 6000


def test_the_plan_is_allowed_the_volume_its_own_goal_needs():
    """The milestone ladder sets the volume ceiling for a practice plan, and
    for a run-walk goal it stops the ramp short of a distance the athlete asked
    for in as many words."""
    plan, verdict = generate_goal(START, dt.date(2027, 3, 31), 5.0, baseline(),
                                  PlanConfig(), style="run_walk")
    assert plan.ideal_peak_run_km >= verdict.peak_run_km_needed


def test_an_athlete_already_past_the_goal_is_not_stepped_backwards():
    """The search ceiling is the volume the goal needs, and for somebody
    already running more than that it sits BELOW where they are. Floored the
    same way the plan floors it, or the projection walks their week down to the
    ceiling while the plan they are handed walks it up."""
    fit = baseline(run_km_per_week=25.0)
    verdict = assess_goal(START, dt.date(2027, 3, 31), 5.0, fit, PlanConfig(),
                          style="run_walk")
    assert verdict.weeks_needed == 0
    plan, _ = generate_goal(START, dt.date(2027, 3, 31), 5.0, fit, PlanConfig(),
                            style="run_walk")
    volumes = [w.planned_run_km for w in plan.weeks]
    assert min(volumes) >= 25.0 * 0.7 - 1e-9, volumes


def test_the_weekly_cap_still_holds_on_a_run_walk_goal():
    """Raising the ceiling must move only where the ramp stops, never how fast
    it climbs. The cap is an injury rule, not a tuning knob.

    Measured across LOADING weeks. A cutback prescribes 70 % of a trajectory it
    does not unlearn, so the week after one returns to that trajectory and the
    printed step looks like 60 % — comparing raw consecutive weeks measures the
    cutback rather than the ramp, which is how an earlier version of this test
    failed a plan that was behaving correctly.
    """
    plan, _ = generate_goal(START, dt.date(2027, 3, 31), 5.0, baseline(),
                            PlanConfig(), style="run_walk")
    loading = [w.planned_run_km for w in plan.weeks if not w.is_cutback]
    for before, after in zip(loading, loading[1:]):
        assert after <= before * 1.1 + 1e-9, f"{before} -> {after}"
    # And the cutbacks really are cutbacks, not a gap in the check.
    assert any(w.is_cutback for w in plan.weeks)


# --- what already happened outranks a projection of it ----------------------


def test_nobody_is_given_a_date_to_reach_a_distance_they_have_covered():
    """The volume curve divides a weekly figure across the week, so it can
    place the long run below a session that actually happened — and then quote
    six weeks to reach ground the athlete covered in August."""
    done = baseline(demonstrated_covered_m=5200.0)
    verdict = assess_goal(START, dt.date(2027, 3, 31), 5.0, done, PlanConfig(),
                          style="run_walk")
    assert verdict.weeks_needed == 0
    assert verdict.earliest_date == START


def test_demonstrated_coverage_does_not_leak_into_the_nonstop_answer():
    """Covering 5 km with walking says nothing about running it unbroken."""
    done = baseline(demonstrated_covered_m=5200.0)
    plain = assess_goal(START, dt.date(2027, 3, 31), 5.0, baseline(), PlanConfig(),
                        style="nonstop")
    with_coverage = assess_goal(START, dt.date(2027, 3, 31), 5.0, done, PlanConfig(),
                                style="nonstop")
    assert with_coverage.earliest_date == plain.earliest_date


# --- the honest warning -----------------------------------------------------


def test_a_run_walk_goal_says_how_long_the_attempt_takes():
    """The fact that decides whether somebody wants it. "5 km" sounds like one
    thing; "an hour on your feet" is the thing it actually is."""
    plan, verdict = generate_goal(START, dt.date(2027, 3, 31), 5.0, baseline(),
                                  PlanConfig(), style="run_walk")
    assert verdict.session_s > 0
    assert "minutes on your feet" in plan.warnings[0]


def test_an_absurdly_long_run_walk_is_flagged_rather_than_quietly_planned():
    """Nothing in the coverage maths stops a marathon being "achievable" by
    walking most of it over enough weeks. It is still eight hours out."""
    plan, _ = generate_goal(START, dt.date(2029, 12, 31), 42.2, baseline(),
                            PlanConfig(), style="run_walk")
    assert any("day out" in w for w in plan.warnings)
