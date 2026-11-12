"""The rest of the plan, after an interruption.

These tests exist because of one sentence Rohit wrote four times: if he says he
is sick or cannot run, the *whole* future plan should change, not the next
session. The assertions below are that sentence, made checkable.
"""

from __future__ import annotations

import datetime as dt

import pytest

from planning.cascade import NOISE_S, WeekPlan, describe, rebuild

MONDAY = dt.date(2026, 11, 16)


def plan(volumes: list[int], cutbacks: tuple[int, ...] = (), taper_from: int | None = None):
    return [
        WeekPlan(
            index=i,
            start=MONDAY + dt.timedelta(days=7 * i),
            phase="TAPER" if taper_from is not None and i >= taper_from else "BUILD",
            planned_run_s=v,
            is_cutback=i in cutbacks,
        )
        for i, v in enumerate(volumes)
    ]


def test_an_interruption_reaches_every_week_after_it():
    """The whole point. Two sessions is not a plan change."""
    weeks = plan([1800, 1980, 2180, 2400, 2640, 2900])
    # Week 1 was meant to be 33 minutes; 10 actually happened.
    result = rebuild(weeks, achieved_run_s=600, from_index=1)

    assert result.anything
    # Every week from the interruption onward moved, not just the next one.
    assert set(result.changed) == {1, 2, 3, 4, 5}
    assert result.peak_after_s < result.peak_before_s


def test_the_past_is_never_rewritten():
    """Rewriting last week would change the history the baseline is built from."""
    weeks = plan([1800, 1980, 2180, 2400])
    result = rebuild(weeks, achieved_run_s=600, from_index=2)

    assert result.weeks[0].planned_run_s == 1800
    assert result.weeks[1].planned_run_s == 1980
    assert 0 not in result.changed and 1 not in result.changed


def test_a_missed_session_is_lost_not_owed():
    """Nothing is ever carried forward.

    Adding the missed kilometres onto a later week is the most common mistake in
    self-coached training, and the most reliable way to turn a missed easy run
    into an injury.
    """
    weeks = plan([1800, 1980, 2180, 2400])
    result = rebuild(weeks, achieved_run_s=0, from_index=1)

    after = [w.planned_run_s for w in result.weeks]
    assert after[1] == 0
    # No week afterwards is above what it was originally asked to do.
    for original, rebuilt in zip(weeks, result.weeks):
        assert rebuilt.planned_run_s <= original.planned_run_s


def test_the_ramp_restarts_from_what_was_done():
    """Not from where the schedule wanted the athlete to be."""
    weeks = plan([1800, 1980, 2180, 2400, 2640])
    result = rebuild(weeks, achieved_run_s=900, from_index=1, max_weekly_increase_pct=10)

    after = [w.planned_run_s for w in result.weeks]
    assert after[1] == 900
    assert after[2] == pytest.approx(990, abs=2)      # 900 x 1.10
    assert after[3] == pytest.approx(1089, abs=3)     # and again


def test_it_never_makes_a_week_harder_than_planned():
    """Every path through this module reduces or holds. None raises.

    The worst case here must be training slightly less than you could have.
    """
    weeks = plan([1800, 1980, 2180, 2400, 2640])
    # An athlete who somehow did MORE than prescribed still cannot have the
    # following weeks inflated past what the plan intended.
    result = rebuild(weeks, achieved_run_s=9000, from_index=1)

    for original, rebuilt in zip(weeks, result.weeks):
        assert rebuilt.planned_run_s <= original.planned_run_s


def test_a_cutback_week_stays_a_cutback():
    """Recovery is needed more after an interruption, not less."""
    weeks = plan([1800, 1980, 2180, 2400], cutbacks=(3,))
    result = rebuild(weeks, achieved_run_s=1200, from_index=1, cutback_factor=0.7)

    after = [w.planned_run_s for w in result.weeks]
    assert after[3] < after[2], "the down week is still down"


def test_a_taper_follows_the_rebuilt_ramp():
    """A taper is a fraction of what was REACHED, not of what was hoped for."""
    weeks = plan([1800, 1980, 2180, 2400, 2640], taper_from=4)
    result = rebuild(weeks, achieved_run_s=900, from_index=1)

    build_peak = max(w.planned_run_s for w in result.weeks if w.phase != "TAPER")
    taper = result.weeks[4].planned_run_s
    assert taper < build_peak
    assert taper <= 2640, "never above what the plan intended"


def test_small_differences_are_not_an_interruption():
    """Thirty seconds is not a reason to rebuild eleven weeks.

    Without this, stopping at a traffic light reshapes December.
    """
    weeks = plan([1800, 1980, 2180])
    result = rebuild(weeks, achieved_run_s=1800 - (NOISE_S - 10), from_index=0)
    assert 0 not in result.changed


def test_the_description_is_computed_not_written():
    """It cannot claim a change that did not happen, or miss one that did."""
    weeks = plan([1800, 1980, 2180, 2400])
    result = rebuild(weeks, achieved_run_s=600, from_index=1)
    lines = describe(result, weeks)

    assert lines, "a change that happened must be described"
    assert any("peak week" in line for line in lines)
    assert any("16 Nov" in line or "23 Nov" in line for line in lines)


def test_nothing_changed_says_nothing():
    weeks = plan([1800, 1980, 2180])
    result = rebuild(weeks, achieved_run_s=1800, from_index=0)
    assert not result.anything
    assert describe(result, weeks) == []
