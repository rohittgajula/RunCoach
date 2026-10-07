"""R8 §A, pure: runs per week in the generator and the re-layout of a week."""

import datetime as dt

import pytest

from planning.generator import (
    MIN_SESSION_MINUTES, Baseline, effective_run_days, fit_run_count, generate_plan,
)
from planning.relayout import WeekVolume, relayout_week

ALL_DAYS = {str(d): True for d in range(7)}
RUNS = {"RUN_WALK", "EASY", "LONG", "INTERVALS", "TEMPO"}


def baseline(km=20.0, runs=None, days=ALL_DAYS):
    return Baseline(run_km_per_week=km, longest_run_s=1800, run_pace_s_per_km=400,
                    walk_pace_s_per_km=800, available_days=days, long_run_day=6,
                    runs_per_week=runs)


def plan(**kw):
    start = dt.date(2026, 10, 12)
    return generate_plan(start, start + dt.timedelta(weeks=12), 10.0, baseline(**kw))


def run_sessions(week):
    return [s for s in week.sessions if s.kind in RUNS and not s.optional]


def test_effective_is_min_of_choice_days_and_six():
    assert effective_run_days(None, 4, 7) == 4
    assert effective_run_days(6, 4, 7) == 6
    assert effective_run_days(6, 4, 3) == 3
    assert effective_run_days(9, 4, 7) == 6          # never 7: always a rest day


@pytest.mark.parametrize("runs", [2, 3, 5, 6])
def test_same_weekly_volume_split_across_chosen_days(runs):
    default, chosen = plan(), plan(runs=runs)
    for a, b in zip(default.weeks, chosen.weeks):
        assert a.planned_run_km == b.planned_run_km          # volume unchanged
        if b.phase == "RACE":
            continue
        n = len(run_sessions(b))
        assert n <= runs and len({s.date for s in run_sessions(b)}) == n
        total = sum(s.run_minutes for s in run_sessions(b))
        assert total == pytest.approx(b.planned_run_km * 400 / 60, abs=0.5)


def test_six_runs_keep_a_rest_day_and_no_session_under_15_min():
    p = plan(km=30.0, runs=6)
    for week in p.weeks:
        runs = run_sessions(week)
        assert len(runs) <= 6
        if week.phase != "RACE":
            assert all(s.total_minutes >= MIN_SESSION_MINUTES - 0.1 for s in runs), week.phase


def test_too_little_volume_uses_fewer_sessions_and_says_so():
    p = plan(km=5.0, runs=6)
    first = p.weeks[0]
    assert len(run_sessions(first)) < 6
    assert all(s.total_minutes >= MIN_SESSION_MINUTES - 0.1 for s in run_sessions(first))
    assert any("instead of 6" in n and "15 min" in n for n in p.notes)


def test_fit_run_count_never_below_two():
    assert fit_run_count(10, 0.35, 0.5, 6) == 2
    assert fit_run_count(200, 0.35, 0.8, 6) == 6
    assert fit_run_count(10, 0.35, 0.5, 1) == 1


def test_hard_session_rules_unchanged():
    for week in plan(km=30.0, runs=6).weeks:
        hard = sorted(s.date for s in week.sessions if s.kind in ("INTERVALS", "TEMPO"))
        assert len(hard) <= 1                           # long run counts as one of two
        assert all((b - a).days > 1 for a, b in zip(hard, hard[1:]))


def test_relayout_keeps_run_and_walk_time():
    week = WeekVolume(start=dt.date(2026, 10, 19), phase="AEROBIC", run_s=6000, walk_s=3000,
                      long_continuous_s=900)
    for runs in (3, 4, 5, 6):
        sessions, notes = relayout_week(week, available_days=ALL_DAYS, long_run_day=6,
                                        runs=runs)
        assert sum(s.run_minutes for s in sessions) == pytest.approx(100, abs=0.5)
        assert sum(s.walk_minutes for s in sessions) == pytest.approx(50, abs=0.5)
        assert len(sessions) <= runs and not notes
        assert sum(1 for s in sessions if s.kind == "LONG") == 1
        long_run = next(s for s in sessions if s.kind == "LONG")
        assert long_run.date.weekday() == 6 and long_run.continuous_target_s == 900
        assert all(week.start <= s.date < week.start + dt.timedelta(days=7) for s in sessions)


def test_relayout_respects_last_date_and_race_week():
    week = WeekVolume(start=dt.date(2026, 10, 19), phase="TAPER",
                      run_s=3000, walk_s=600)
    last = dt.date(2026, 10, 22)
    sessions, _ = relayout_week(week, available_days=ALL_DAYS, long_run_day=6, runs=4,
                                last_date=last)
    assert sessions and all(s.date <= last for s in sessions)
    race = WeekVolume(start=dt.date(2026, 10, 19), phase="RACE", run_s=3000, walk_s=0)
    assert relayout_week(race, available_days=ALL_DAYS, long_run_day=6, runs=4) == ([], [])


def test_relayout_minimum_session_note():
    week = WeekVolume(start=dt.date(2026, 10, 19), phase="FOUNDATION", run_s=1200, walk_s=1800)
    sessions, notes = relayout_week(week, available_days=ALL_DAYS, long_run_day=6, runs=6)
    assert len(sessions) < 6 and notes and "the week's volume" in notes[0]
