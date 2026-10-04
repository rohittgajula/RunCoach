"""R6 §1: a break no longer erases running history."""

import datetime as dt

import pytest

from planning.baseline import (
    BEGINNER_RUN_KM_PER_WEEK, RunPoint, detraining_factor, from_history, recent_block,
)

TODAY = dt.date(2026, 10, 4)


def run(day, km=3.0, longest=600):
    return RunPoint(date=day, run_distance_m=km * 1000, longest_run_s=longest,
                    run_pace_s_per_km=420, walk_pace_s_per_km=760)


@pytest.mark.parametrize("gap,factor", [
    (0, 1.0), (14, 1.0), (15, 0.85), (28, 0.85), (29, 0.7), (56, 0.7), (57, 0.5), (110, 0.5),
])
def test_detraining_bands(gap, factor):
    assert detraining_factor(gap) == factor


def best_august_week():
    # Best week: 17-23 Aug, 3 runs x 4 km = 12 km. Last run 24 Aug.
    return [run(dt.date(2026, 8, d), 4.0, 900) for d in (17, 19, 21)] + [
        run(dt.date(2026, 8, 9), 2.0), run(dt.date(2026, 8, 24), 3.0, 700)]


def test_six_week_gap_uses_history_at_70_percent():
    result = from_history(best_august_week(), TODAY)
    assert result.source == "history"
    assert result.last_run_date == dt.date(2026, 8, 24)
    assert result.gap_days == 41
    assert result.detraining_factor == 0.7
    assert result.best_week_km == 12.0
    assert result.run_km_per_week == pytest.approx(12.0 * 0.7)
    assert result.longest_run_s == pytest.approx(900 * 0.7)
    assert "6 weeks ago" in result.warning and "70 %" in result.warning
    assert "August" in result.warning


def test_recent_gap_keeps_full_volume():
    runs = [run(TODAY - dt.timedelta(days=d), 5.0) for d in (3, 5, 9)]
    result = from_history(runs, TODAY)
    assert result.detraining_factor == 1.0 and result.warning is None


def test_never_below_the_beginner_default():
    runs = [run(TODAY - dt.timedelta(days=100), 1.5)]
    result = from_history(runs, TODAY)
    assert result.detraining_factor == 0.5
    assert result.run_km_per_week == BEGINNER_RUN_KM_PER_WEEK


def test_older_than_sixteen_weeks_is_beginner():
    result = from_history([run(TODAY - dt.timedelta(weeks=17))], TODAY)
    assert result.source == "beginner_defaults" and result.longest_run_s == 0


def test_block_stops_at_a_gap_longer_than_two_weeks():
    old = [run(dt.date(2026, 6, 1), 20.0)]      # a big week in an earlier block
    block = recent_block(old + best_august_week(), TODAY)
    assert min(r.date for r in block) == dt.date(2026, 8, 9)
    assert from_history(old + best_august_week(), TODAY).best_week_km == 12.0


def test_propose_plan_records_history_baseline(athlete):
    from apps.planning.plan_store import propose_plan
    from tests.r6_helpers import make_activity

    today = athlete.local_today
    for days_ago in (44, 42, 40):
        make_activity(athlete, today - dt.timedelta(days=days_ago), run_s=1800, longest_s=900)
    plan = propose_plan(athlete, race_name="10K", race_date=today + dt.timedelta(weeks=10),
                        distance_km=10.0)
    summary = plan.summary
    assert summary["baseline_source"] == "history"
    assert summary["gap_days"] == 40
    assert summary["detraining_factor"] == 0.7
    assert summary["last_run_date"] == str(today - dt.timedelta(days=40))
    assert any("weeks ago" in w for w in summary["warnings"])
    assert summary["baseline"]["run_km_per_week"] >= BEGINNER_RUN_KM_PER_WEEK


def test_history_summary_in_chat_context(athlete):
    from apps.coaching.context import history_summary
    from tests.r6_helpers import make_activity

    today = athlete.local_today
    make_activity(athlete, today - dt.timedelta(days=30), longest_s=700)
    make_activity(athlete, today - dt.timedelta(days=10), longest_s=500)
    summary = history_summary(athlete)
    assert summary["runs"] == 2 and summary["gap_days"] == 10
    assert summary["longest_unbroken_run"]["date"] == today - dt.timedelta(days=30)
    assert sum(summary["run_km_by_month"].values()) == pytest.approx(summary["total_run_km"], abs=0.2)


def test_floor_is_mentioned_when_it_applies():
    runs = [run(dt.date(2026, 8, d), 2.0) for d in (17, 19)]
    result = from_history(runs, TODAY)
    assert result.run_km_per_week == BEGINNER_RUN_KM_PER_WEEK
    assert "beginner floor" in result.warning
