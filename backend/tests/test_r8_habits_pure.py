"""R8 §B, pure: streaks, since-quit maths, milestones and the impact analysis."""

import datetime as dt

import pytest

from analysis import habits as h

D = dt.date(2026, 10, 7)


def day(n):
    return D - dt.timedelta(days=n)


def test_streak_counts_only_from_tracking_start():
    totals = {day(10): 5, day(4): 2}
    assert h.streak(totals, D, day(12)) == {"current_days": 4, "best_days": 5}
    assert h.streak(totals, D, None) == {"current_days": 0, "best_days": 0}
    assert h.streak({}, D, day(2)) == {"current_days": 3, "best_days": 3}  # today counts
    assert h.streak({D: 1}, D, day(2))["current_days"] == 0


def test_since_quit():
    out = h.since_quit(day(10), D, baseline_per_day=10, price=18.0, smoked_since=4)
    assert out == {"days": 10, "cigarettes_avoided": 96.0, "money_saved": 1728.0}
    assert h.since_quit(None, D, 10, 18, 0) is None
    assert h.since_quit(day(1), D, 2, None, 10)["cigarettes_avoided"] == 0.0
    assert h.since_quit(day(3), D, None, 5, 0) == {"days": 3, "cigarettes_avoided": None,
                                                   "money_saved": None}


def test_milestones():
    quit_at = dt.datetime(2026, 10, 1, 0, 0, tzinfo=dt.timezone.utc)
    now = quit_at + dt.timedelta(days=3)
    ms = h.milestones(quit_at, now)
    assert len(ms) == 8 and all("typically" in m["label"] for m in ms)
    assert [m["reached"] for m in ms] == [True, True, True, True, False, False, False, False]
    assert ms[4]["at"] == (quit_at + dt.timedelta(weeks=2)).isoformat()
    assert h.milestones(None, now) == []


def test_series_and_trend():
    totals = h.daily_totals([(day(2), 1), (day(2), 2), (D, 1)])
    series = h.series(totals, day(2), D)
    assert series == [{"date": day(2).isoformat(), "count": 3.0},
                      {"date": day(1).isoformat(), "count": 0},
                      {"date": D.isoformat(), "count": 1.0}]
    falling = [{"count": c} for c in (10, 9, 8, 7, 6, 5, 4)]
    assert h.trend_per_week(falling) == -7.0
    assert h.trend_per_week(falling[:2]) is None


def build(n_with, n_without, with_hrv, without_hrv):
    days = [day(i) for i in range(1, n_with + n_without + 1)]
    totals = {d: 2 for d in days[:n_with]}
    mornings = {d + dt.timedelta(days=1): {"hrv": with_hrv if d in totals else without_hrv,
                                           "rhr": 60}
                for d in days}
    return totals, days, mornings


def row(rows, metric, dose=None):
    return next(r for r in rows if r["metric"] == metric and r["dose"] == dose)


def test_impact_needs_five_each_side():
    totals, days, mornings = build(4, 10, 40, 50)
    hrv = row(h.impact("alcohol", totals, days, mornings, {}), "hrv")
    assert hrv["enough_data"] is False and hrv["direction"] == "no_clear_difference"
    assert hrv["n_with"] == 4 and hrv["n_without"] == 10 and hrv["diff"] == -10


def test_impact_direction_uses_thresholds():
    totals, days, mornings = build(5, 5, 45, 50)      # -10 % HRV: worse
    hrv = row(h.impact("alcohol", totals, days, mornings, {}), "hrv")
    assert hrv["enough_data"] and hrv["direction"] == "worse"
    assert hrv["with_avg"] == 45 and hrv["without_avg"] == 50 and hrv["diff_pct"] == -10.0
    assert "lower on average (n=5 vs 5)" in hrv["label"] and "cause" not in hrv["label"]
    totals, days, mornings = build(5, 5, 48.5, 50)    # -3 %: inside the ±5 % band
    assert row(h.impact("alcohol", totals, days, mornings, {}), "hrv")["direction"] == \
        "no_clear_difference"
    totals, days, mornings = build(5, 5, 55, 50)
    assert row(h.impact("smoke", totals, days, mornings, {}), "hrv")["direction"] == "better"


@pytest.mark.parametrize("metric,with_v,without_v,expected", [
    ("rhr", 63, 60, "worse"), ("rhr", 61, 60, "no_clear_difference"),
    ("sleep_score", 70, 75, "worse"), ("body_battery", 60, 70, "worse"),
    ("stress", 40, 30, "worse"), ("stress", 31, 30, "no_clear_difference"),
])
def test_metric_thresholds(metric, with_v, without_v, expected):
    out = h.compare("alcohol", metric, [with_v] * 5, [without_v] * 5)
    assert out["direction"] == expected


def test_run_metrics_use_the_day_after():
    days = [day(i) for i in range(1, 11)]
    totals = {d: 1 for d in days[:5]}
    runs = {d + dt.timedelta(days=1): {"easy_hr": 150 if d in totals else 144,
                                        "efficiency": 1.0, "hr_drift": 5}
            for d in days}
    rows = h.impact("smoke", totals, days, {}, runs)
    assert row(rows, "easy_hr")["direction"] == "worse"
    assert row(rows, "efficiency")["direction"] == "no_clear_difference"
    assert "the day after" in row(rows, "easy_hr")["label"]


def test_alcohol_dose_rows_only_when_data_allows():
    days = [day(i) for i in range(1, 16)]
    totals = {d: (1 if i < 3 else 4) for i, d in enumerate(days[:6])}
    mornings = {d + dt.timedelta(days=1): {"hrv": 50} for d in days}
    rows = h.impact("alcohol", totals, days, mornings, {})
    assert {r["dose"] for r in rows if r["dose"]} == {"1-2", "3+"}
    few = {days[0]: 4}
    assert not [r for r in h.impact("alcohol", few, days, mornings, {}) if r["dose"]]


def test_weekly_rollup():
    start = dt.date(2026, 9, 28)                      # a Monday
    out = h.weekly(start, dt.date(2026, 10, 11), {"smoke": {start: 3}, "alcohol": {}},
                   {start: {"hrv": 40, "rhr": 60, "sleep_score": 80}},
                   {start: {"easy_pace": 600, "efficiency": 1.2}})
    assert len(out) == 2 and out[0]["cigarettes"] == 3 and out[0]["hrv_avg"] == 40
    assert set(out[0]) == {"week_start", "cigarettes", "drinks", "sugar", "hrv_avg",
                           "rhr_avg", "sleep_score_avg", "easy_pace_s_per_km", "efficiency"}
    assert out[1]["hrv_avg"] is None
