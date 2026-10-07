"""R10 pure maths: LT zones (safety rule), sleep, form, records, training status, gear,
body, compare, lung recovery, weekly report, achievements and the readiness forecast."""

import datetime as dt

import pytest

from analysis import achievements, body, compare, forecast, form, gear, lung, records, sleep
from analysis import training_status, weekly_report, zones

D = dt.date(2026, 10, 7)


def day(n):
    return D - dt.timedelta(days=n)


# --- zones from the lactate threshold ----------------------------------------------

def test_lt_zones_never_make_easy_zones_harder():
    reserve = zones.build(60, 190)                  # Z2 = 138–151 by heart-rate reserve
    lt = zones.from_lactate_threshold(175, max_hr=190, resting_hr=60, reserve=reserve,
                                      hr_ceiling=155)
    assert lt.source == "lactate_threshold" and lt.lt_hr == 175
    z1, z2, z3 = lt.band("Z1"), lt.band("Z2"), lt.band("Z3")
    assert z2.high <= reserve.band("Z2").high and z2.low <= reserve.band("Z2").low
    assert z1.high <= reserve.band("Z1").high
    assert lt.capped is True
    assert z3.low == z2.high                        # contiguous after the cap
    assert lt.band("Z4").high == 175 and lt.band("Z5").high == 190


def test_lt_zones_can_make_easy_zones_easier():
    reserve = zones.build(50, 200)                  # Z2 high = 155
    lt = zones.from_lactate_threshold(160, max_hr=200, resting_hr=50, reserve=reserve)
    assert lt.band("Z2").high == round(160 * 0.89) < reserve.band("Z2").high
    assert lt.capped is False


def test_lt_zones_capped_by_hr_ceiling_without_reserve():
    lt = zones.from_lactate_threshold(180, hr_ceiling=150)
    assert lt.band("Z2").high == 150 and lt.band("Z1").high <= 150
    assert lt.max_hr == round(180 * 1.06) and lt.max_source == "lactate_threshold_estimate"


@pytest.mark.parametrize("value,max_hr", [(None, None), (100, None), (230, None), (190, 185)])
def test_implausible_lt_gives_no_zones(value, max_hr):
    assert zones.from_lactate_threshold(value, max_hr=max_hr) is None


def test_lt_zones_are_ordered():
    reserve = zones.build(70, 180)
    lt = zones.from_lactate_threshold(168, max_hr=180, resting_hr=70, reserve=reserve,
                                      hr_ceiling=140)
    bounds = [(z.low, z.high) for z in lt.zones]
    for low, high in bounds:
        assert low <= high
    for (_, high), (low, _) in zip(bounds, bounds[1:]):
        assert low >= high - 0 or low == high


# --- sleep -----------------------------------------------------------------------------

def test_minutes_after_noon_spans_midnight():
    assert sleep.minutes_after_noon(dt.datetime(2026, 1, 1, 22, 30)) == 630
    assert sleep.minutes_after_noon(dt.datetime(2026, 1, 1, 1, 0)) == 780
    assert sleep.clock(630, after_noon=True) == "22:30"


def test_regularity_needs_three_nights_and_compares():
    beds = [dt.datetime(2026, 1, i, 23, 0) for i in range(1, 6)]
    wobbly = [dt.datetime(2026, 1, 1, 22, 0), dt.datetime(2026, 1, 2, 0, 30),
              dt.datetime(2026, 1, 3, 23, 0), dt.datetime(2026, 1, 4, 1, 30)]
    out = sleep.regularity(beds, wobbly)
    assert out["bedtime_sd_min"] == 0 and out["previous_bedtime_sd_min"] > 30
    assert out["better"] is True and out["n"] == 5
    assert sleep.regularity(beds[:2], [])["bedtime_sd_min"] is None


def test_sleep_debt_last_seven_signed_sum_floored():
    nights = [(7 * 3600, 8 * 3600)] * 9            # 1 h short each
    out = sleep.debt(nights)
    assert out["debt_s"] == 7 * 3600 and out["nights"] == 7 and out["short_nights"] == 7
    assert out["short_by_s"] == 3600 and out["need_s"] == 8 * 3600
    surplus = sleep.debt([(9 * 3600, 8 * 3600)] * 3)
    assert surplus["debt_s"] == 0 and surplus["short_nights"] == 0
    assert sleep.debt([(None, 8 * 3600)])["debt_s"] is None


def test_tonight_bedtime_from_median_wake_and_need():
    wakes = [dt.datetime(2026, 1, i, 6, 30) for i in range(1, 4)]
    out = sleep.tonight(wakes, 7 * 3600 + 1800)
    assert out == {"need_s": 27000, "wake_time": "06:30", "bedtime": "22:45"}
    assert sleep.tonight([], None)["bedtime"] is None


def test_sleep_vs_runs():
    pairs = [(5.5, 152), (5.0, 150), (5.8, 154), (7.5, 146), (8.0, 145), (7.2, 147), (6.5, 160)]
    out = sleep.sleep_vs_runs(pairs)
    assert out["enough_data"] and out["short"]["n"] == 3 and out["long"]["n"] == 3
    assert out["diff_bpm"] == 6.0 and "6 bpm lower" in out["sentence"]
    assert sleep.sleep_vs_runs(pairs[:4])["sentence"] is None


# --- form / records / status / gear / body ---------------------------------------------

def test_form_rows_compare_last_five_with_five_before():
    runs = [{"date": day(20 - i).isoformat(), "cadence_spm": 150 + i, "ground_contact_ms": 300 - i,
             "vertical_oscillation_cm": None, "stride_length_m": 0.9} for i in range(10)]
    rows = {r["key"]: r for r in form.metric_rows(runs)}
    assert rows["cadence"]["current"] == 157 and rows["cadence"]["previous"] == 152
    assert rows["cadence"]["better"] is True            # closer to 168
    assert rows["ground_contact"]["better"] is True     # lower
    assert rows["vertical_oscillation"]["current"] is None and rows["vertical_oscillation"]["n"] == 0
    assert rows["stride_length"]["better"] is None
    assert form.has_dynamics(runs) and not form.has_dynamics([{"cadence_spm": 150}])


GARMIN_PRS = [
    {"typeId": 1, "value": 550.97, "activityId": 24004857607,
     "activityStartDateTimeLocalFormatted": "2026-08-17T06:14:00.0"},
    {"typeId": 7, "value": 2650.9, "activityId": 24004857607,
     "activityStartDateTimeLocalFormatted": "2026-08-17T06:14:00.0"},
    {"typeId": 8, "value": 2987.9, "activityId": 1},          # cycling: ignored
    {"typeId": 12, "value": 28163.0},                          # steps: ignored
    {"typeId": 3, "value": None},                              # broken: skipped
]


def test_parse_garmin_prs_keeps_running_types():
    out = records.parse_garmin(GARMIN_PRS)
    assert [r["key"] for r in out] == ["1k", "longest_run"]
    assert out[0]["date"] == dt.date(2026, 8, 17) and out[0]["garmin_activity_id"] == 24004857607
    assert records.parse_garmin(None) == [] and records.parse_garmin({"x": 1}) == []


def test_record_display_and_new_flag():
    assert records.display(550.97, "s") == "9:11"
    assert records.display(3735, "s") == "1:02:15"
    assert records.display(10230, "m") == "10.2 km"
    assert records.is_new(D - dt.timedelta(days=13), D) and not records.is_new(day(14), D)


def test_computed_bests():
    runs = [{"id": 1, "date": "2026-09-01", "fastest_1k_s": 400, "total_km": 5.2, "longest_run_s": 900},
            {"id": 2, "date": "2026-09-08", "fastest_1k_s": 380, "total_km": 4.0, "longest_run_s": None}]
    out = {r["key"]: r for r in records.computed(runs)}
    assert out["fastest_1k"]["activity_id"] == 2 and out["fastest_1k"]["value"] == 380
    assert out["longest_distance"]["value"] == 5200 and out["longest_continuous"]["value"] == 900


def test_training_status_helpers():
    assert training_status.status_key("Productive") == "productive"
    assert training_status.status_key("No Status") == "no_status"
    assert training_status.status_key("Detraining") == "detraining"
    assert training_status.status_key("") is None and training_status.status_key("Odd") is None
    focus = training_status.load_focus({
        "monthlyLoadAerobicLow": 410.0, "monthlyLoadAerobicLowTargetMin": 95,
        "monthlyLoadAerobicLowTargetMax": 260, "monthlyLoadAerobicHigh": 120.0,
        "monthlyLoadAerobicHighTargetMin": 205, "monthlyLoadAerobicHighTargetMax": 369,
        "monthlyLoadAnaerobic": 10.0, "trainingBalanceFeedbackPhrase": "BELOW_TARGETS"})
    assert focus["feedback"] == "Below targets"
    assert [i["state"] for i in focus["items"]] == ["above", "below", None]
    assert training_status.load_focus({}) is None


def test_gear_status():
    assert gear.status(650, 700) == {"remaining_km": 50.0, "replace_soon": True,
                                     "replace_due": False}
    assert gear.status(800, None)["replace_due"] is True


def test_body_merge_and_trend():
    garmin = [{"date": day(14), "weight_kg": 76.0, "body_fat_pct": 20.0}]
    manual = [{"date": day(14), "weight_kg": 77.0}, {"date": day(7), "weight_kg": 75.5},
              {"date": day(0), "weight_kg": 75.0}]
    merged = body.merge(garmin, manual)
    assert [p["source"] for p in merged] == ["garmin", "manual", "manual"]
    assert body.change(merged, "weight_kg") == -1.0 and body.change(merged, "body_fat_pct") is None
    assert body.trend(merged) == -0.5


# --- compare ---------------------------------------------------------------------------

def test_compare_pairs_with_lag_and_reports_negative_link():
    xs = {day(i): float(10 - i) for i in range(10)}
    ys = {day(i) + dt.timedelta(days=1): float(i) for i in range(10)}
    out = compare.compare(xs, ys, 1, "sleep", "HR at easy pace")
    assert out["n"] == 10 and out["rho"] == -1.0 and out["strength"] == "strong"
    assert out["direction"] == "negative" and out["enough_data"]
    assert "followed by lower HR at easy pace the next day" in out["sentence"]
    assert "ρ = −1.00, n = 10" in out["sentence"] and out["trend"]["slope"] == -1.0
    assert compare.compare(xs, ys, 0, "a", "b")["n"] == 9          # overlap without the lag


def test_compare_needs_eight_pairs_and_handles_constant():
    xs = {day(i): float(i) for i in range(5)}
    out = compare.compare(xs, dict(xs), 0, "a", "b")
    assert not out["enough_data"] and out["strength"] is None and "n = 5" in out["sentence"]
    flat = {day(i): 1.0 for i in range(10)}
    out = compare.compare(flat, {day(i): float(i) for i in range(10)}, 0, "a", "b")
    assert out["rho"] is None and "didn't change" in out["sentence"]


def test_compare_no_clear_link():
    xs = {day(i): float(v) for i, v in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])}
    ys = {day(i): float(v) for i, v in enumerate([8, 5, 1, 4, 9, 10, 2, 3, 7, 6])}
    out = compare.compare(xs, ys, 0, "a", "b")
    assert out["strength"] == "none" and out["direction"] is None
    assert out["sentence"].startswith("No clear link")


# --- lung -------------------------------------------------------------------------------

def test_lung_metric_before_vs_now():
    quit_date = day(30)
    values = {quit_date - dt.timedelta(days=i): 16.0 for i in range(1, 15)}
    values.update({day(i): 15.0 for i in range(14)})
    out = lung.metric("sleep_breathing_rate", values, quit_date, D)
    assert out["before"] == 16.0 and out["now"] == 15.0 and out["change"] == -1.0
    assert out["better"] is True and out["enough_data"] and out["before_n"] == 14
    assert "can't" not in out["sentence"] and "move it too" in out["sentence"]
    assert "caused" not in out["sentence"]


def test_lung_metric_not_enough_data():
    out = lung.metric("resting_hr", {day(1): 60.0}, day(5), D)
    assert not out["enough_data"] and out["better"] is None
    assert out["sentence"].startswith("Not enough")


# --- weekly report ----------------------------------------------------------------------

RUNS = {"done": 3, "planned": 3, "planned_done": 3, "km": 12.0, "run_km": 10.0,
        "time_s": 5400, "previous_done": 2, "previous_km": 8.0}


def test_weekly_wellness_rows():
    rows = {r["metric"]: r for r in weekly_report.wellness_rows(
        {"hrv": [50, 52, 54], "rhr": [56, 56], "sleep": [7.5, 7.0], "sleep_score": [None]},
        {"hrv": [44, 46], "rhr": [59, 59], "sleep": [6.0, 6.5], "sleep_score": [80, 82]})}
    assert rows["hrv"]["better"] is True and rows["hrv"]["delta"] == 7
    assert rows["rhr"]["better"] is True and rows["sleep"]["this_week"] == 7.2
    assert rows["sleep_score"]["this_week"] is None and rows["sleep_score"]["better"] is None


def test_weekly_bullets_and_goal():
    habits = weekly_report.habit_rows({"alcohol": 5, "private": 3}, {"alcohol": 2, "private": 1},
                                      ["alcohol", "private"])
    good, bad, goal = weekly_report.bullets(runs=RUNS, wellness=[], habits=habits, prs=[],
                                            zones={"Z1": 600, "Z2": 3000, "Z3": 300})
    assert "3 of 3 planned runs done" in good and any("easy zones" in g for g in good)
    assert any("drinks" in b.lower() for b in bad) and any("Private" in b for b in bad)
    assert "drinks" in goal and "Private" not in goal
    _, bad_ai, goal_ai = weekly_report.bullets(runs=RUNS, wellness=[], habits=habits, prs=[],
                                               zones={}, ai_safe=True)
    assert not any("Private" in b for b in bad_ai) and "Private" not in goal_ai


def test_weekly_goal_when_runs_missed_or_none():
    missed = {**RUNS, "planned_done": 1}
    assert "planned runs" in weekly_report.goal(missed, [], [], {})
    none = {**RUNS, "done": 0, "planned": 0, "planned_done": 0}
    good, bad, goal = weekly_report.bullets(runs=none, wellness=[], habits=[], prs=[], zones={})
    assert bad[0] == "No runs logged last week" and "two easy runs" in goal


# --- achievements -----------------------------------------------------------------------

def test_smoke_free_counts_only_finished_days():
    totals = {day(10): 2.0}
    reached, current = achievements.smoke_free(totals, day(10), D)
    assert current == 9 and reached[1] == day(9) and reached[7] == day(3) and 14 not in reached


def test_consistent_weeks_and_run_streak():
    monday = D - dt.timedelta(days=D.weekday())
    dates = []
    for w in range(1, 5):
        start = monday - dt.timedelta(weeks=w)
        dates += [start, start + dt.timedelta(days=2)]
    reached, current = achievements.consistent_weeks(dates, D)
    assert reached[2] == monday - dt.timedelta(weeks=3) + dt.timedelta(days=2)
    assert 4 in reached and current == 4
    streak_dates = [day(3), day(2), day(1)]
    reached, current = achievements.run_streak(streak_dates, D)
    assert reached[3] == day(1) and current == 3       # alive until today ends


def test_sleep_streak_first_5k_and_records():
    nights = {day(i): 7 * 3600 + 60 for i in range(5)}
    nights[day(5)] = 5 * 3600
    reached, current = achievements.sleep_streak(nights)
    assert reached[3] == day(2) and current == 5
    assert achievements.first_5k([(day(3), 5100), (day(1), 6000)])[0] == {1: day(3)}
    assert achievements.records([day(5), day(1)])[0] == {1: day(5)}


def test_badges_progress_and_hidden_groups():
    out = achievements.badges({"distance": ({}, 0), "sleep": ({3: day(1)}, 5)})
    keys = {b["key"]: b for b in out}
    assert "first_5k" in keys and "smoke_free_1" not in keys
    assert keys["sleep_7h_3"]["earned_on"] == day(1)
    assert keys["sleep_7h_7"]["progress"] == {"current": 5, "target": 7}


# --- forecast -------------------------------------------------------------------------

def test_forecast_estimate_factors_and_levers():
    inputs = forecast.ForecastInputs(
        today_score=70, recent_scores=[70, 72, 68], today_load=60, chronic_daily_load=30,
        hrv_recent=[40, 41, 39], hrv_baseline_low=45, hrv_baseline_high=60,
        sleep_debt_s=4 * 3600, need_s=8 * 3600, bedtime_target="22:45", alcohol_today=2,
        drinks_regularly=True)
    out = forecast.forecast(inputs)
    keys = [f["key"] for f in out["factors"]]
    assert keys == ["load", "hrv_trend", "sleep_debt", "alcohol"]
    assert out["estimate"] == round(70 - 8 - 6 - 4 - 5)
    assert [l["key"] for l in out["levers"]] == ["bedtime", "no_alcohol"]
    assert out["best_case"] == out["estimate"] + 6 + 5
    assert "Asleep by 10:45 pm and no more alcohol tonight could make it" in out["sentence"]
    assert out["low"] == out["estimate"] - 8 and "estimate" in out["note"].lower()


def test_forecast_without_data_is_null():
    out = forecast.forecast(forecast.ForecastInputs())
    assert out["estimate"] is None and out["label"] == "Unknown" and out["levers"] == []


def test_forecast_rest_day_raises_it():
    out = forecast.forecast(forecast.ForecastInputs(today_score=60, today_load=0,
                                                     chronic_daily_load=20))
    # No recent scores: today's 60 drifts towards the neutral 70, plus the rest day.
    assert out["estimate"] == round(0.6 * 60 + 0.4 * 70 + 4) and out["levers"] == []
