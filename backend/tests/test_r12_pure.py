"""R12 pure maths: periods and bucketing (analysis.buckets) and the wake planner /
watch-alarm check (analysis.wake). No database."""

import datetime as dt

from analysis import buckets as b
from analysis import compare
from analysis import wake as w

D = dt.date(2026, 10, 7)       # a Wednesday


# --- periods ---------------------------------------------------------------------------

def test_period_compare_window_and_dict():
    p = b.Period("custom", dt.date(2026, 9, 1), dt.date(2026, 9, 30), "day")
    assert p.days == 30
    assert p.compare_start == dt.date(2026, 8, 2) and p.compare_end == dt.date(2026, 8, 31)
    assert p.ranged() == {"range": "custom", "start": p.start, "end": p.end,
                          "period": {"start": p.start, "end": p.end, "days": 30,
                                     "compare_start": p.compare_start,
                                     "compare_end": p.compare_end, "freq": "day"}}


def test_default_freq_by_length():
    assert b.default_freq(7) == "day" and b.default_freq(92) == "day"
    assert b.default_freq(93) == "week" and b.default_freq(366) == "week"
    assert b.default_freq(367) == "month"


def test_bucket_start_and_next():
    assert b.bucket_start(D, "week") == dt.date(2026, 10, 5)
    assert b.bucket_start(D, "month") == dt.date(2026, 10, 1)
    assert b.bucket_start(D, "day") == D
    assert b.next_bucket(dt.date(2026, 12, 1), "month") == dt.date(2027, 1, 1)
    assert b.next_bucket(dt.date(2026, 1, 31).replace(day=1), "month") == dt.date(2026, 2, 1)
    assert b.next_bucket(dt.date(2026, 10, 5), "week") == dt.date(2026, 10, 12)


# --- bucketing -------------------------------------------------------------------------

def daily(n=14, start=dt.date(2026, 9, 28)):
    return [{"date": start + dt.timedelta(days=i), "value": float(i), "steps": 1000,
             "label": f"d{i}"} for i in range(n)]


def test_day_freq_is_identity():
    pts = daily()
    assert b.bucket(pts, "day") is pts
    assert b.bucket([], "week") == []


def test_week_mean_sum_last_and_text():
    out = b.bucket(daily(), "week", {"steps": "sum", "value": "mean"}, digits=1)
    assert [p["date"] for p in out] == [dt.date(2026, 9, 28), dt.date(2026, 10, 5)]
    assert out[0] == {"date": dt.date(2026, 9, 28), "value": 3.0, "steps": 7000, "label": "d6",
                      "n": 7}
    last = b.bucket(daily(), "week", "last")
    assert last[1]["value"] == 13.0


def test_month_buckets_and_iso_dates_stay_strings():
    pts = [{"date": (dt.date(2026, 8, 30) + dt.timedelta(days=i)).isoformat(), "count": 1}
           for i in range(5)]
    out = b.bucket(pts, "month", "sum")
    assert out == [{"date": "2026-08-01", "count": 2, "n": 2},
                   {"date": "2026-09-01", "count": 3, "n": 3}]


def test_nulls_ignored_and_all_null_stays_null():
    pts = [{"date": D, "v": None, "w": 2}, {"date": D + dt.timedelta(days=1), "v": None, "w": 4}]
    out = b.bucket(pts, "week", "mean", digits=0)
    assert out[0]["v"] is None and out[0]["w"] == 3 and out[0]["n"] == 2


def test_per_key_digits_and_wildcard():
    pts = [{"date": D, "a": 1, "b": 1.25}, {"date": D, "a": 2, "b": 1.5}]
    out = b.bucket(pts, "week", "mean", digits={"a": 0, "*": 2})
    assert out[0]["a"] == 2 and out[0]["b"] == 1.38


def test_bucket_map_and_shift_back():
    values = {dt.date(2026, 9, 28) + dt.timedelta(days=i): 1.0 for i in range(14)}
    weekly = b.bucket_map(values, "week", "sum")
    assert weekly == {dt.date(2026, 9, 28): 7.0, dt.date(2026, 10, 5): 7.0}
    assert b.bucket_map(values, "day") is values
    assert b.shift_back(weekly, "week") == {dt.date(2026, 9, 21): 7.0, dt.date(2026, 9, 28): 7.0}
    assert b.shift_back({dt.date(2026, 3, 1): 1.0}, "month") == {dt.date(2026, 2, 1): 1.0}
    assert b.shift_back({D: 1.0}, "day") == {D - dt.timedelta(days=1): 1.0}


def test_compare_wording_follows_bucket():
    xs = {dt.date(2026, 1, 5) + dt.timedelta(weeks=i): float(i) for i in range(10)}
    ys = {k: v * 2 for k, v in xs.items()}
    out = compare.compare(xs, ys, 1, "sleep", "HRV", freq="week", pre_shifted=True)
    assert out["n"] == 10 and out["sentence"].startswith("Weeks with more sleep")
    assert "the next week" in out["sentence"]
    few = compare.compare({D: 1.0}, {D: 2.0}, 0, "a", "b", freq="month")
    assert few["sentence"].startswith("Not enough months")


# --- wake planner ----------------------------------------------------------------------

def test_typical_run_time_uses_morning_runs():
    assert w.typical_run_time([6 * 60, 6 * 60 + 30, 18 * 60, 7 * 60]) == 6 * 60 + 30
    assert w.typical_run_time([18 * 60]) is None


def test_plan_sources():
    run = w.plan(run_planned=True, run_time=390, habit_wake=420, need_s=7 * 3600, lead_min=30)
    assert run["wake"] == 345 and run["wake_source"] == "run"
    assert w.clock(run["bedtime"]) == "22:30" and w.clock(run["reminder"]) == "22:00"
    assert run["need_source"] == "garmin"
    habit = w.plan(run_planned=False, run_time=390, habit_wake=420, need_s=None, lead_min=30)
    assert habit["wake_source"] == "habit" and habit["need_s"] == 8 * 3600
    assert w.clock(habit["bedtime"]) == "22:45" and habit["need_source"] == "default"
    default = w.plan(run_planned=True, run_time=None, habit_wake=None, need_s=None, lead_min=15)
    assert default["wake_source"] == "default" and default["wake"] == 420


def test_parse_alarm_shapes():
    a = w.parse_alarm({"alarmMode": "ON", "alarmTime": 360,
                       "alarmDays": ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]}, "FR265")
    assert a == {"time": "06:00", "days": [0, 1, 2, 3, 4], "once": False, "enabled": True,
                 "label": None, "device": "FR265"}
    once = w.parse_alarm({"alarmMode": "OFF", "alarmTime": 450, "alarmDays": ["ONCE"],
                          "alarmLabel": "Race"})
    assert once["once"] and not once["enabled"] and once["label"] == "Race" and once["days"] == []
    assert w.parse_alarm({"alarmTime": "05:45", "alarmDays": "DAILY"})["days"] == list(range(7))
    assert w.parse_alarm({"alarmTime": 21600, "alarmDays": ["SU"]})["time"] == "06:00"   # seconds
    assert w.parse_alarm({"alarmTime": None}) is None and w.parse_alarm("x") is None
    assert w.parse_alarm({"alarmTime": 2000}) is None           # not a clock time


def test_summary_and_alarms_on():
    alarms = [{"time": "06:00", "days": [0, 1, 2, 3, 4], "once": False, "enabled": True},
              {"time": "08:00", "days": [5], "once": False, "enabled": True},
              {"time": "05:00", "days": [6], "once": False, "enabled": False},
              {"time": "07:30", "days": [], "once": True, "enabled": True}]
    assert w.summary(alarms) == "06:00 Mon–Fri · 07:30 once · 08:00 Sat"
    assert w.alarms_on(alarms, 0) == [360, 450] and w.alarms_on(alarms, 6) == [450]
    assert w.alarms_on(alarms, 5, include_once=False) == [480]
    assert w.summary([]) is None
    assert w._days_text([0, 2, 3, 4]) == "Mon, Wed–Fri"
    assert w._days_text([0, 1]) == "Mon, Tue"


def test_flags():
    kw = dict(run_planned=True, run_time=390, watch_available=True)
    assert w.flags(**kw, watch_times=[420], my_alarm=None)[0]["text"] == \
        "Your run is at 06:30 but your watch alarm is 07:00."
    assert w.flags(**kw, watch_times=[330], my_alarm=None) == []
    assert [f["kind"] for f in w.flags(**kw, watch_times=[], my_alarm=None)] == ["no_alarm_for_run"]
    assert [f["kind"] for f in w.flags(**kw, watch_times=[], my_alarm=400)] == \
        ["no_watch_alarm_for_run", "my_alarm_after_run"]
    assert w.flags(run_planned=False, run_time=390, watch_available=True, watch_times=[],
                   my_alarm=None) == []
    assert w.flags(run_planned=True, run_time=390, watch_available=False, watch_times=[],
                   my_alarm=300) == []


def test_android_intent_and_sentence():
    url = w.android_intent(345)
    assert url.startswith("intent:#Intent;action=android.intent.action.SET_ALARM;")
    assert "alarm.HOUR=5;" in url and "alarm.MINUTES=45;" in url and url.endswith(";end")
    assert "06:30 run" in w.sentence("run", 345, 1350, 390)
    assert w.sentence("default", 420, 1365, None).startswith("Aim for bed by 22:45")
