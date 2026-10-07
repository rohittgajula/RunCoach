"""R11 pure maths: analysis.day (the day between runs), analysis.day_trends and
analysis.route (run maps). No database."""

import datetime as dt
import math

import pytest

from analysis import day as d
from analysis import day_trends as t
from analysis import route as r

D = dt.date(2026, 10, 6)


def steps_day(pattern: dict[int, tuple[int, str | None]] | None = None, default=(0, "sedentary")):
    """96 buckets; pattern maps bucket start minute -> (steps, level)."""
    pattern = pattern or {}
    return [[m, *pattern.get(m, default)] for m in range(0, 1440, 15)]


# --- helpers -----------------------------------------------------------------------------

def test_hhmm_clamps_and_formats():
    assert d.hhmm(0) == "00:00" and d.hhmm(615) == "10:15"
    assert d.hhmm(1440) == "23:59" and d.hhmm(None) is None


def test_value_at_and_before():
    pts = [[60, 10], [120, 20], [300, 50]]
    assert d.value_at(pts, 125) == 20 and d.value_at(pts, 200, 30) is None
    assert d.value_before(pts, 200) == 20          # step function for change points
    assert d.value_before(pts, 30) == 10 and d.value_before(pts, 0, 45) is None


# --- awake window ------------------------------------------------------------------------

def test_awake_from_sleep_data():
    a = d.awake_window(7 * 60, 23 * 60 + 30, [])
    assert (a.start, a.end, a.source) == (420, 1410, "sleep")


def test_awake_bed_after_midnight_runs_to_end_of_day():
    assert d.awake_window(400, 1440 + 60, []).end == 1440


def test_awake_from_sleeping_buckets_then_default():
    pattern = {m: (0, "sleeping") for m in range(0, 405, 15)}
    pattern.update({m: (0, "sleeping") for m in range(1350, 1440, 15)})
    a = d.awake_window(None, None, steps_day(pattern))
    assert (a.start, a.end, a.source) == (405, 1350, "steps")
    assert d.awake_window(None, None, []).as_dict() == {"start": "07:00", "end": "23:00",
                                                         "source": "default"}


# --- steps -------------------------------------------------------------------------------

def test_adaptive_goal_median_times_105_clamped():
    assert d.adaptive_goal([8000] * 10) == 8400
    assert d.adaptive_goal([2000] * 10) == 6000            # clamp low
    assert d.adaptive_goal([20000] * 10) == 15000          # clamp high
    assert d.adaptive_goal([8000] * 6) is None             # needs 7 days
    assert d.adaptive_goal([None, 0] + [9000] * 7) == 9400   # empty days ignored, /100


def test_choose_goal_prefers_garmin():
    assert d.choose_goal(7500, 8400) == (7500, "garmin")
    assert d.choose_goal(None, 8400) == (8400, "adaptive")
    assert d.choose_goal(None, None) == (None, None)


def test_goal_streak_and_unfinished_today():
    days = {D - dt.timedelta(days=i): (9000, 8000) for i in range(1, 4)}
    days[D] = (3000, 8000)
    assert d.goal_streak(days, D) == 0
    assert d.goal_streak(days, D, allow_unmet_end=True) == 3
    days[D] = (8000, 8000)
    assert d.goal_streak(days, D) == 4


def test_steps_trend_and_run_vs_rest():
    by_day = {D - dt.timedelta(days=i): (10000 if i < 7 else 5000) for i in range(14)}
    assert d.steps_trend(by_day, D) == {"last7_avg": 10000, "prev7_avg": 5000, "change_pct": 100}
    out = d.run_vs_rest(by_day, {D, D - dt.timedelta(days=8)})
    assert out == {"run_days_avg": 7500, "rest_days_avg": 7500, "run_days_n": 2, "rest_days_n": 12}


def test_hourly_and_active_hours():
    steps = steps_day({600: (500, "active"), 615: (700, "active"), 840: (1200, "highly_active")})
    hourly = d.hourly_steps(steps)
    assert len(hourly) == 24 and hourly[10]["steps"] == 1200 and hourly[14]["steps"] == 1200
    most, least = d.active_hours(hourly, d.Awake(420, 1380, "sleep"))
    assert most == {"hour": 10, "label": "10:00–11:00", "steps": 1200}   # tie → earlier hour
    assert least["hour"] == 7 and least["steps"] == 0
    assert d.active_hours(d.hourly_steps(steps_day()), d.Awake(420, 1380, "x")) == (None, None)


# --- active vs sedentary -----------------------------------------------------------------

def test_activity_minutes_garmin_first_then_buckets():
    garmin = d.activity_minutes([], {"sedentary_s": 36000, "active_s": 3600, "highly_active_s": 600,
                                     "sleeping_s": 28800})
    assert garmin == {"sedentary_min": 600, "active_min": 60, "intense_min": 10,
                      "sleeping_min": 480, "source": "garmin"}
    steps = steps_day({0: (0, "sleeping"), 600: (300, "active"), 615: (1500, "highly_active")})
    buckets = d.activity_minutes(steps)
    assert buckets["source"] == "steps" and buckets["active_min"] == 15
    assert buckets["intense_min"] == 15 and buckets["sleeping_min"] == 15
    assert buckets["sedentary_min"] == 1440 - 45
    assert d.activity_minutes([])["source"] is None


def test_longest_sedentary_and_trailing_stretch():
    pattern = {m: (200, "active") for m in range(0, 1440, 15) if m not in range(540, 690, 15)}
    steps = steps_day(pattern)      # 09:00–11:30 sitting
    long = d.longest_sedentary(steps, d.Awake(420, 1380, "sleep"))
    assert long == {"minutes": 150, "start": "09:00", "end": "11:30"}
    upto = [row for row in steps if row[0] < 660]   # data ends 11:00 mid-stretch
    assert d.trailing_sedentary(upto) == (540, 120)
    assert d.trailing_sedentary(steps) is None       # latest bucket is active


def test_sedentary_ignores_sleeping_buckets_and_night():
    steps = steps_day({m: (0, "sleeping") for m in range(0, 420, 15)})
    long = d.longest_sedentary(steps, d.Awake(420, 1380, "sleep"))
    assert long["start"] == "07:00" and long["minutes"] == 1380 - 420


def test_naps_need_30_minutes_while_awake():
    steps = steps_day({840: (0, "sleeping"), 855: (0, "sleeping"), 1000: (0, "sleeping")})
    assert d.naps(steps, d.Awake(420, 1380, "sleep")) == [(840, 870)]


# --- stress ------------------------------------------------------------------------------

def stress_series(values: dict[tuple[int, int], int], default=20):
    """3-minute samples; values maps (start, end) minutes to a level."""
    out = []
    for m in range(0, 1440, 3):
        level = default
        for (a, b), v in values.items():
            if a <= m < b:
                level = v
        out.append([m, level])
    return out


def test_stress_bands_use_garmin_ranges():
    pts = [[0, 0], [3, 25], [6, 26], [9, 50], [12, 51], [15, 75], [18, 76], [21, 100]]
    out = d.stress_bands(pts)
    assert out == {"rest_min": 6, "low_min": 6, "medium_min": 6, "high_min": 6,
                   "stressful_min": 12}


def test_stress_peak_window():
    pts = stress_series({(660, 720): 80})
    assert d.stress_peak(pts) == {"start": "11:00", "end": "12:00", "avg": 80}
    assert d.stress_peak([]) is None


def test_stress_stretches_bridge_small_gaps_and_need_30_min():
    pts = stress_series({(600, 640): 70, (640, 643): 40, (643, 660): 80, (900, 921): 90})
    stretches = d.stress_stretches(pts)
    assert len(stretches) == 1      # the 21-min spell at 15:00 is too short
    s = stretches[0]
    assert (s["start"], s["end"], s["peak"]) == ("10:00", "11:00", 80)
    assert s["minutes"] == 60
    # A longer dip splits the spell.
    split = d.stress_stretches(stress_series({(600, 630): 70, (630, 645): 30, (645, 690): 70}))
    assert [x["minutes"] for x in split] == [30, 45]


def test_trailing_stress():
    pts = [p for p in stress_series({(600, 660): 60}) if p[0] < 660]
    assert d.trailing_stress(pts, 51) == (600, 60)
    assert d.trailing_stress(pts, 61) is None
    assert d.trailing_stress(stress_series({}), 51) is None


# --- body battery ------------------------------------------------------------------------

def test_bb_legs_ignore_jitter():
    pts = [[0, 20], [60, 40], [90, 39], [120, 60], [600, 30], [660, 32], [900, 10]]
    legs = d.bb_legs(pts)
    assert [(a[1], b[1]) for a, b in legs] == [(20, 60), (60, 10)]


def test_bb_events_labelled_by_overlap():
    pts = [[0, 20], [420, 80], [600, 75], [720, 55], [900, 56], [960, 66], [1380, 30]]
    events = d.bb_events(pts, {"sleep": [(0, 420)], "run": [(600, 720)], "nap": [(840, 960)],
                               "stress": []})
    by = [(e["type"], e["cause"], e["amount"]) for e in events]
    assert ("charge", "sleep", 60) in by
    assert ("drain", "run", 25) in by        # 80 → 55 over 07:00–12:00, the run covers 2 h of 5
    assert ("charge", "nap", 11) in by       # 12:00–16:00, the nap covers 2 h of 4
    assert ("drain", "activity", 36) in by
    assert events == sorted(events, key=lambda e: e["start"])


def test_bb_summary_values_at_wake_and_bed():
    pts = [[0, 20], [420, 80], [1200, 40], [1380, 35]]
    awake = d.Awake(420, 1380, "sleep")
    out = d.bb_summary(pts, awake, 420, 1300)
    assert out["at_wake"] == 80 and out["at_bedtime"] == 40
    assert out["charged"] == 60 and out["drained"] == 45
    assert (out["high"], out["low"], out["start"], out["end"]) == (80, 20, 20, 35)
    after = d.bb_summary(pts, awake, 420, 1440 + 90, next_points=[[0, 33], [60, 30]])
    assert after["at_bedtime"] == 30
    garmin = d.bb_summary(pts, awake, 420, None, summary={"bb_charged": 70, "bb_drained": 50})
    assert garmin["charged"] == 70 and garmin["at_bedtime"] is None
    assert d.bb_summary([], awake, None, None, summary={"bb_at_wake": 66})["at_wake"] == 66


# --- heart rate --------------------------------------------------------------------------

def test_awake_hr_excludes_night_and_runs():
    pts = [[m, 50] for m in range(0, 420, 2)] + [[m, 70] for m in range(420, 600, 2)] + \
          [[m, 160] for m in range(600, 660, 2)] + [[m, 80] for m in range(660, 1380, 2)]
    out = d.awake_hr(pts, d.Awake(420, 1380, "sleep"), [(600, 660)])
    assert out["awake_min"] == 70 and out["awake_max"] == 80
    assert 70 < out["awake_avg"] < 80


def test_week_change():
    by_day = {D - dt.timedelta(days=i): (70 if i < 7 else 74) for i in range(14)}
    assert d.week_change(by_day, D) == {"this_week_avg": 70, "prev_week_avg": 74, "change": -4}


# --- score card --------------------------------------------------------------------------

def card(**kw):
    base = dict(steps=9000, goal=8000, stress_avg=22, stressful_min=0, stretches=[],
                longest_sit=None, bb_start=30, bb_end=60, bb_at_bed=40, ran=True, peak=None,
                is_today=False)
    return d.score_card(**{**base, **kw})


def test_score_card_good_day():
    c = card()
    assert c["status"] == "good" and len(c["bullets"]) == 3 and 1 <= len(c["tips"]) <= 2
    assert c["sentence"] == "This day: a run, the step goal met and calm stress levels."


def test_score_card_tips_for_a_rough_day():
    c = card(steps=2000, stress_avg=60, stressful_min=180, ran=False, bb_end=12, bb_at_bed=12,
             stretches=[{"start": "10:00"}], peak={"start": "11:00"},
             longest_sit={"minutes": 150, "start": "13:00", "end": "15:30"})
    assert c["status"] == "low"
    assert len(c["tips"]) == 2
    assert "sitting" in c["tips"][0] and "11:00" in c["tips"][1]
    assert all("run" not in tip.lower() for tip in c["tips"])     # safety: never more training


def test_score_card_no_data():
    c = card(steps=None, stress_avg=None, bb_start=None, bb_end=None)
    assert c == {"status": "no_data", "sentence": "No daytime data from Garmin for this day yet.",
                 "bullets": [], "tips": []}


def test_score_card_today_wording():
    assert card(is_today=True)["sentence"].startswith("Today so far:")


# --- the whole day -----------------------------------------------------------------------

def full_input(**kw):
    steps = steps_day({m: (0, "sleeping") for m in range(0, 420, 15)} |
                      {m: (300, "active") for m in range(720, 780, 15)} |
                      {m: (1500, "highly_active") for m in range(390 + 30, 480, 15)})
    hr = [[m, 55 if m < 420 else 75] for m in range(0, 1440, 2)]
    stress = stress_series({(0, 420): 10, (600, 660): 70})
    bb = [[0, 30], [420, 85], [900, 50], [1380, 35]]
    history = {D - dt.timedelta(days=i): 8000 for i in range(1, 29)}
    base = dict(date=D, hr=hr, stress=stress, body_battery=bb, steps=steps, wake_min=420,
                bed_min=1380, summary={"resting_hr": 52},
                runs=[{"start": 420, "end": 465, "activity_id": 9, "label": "Run · 5.0 km"}],
                habits=[{"minute": 1260, "kind": "alcohol", "label": "Drink"}],
                step_history=history, goal_history={}, run_dates={D},
                awake_hr_history={})
    return d.DayInput(**{**base, **kw})


def test_analyse_shapes_every_block():
    out = d.analyse(full_input())
    assert set(out) == {"data_as_of", "awake", "timeline", "steps", "activity", "stress",
                        "body_battery", "heart_rate", "score_card", "now"}
    assert out["awake"] == {"start": "07:00", "end": "23:00", "source": "sleep"}
    assert out["steps"]["goal_source"] == "adaptive" and out["steps"]["goal"] == 8400
    assert out["steps"]["total"] == sum(row[1] for row in full_input().steps)
    assert len(out["steps"]["hourly"]) == 24
    assert out["stress"]["peak"]["start"] == "10:00" and out["stress"]["stretches"]
    assert "_start" not in out["stress"]["stretches"][0]
    types = [m["type"] for m in out["timeline"]["markers"]]
    assert {"sleep", "run", "habit"} <= set(types)
    assert out["heart_rate"]["resting"] == 52 and out["heart_rate"]["awake_avg"] == 75
    assert out["now"]["stress"] is None            # not today
    assert out["data_as_of"] == "23:59"


def test_analyse_today_has_now_values():
    out = d.analyse(full_input(is_today=True))
    assert out["now"]["body_battery"] == 35 and out["now"]["stress"] == 20
    assert out["now"]["stress_at"] == "23:57"


def test_analyse_empty_day():
    out = d.analyse(d.DayInput(date=D))
    assert out["score_card"]["status"] == "no_data"
    assert out["steps"]["total"] is None and out["timeline"]["markers"] == []
    assert out["data_as_of"] is None


def test_aggregates_for_storage():
    agg = d.aggregates(full_input())
    assert agg["steps_total"] > 0 and agg["stress_avg"] is not None
    assert agg["stressful_min"] == 60 and agg["stress_high_min"] == 0
    assert agg["awake_hr_avg"] == 75 and agg["bb_at_bedtime"] == 35 and agg["bb_at_wake"] == 85
    empty = d.aggregates(d.DayInput(date=D, summary={"stress_avg": 33}))
    assert empty["stress_avg"] == 33 and empty["stress_high_min"] is None


# --- trends ------------------------------------------------------------------------------

def rows(n=28, **kw):
    out = []
    for i in range(n):
        day = D - dt.timedelta(days=n - 1 - i)
        out.append({"date": day, "steps": 8000 + i * 10, "active_min": 60, "sedentary_min": 600,
                    "stress_avg": 30 + (i % 7), "stress_high_min": 10, "awake_hr_avg": 70 + i // 7,
                    "bb_at_bedtime": 30, **kw})
    return out


def test_weeks_and_averages():
    days = rows(14)
    weeks = t.weeks(days)
    assert [w["week_start"].weekday() for w in weeks] == [0] * len(weeks)
    assert sum(w["n"] for w in weeks) == 14
    assert t.averages(days)["active_min"] == 60 and t.averages([])["steps"] is None


def test_awake_hr_trend():
    up = t.awake_hr_trend(rows(28))
    assert up["direction"] == "up" and up["per_week"] == pytest.approx(1.0, abs=0.2)
    flat = t.awake_hr_trend(rows(28, awake_hr_avg=70))
    assert flat["direction"] == "flat"
    short = t.awake_hr_trend(rows(5))
    assert short["direction"] is None and "14 days" in short["sentence"]


def test_weekday_pattern_peaks():
    days = rows(14)
    stress = {}
    for row in days:
        hot = (660, 780) if row["date"].weekday() < 5 else (1080, 1140)
        stress[row["date"]] = stress_series({hot: 80})
    out = t.weekday_pattern(days, stress)
    assert out["stress_peak_weekdays"]["start"] == "11:00"
    assert out["stress_peak_weekends"]["start"] == "18:00"
    assert out["sentence"].startswith("Stress tends to peak 11:00–13:00 on weekdays")
    assert len(out["by_weekday"]) == 7 and out["by_weekday"][0]["label"] == "Mon"
    assert t.weekday_pattern([], {})["sentence"] is None


def test_split_halves():
    vals = [(D - dt.timedelta(days=i), float(i)) for i in range(5)]
    high, low, split = t.split_halves(vals)
    assert len(high) == len(low) == 2 and split == 2.0
    assert t.split_halves([(D, 1.0)]) == ([], [], None)


def test_day_night_run_card():
    days = [{"date": D - dt.timedelta(days=i), "stress_avg": 60 if i % 2 else 20,
             "steps": 4000 if i % 2 else 12000} for i in range(1, 21)]
    nights = {row["date"] + dt.timedelta(days=1): {"sleep_score": 60 if row["stress_avg"] == 60 else 80,
                                                    "hrv": 40, "sleep_h": 7.0} for row in days}
    runs = {row["date"] + dt.timedelta(days=1): {"easy_hr": 150 if row["stress_avg"] == 60 else 140,
                                                  "efficiency": 1.2} for row in days[:8]}
    out = t.day_night_run(days, nights, runs)
    assert out["caveat"] and [g["key"] for g in out["groups"]] == ["stress", "steps"]
    stress = {row["metric"]: row for row in out["groups"][0]["rows"]}
    assert stress["sleep_score"]["enough_data"] is True
    assert stress["sleep_score"]["high"] == 60 and stress["sleep_score"]["low"] == 80
    assert stress["sleep_score"]["diff"] == -20
    assert stress["easy_hr"]["enough_data"] is True and stress["easy_hr"]["diff"] > 0
    few = t.day_night_run(days[:4], nights, {})
    row = few["groups"][0]["rows"][0]
    assert row["enough_data"] is False and row["high"] is None and "not enough" in row["sentence"]


def test_next_run_looks_two_days_ahead():
    runs = {D + dt.timedelta(days=2): {"easy_hr": 140}}
    assert t.next_run(D, runs) == {"easy_hr": 140}
    assert t.next_run(D - dt.timedelta(days=1), runs) is None


# --- route -------------------------------------------------------------------------------

def track(n=1500, step_m=3.0, lat0=18.59, lon0=73.73, hr=140, alt=True, wiggle=True):
    """A run heading east with a gentle wiggle; one sample a second."""
    out = []
    for i in range(n):
        dlon = (i * step_m) / (111_320 * math.cos(math.radians(lat0)))
        dlat = (math.sin(i / 50) * 20 / 111_320) if wiggle else 0
        out.append({"t": float(i), "lat": lat0 + dlat, "lon": lon0 + dlon, "dist": i * step_m,
                    "hr": hr, "alt": (550 + math.sin(i / 200) * 10) if alt else None})
    return out


def test_douglas_peucker_keeps_corners():
    xy = [(0, 0), (1, 0.01), (2, 0), (2, 1), (2, 2)]
    assert r.douglas_peucker(xy, 0.5) == [0, 2, 4]
    assert r.douglas_peucker(xy[:2], 1.0) == [0, 1]


def test_simplify_caps_points_and_keeps_required():
    xy = [(i, math.sin(i / 3) * 50) for i in range(5000)]
    kept = r.simplify(xy, 800, must_keep={1234})
    assert len(kept) <= 800 and 1234 in kept and kept[0] == 0 and kept[-1] == 4999


def test_build_route_shape_and_privacy_trim():
    segs = [(0.0, 900.0, "run"), (900.0, 1100.0, "walk"), (1100.0, 1500.0, "run")]
    body = r.build(track(), segs, hide_m=200)
    assert body["available"] and body["hidden_endpoints"] and body["trimmed_m"] == 200
    pts = body["points"]
    assert 2 <= len(pts) <= 800
    assert pts[0]["dist_m"] >= 200 and pts[-1]["dist_m"] <= body["total_distance_m"] - 200
    assert set(pts[0]) == {"lat", "lon", "dist_m", "t_s", "pace_s_per_km", "hr", "segment", "ele_m"}
    assert pts[0]["pace_s_per_km"] == 333           # 3 m/s
    assert {p["segment"] for p in pts} >= {"run", "walk"}
    assert body["has_hr"] and body["has_elevation"] and body["has_segments"]
    assert [k["km"] for k in body["km_markers"]] == [1, 2, 3, 4]
    for k in body["km_markers"]:
        assert pts[k["index"]]["lat"] == k["lat"] and pts[k["index"]]["dist_m"] >= k["km"] * 1000
    assert body["start"] == {"lat": pts[0]["lat"], "lon": pts[0]["lon"]}
    assert body["bounds"]["south"] <= body["bounds"]["north"]
    assert body["pace_range"] == {"min": 333, "max": 333}
    assert body["elevation"]["max_m"] > body["elevation"]["min_m"]


def test_build_route_without_hiding_starts_at_zero():
    body = r.build(track(), hide_m=0)
    assert body["points"][0]["dist_m"] == 0 and body["trimmed_m"] == 0
    assert body["hidden_endpoints"] is False and body["has_segments"] is False


def test_build_route_caps_long_runs():
    body = r.build(track(n=12000, step_m=3.0), hide_m=200)
    assert len(body["points"]) <= 800 and body["sampled_from"] == 12000


def test_build_route_unavailable():
    no_gps = r.build([{"t": 0, "lat": None, "lon": None, "dist": 0}])
    assert no_gps["available"] is False and no_gps["reason"] == "no_gps" and no_gps["points"] == []
    short = r.build(track(n=100), hide_m=200)       # 300 m
    assert short["reason"] == "too_short"


def test_route_drops_null_island_and_computes_missing_distance():
    samples = track(n=300, wiggle=False)
    samples[5]["lat"] = samples[5]["lon"] = 0.0
    for s in samples:
        s["dist"] = None
    body = r.build(samples, hide_m=0)
    assert body["sampled_from"] == 299
    assert body["total_distance_m"] == pytest.approx(897, abs=5)


def test_paces_ignore_gps_jumps_and_stops():
    times = [float(i) for i in range(60)]
    dists = [i * 3.0 for i in range(30)] + [90.0] * 30          # stops after 30 s
    paces = r._paces(times, dists)
    assert paces[5] == 333 and paces[59] is None
    jump = [i * 20.0 for i in range(60)]                          # 20 m/s
    assert r._paces(times, jump)[30] is None


def test_overlay_is_light():
    line = r.overlay(track(n=3000), hide_m=200)
    assert 2 <= len(line) <= 150 and len(line[0]) == 2
    assert r.overlay(track(n=50), hide_m=200) == []
