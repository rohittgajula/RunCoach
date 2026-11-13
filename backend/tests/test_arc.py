"""The arc series: past and future weeks on one axis, and the axis must be honest.

The bug this file exists to prevent is subtle and would not look like a bug. A
planned session's duration and an achieved unbroken run block are different
quantities. Draw them on one scale and the chart quietly claims the plan is
asking for a 30-minute unbroken run when it asked for a 30-minute session
holding a 10-minute block. The numbers would all be real; the picture would be a
lie. Several tests here only check that those two never meet.
"""

from __future__ import annotations

import datetime as dt

import pytest

from planning import arc

FRIDAY = dt.date(2026, 11, 13)
THAT_MONDAY = dt.date(2026, 11, 9)


def run(day, run_s=900, run_m=2300, block=380):
    return arc.RunRow(day=day, run_s=run_s, run_m=run_m, longest_run_s=block)


def plan(day, duration_s=1140, block_s=360, is_run=True, done=False):
    return arc.PlanRow(day=day, duration_s=duration_s, block_s=block_s,
                       is_run=is_run, done=done)


class TestWeekBuckets:
    def test_monday_is_the_week_start(self):
        assert arc.monday(FRIDAY) == THAT_MONDAY
        assert arc.monday(THAT_MONDAY) == THAT_MONDAY
        assert arc.monday(dt.date(2026, 11, 15)) == THAT_MONDAY   # the Sunday

    def test_empty_in_empty_out(self):
        assert arc.build(FRIDAY, [], []) == []

    def test_silent_weeks_are_kept(self):
        """The gap is the information. A series that skips it flatters the athlete."""
        weeks = arc.build(FRIDAY, [run(dt.date(2026, 10, 9)), run(dt.date(2026, 11, 10))], [])
        starts = [w.start for w in weeks]
        assert starts == [THAT_MONDAY - dt.timedelta(weeks=n) for n in range(5, -1, -1)]
        assert [w.runs_done for w in weeks] == [1, 0, 0, 0, 0, 1]

    def test_past_current_future_are_exclusive(self):
        weeks = arc.build(FRIDAY, [run(dt.date(2026, 11, 10))],
                          [plan(dt.date(2026, 11, 25))])
        for week in weeks:
            assert not (week.past and week.current)
        assert [w.start for w in weeks if w.current] == [THAT_MONDAY]
        assert all(w.start < THAT_MONDAY for w in weeks if w.past)

    def test_horizon_clamps_both_ends(self):
        weeks = arc.build(
            FRIDAY,
            [run(dt.date(2024, 1, 1))],                  # years back
            [plan(dt.date(2030, 1, 1))],                 # years forward
            past_weeks=3, future_weeks=2,
        )
        assert weeks[0].start == THAT_MONDAY - dt.timedelta(weeks=3)
        assert weeks[-1].start == THAT_MONDAY + dt.timedelta(weeks=2)


class TestDoneAndPlanned:
    def test_a_week_carries_both(self):
        weeks = arc.build(FRIDAY, [run(THAT_MONDAY, run_s=900, block=380)],
                          [plan(dt.date(2026, 11, 14), duration_s=1140, block_s=360)])
        now = next(w for w in weeks if w.current)
        assert (now.runs_done, now.run_s, now.longest_run_s) == (1, 900, 380)
        assert (now.runs_planned, now.planned_run_s, now.planned_block_s) == (1, 1140, 360)

    def test_gym_is_counted_apart_from_running(self):
        weeks = arc.build(FRIDAY, [], [
            plan(dt.date(2026, 11, 10), duration_s=2400, block_s=0, is_run=False, done=True),
            plan(dt.date(2026, 11, 13), duration_s=2400, block_s=0, is_run=False),
        ])
        now = next(w for w in weeks if w.current)
        assert (now.gym_planned, now.gym_done) == (2, 1)
        assert now.runs_planned == 0
        assert now.planned_run_s == 0, "a gym session is not running volume"

    def test_gym_never_contributes_a_block(self):
        weeks = arc.build(FRIDAY, [], [
            plan(dt.date(2026, 11, 10), duration_s=2400, block_s=2400, is_run=False),
        ])
        assert next(w for w in weeks if w.current).planned_block_s == 0

    def test_weekly_volume_sums_but_the_block_is_a_maximum(self):
        weeks = arc.build(FRIDAY, [
            run(dt.date(2026, 11, 9), run_s=600, run_m=1500, block=300),
            run(dt.date(2026, 11, 10), run_s=700, run_m=1800, block=420),
            run(dt.date(2026, 11, 11), run_s=500, run_m=1200, block=260),
        ], [])
        now = next(w for w in weeks if w.current)
        assert now.run_s == 1800 and now.run_m == 4500
        assert now.longest_run_s == 420, "blocks do not add up across three runs"


class TestTheRecordDoesNotExpire:
    def test_best_is_a_running_maximum(self):
        weeks = arc.build(FRIDAY, [
            run(dt.date(2026, 10, 9), block=699),      # 11:39
            run(dt.date(2026, 11, 10), block=392),     # 6:32, after five weeks off
        ], [])
        assert [w.best_run_s for w in weeks] == [699, 699, 699, 699, 699, 699]

    def test_best_never_falls_when_a_week_is_empty(self):
        weeks = arc.build(FRIDAY, [run(dt.date(2026, 10, 12), block=500)], [])
        assert all(w.best_run_s == 500 for w in weeks if w.start >= dt.date(2026, 10, 12))


class TestMissed:
    def test_a_finished_week_shows_what_was_skipped(self):
        last = THAT_MONDAY - dt.timedelta(weeks=1)
        weeks = arc.build(FRIDAY, [run(last)], [plan(last), plan(last + dt.timedelta(days=2)),
                                                plan(last + dt.timedelta(days=4))])
        done = next(w for w in weeks if w.start == last)
        assert done.missed == 2

    def test_the_future_cannot_have_missed_anything(self):
        ahead = THAT_MONDAY + dt.timedelta(weeks=2)
        weeks = arc.build(FRIDAY, [], [plan(ahead), plan(ahead + dt.timedelta(days=2))])
        assert next(w for w in weeks if w.start == ahead).missed == 0

    def test_an_extra_run_does_not_pay_off_a_skipped_session(self):
        """Four runs in a week that planned three, but on the wrong days, is not
        a clean week — and the generator already treats a missed session as lost
        rather than owed."""
        last = THAT_MONDAY - dt.timedelta(weeks=1)
        weeks = arc.build(
            FRIDAY,
            [run(last + dt.timedelta(days=n)) for n in (0, 1, 2, 3)],
            [plan(last + dt.timedelta(days=n)) for n in (0, 2, 5)],
        )
        done = next(w for w in weeks if w.start == last)
        assert done.runs_done == 4 and done.runs_planned == 3
        assert done.missed == 0


class TestPeak:
    def test_two_scales_not_one(self):
        weeks = arc.build(FRIDAY, [run(dt.date(2026, 11, 10), run_s=900, block=699)],
                          [plan(dt.date(2026, 12, 7), duration_s=1800, block_s=600)])
        scale = arc.peak(weeks)
        assert set(scale) == {"run_s", "block_s"}

    def test_a_long_session_never_inflates_the_block_scale(self):
        """The whole point. A 30-minute session must not stretch an axis that
        measures unbroken running."""
        weeks = arc.build(FRIDAY, [run(dt.date(2026, 11, 10), block=392)],
                          [plan(dt.date(2026, 12, 7), duration_s=3600, block_s=600)])
        assert arc.peak(weeks)["block_s"] == 600
        assert arc.peak(weeks)["run_s"] == 3600

    def test_never_zero(self):
        weeks = arc.build(FRIDAY, [run(dt.date(2026, 11, 10), run_s=0, block=0)], [])
        scale = arc.peak(weeks)
        assert scale["run_s"] >= 1 and scale["block_s"] >= 1, "a zero axis divides by zero"


class TestNotes:
    def test_the_record_is_quoted_with_its_week(self):
        weeks = arc.build(FRIDAY, [run(dt.date(2026, 10, 9), block=699)], [])
        assert any("11:39" in n for n in arc.describe(weeks, FRIDAY))

    def test_a_gap_is_named(self):
        weeks = arc.build(FRIDAY, [run(dt.date(2026, 10, 9)), run(dt.date(2026, 11, 10))], [])
        assert any("gap" in n for n in arc.describe(weeks, FRIDAY))

    def test_the_future_note_talks_about_a_block_not_a_session(self):
        weeks = arc.build(FRIDAY, [run(dt.date(2026, 10, 12))],
                          [plan(dt.date(2026, 12, 7), duration_s=1800, block_s=600)])
        note = next(n for n in arc.describe(weeks, FRIDAY) if "builds to" in n)
        assert "10:00" in note, "the block, not the session"
        assert "30 minutes" not in note, "1800s is the session and must not appear"

    def test_a_fresh_athlete_still_hears_what_the_plan_builds_to(self):
        """Nothing behind you is not a reason to say nothing about what is ahead."""
        weeks = arc.build(FRIDAY, [], [plan(THAT_MONDAY + dt.timedelta(weeks=3),
                                            duration_s=1500, block_s=540)])
        assert any("9:00" in n for n in arc.describe(weeks, FRIDAY))

    def test_nothing_at_all_says_nothing(self):
        assert arc.describe([], FRIDAY) == []
