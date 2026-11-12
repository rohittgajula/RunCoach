"""R13 pure modules: auto-adjust rules, strength placement + Garmin payload, race-day
planner, injury flags, run review, cravings, caffeine, monthly report, briefing."""

import datetime as dt

import pytest

from analysis import briefing, caffeine, cravings, injury, monthly_report, run_review
from planning import adapt, garmin_strength, race_day, strength

TODAY = dt.date(2026, 10, 7)        # a Wednesday
YESTERDAY = TODAY - dt.timedelta(days=1)


# --- §1 auto-adjust -------------------------------------------------------------------

def up(id_, days, kind="EASY", run_s=1800, **kw):
    return adapt.Upcoming(id=id_, date=TODAY + dt.timedelta(days=days), kind=kind,
                          run_s=run_s, **kw)


def good_run(day_offset, **kw):
    base = dict(date=TODAY - dt.timedelta(days=day_offset), planned_kind="EASY",
                planned_run_s=1800, actual_run_s=1800, rpe=4, avg_hr=135, zone_top=145,
                drift_pct=3.0)
    base.update(kw)
    return adapt.RunFacts(**base)


def test_no_signals_no_change():
    d = adapt.decide(good_run(1), adapt.Context(), [up(1, 1)], TODAY)
    assert d.severity == "none" and d.changes == []


def test_hr_high_shortens_next_session_mildly_with_chip_reason():
    run = good_run(1, avg_hr=153)          # 8 over the zone top
    d = adapt.decide(run, adapt.Context(), [up(1, 1), up(2, 3)], TODAY)
    assert d.severity == "mild"
    assert d.changes == [adapt.Change(1, "shorten", factor=0.9)]
    assert "your HR ran 8 bpm high yesterday" in d.why


def test_mild_on_hard_session_swaps_with_later_easy_day():
    sessions = [up(1, 1, kind="INTERVALS"), up(2, 2, kind="EASY"), up(3, 4, kind="LONG")]
    d = adapt.decide(good_run(1, rpe=8), adapt.Context(), sessions, TODAY)
    assert {c.action for c in d.changes} == {"swap"}
    by_id = {c.workout_id: c for c in d.changes}
    assert by_id[1].new_date == TODAY + dt.timedelta(days=2)
    assert by_id[2].new_date == TODAY + dt.timedelta(days=1)
    assert by_id[1].group == by_id[2].group


def test_swap_never_puts_hard_session_the_day_before_a_long_run():
    # The only easy day is the day before the long run: no swap, ease instead.
    sessions = [up(1, 1, kind="TEMPO"), up(2, 2, kind="EASY"), up(3, 3, kind="LONG")]
    d = adapt.decide(good_run(1, rpe=8), adapt.Context(), sessions, TODAY)
    assert d.changes[0].action == "easier" and d.changes[0].new_kind == "EASY"


def test_moderate_shortens_two_sessions_and_eases_hard():
    run = good_run(1, rpe=9)               # weight 2
    d = adapt.decide(run, adapt.Context(), [up(1, 1), up(2, 2, kind="TEMPO")], TODAY)
    assert d.severity == "moderate"
    assert d.changes[0] == adapt.Change(1, "shorten", factor=0.8)
    assert d.changes[1].action == "easier" and d.changes[1].factor == 0.9


def test_strong_converts_to_run_walk():
    run = good_run(1, rpe=9, avg_hr=160, actual_run_s=700)   # 2 + 2 + 2
    d = adapt.decide(run, adapt.Context(), [up(1, 1), up(2, 2)], TODAY)
    assert d.severity == "strong"
    assert d.changes[0].action == "run_walk" and d.changes[0].factor == 0.75
    assert d.changes[1] == adapt.Change(2, "shorten", factor=0.85)


def test_bad_pain_means_rest_next_session():
    ctx = adapt.Context(pain="bad", pain_label="your knee (left) sore 2 days")
    d = adapt.decide(None, ctx, [up(1, 0), up(2, 2)], TODAY)
    assert d.changes[0].action == "rest" and d.changes[0].workout_id == 1
    assert "knee" in d.why


@pytest.mark.parametrize("field,value", [
    ("readiness", 20), ("sleep_debt_s", 6 * 3600), ("drinks_last_night", 3),
])
def test_context_signals_make_it_easier(field, value):
    d = adapt.decide(good_run(1), adapt.Context(**{field: value}), [up(1, 1)], TODAY)
    assert d.severity == "mild" and d.changes[0].action == "shorten"


def test_never_touches_protected_sessions():
    sessions = [
        up(1, 0, kind="RACE"),
        up(2, 1, status="completed"),
        up(3, 1, completed=True),
        up(4, 1, adjusted_by="checkin"),
        up(5, 1, adjusted_by="kept"),
        up(6, 2, moved=True),
        up(7, -1),                                     # past
        up(8, 9),                                      # beyond the lookahead
        up(9, 1, kind="WALK"),
    ]
    d = adapt.decide(good_run(1, rpe=10), adapt.Context(), sessions, TODAY)
    assert d.changes == []


def test_only_ever_easier_factors():
    for level in ("mild", "moderate", "strong"):
        first, second = adapt.FACTORS[level]
        assert 0.75 <= first < 1 and (second is None or 0.75 <= second < 1)


def test_extend_needs_three_easy_and_good_runs_and_room():
    runs = [good_run(5), good_run(3), good_run(1)]
    ctx = adapt.Context(recent_runs=runs)
    # No room left in the week: nothing.
    d = adapt.decide(runs[-1], ctx, [up(1, 1, room_s=0)], TODAY)
    assert d.changes == []
    # Room for 2 min, 5 % of 30 min = 90 s -> 60 s (whole minutes).
    d = adapt.decide(runs[-1], ctx, [up(1, 1, room_s=120)], TODAY)
    assert d.severity == "extend" and d.changes == [adapt.Change(1, "extend", extend_s=60)]


def test_extend_capped_by_week_room_and_five_percent():
    assert adapt.extend_seconds(3600, 10_000) == 180          # 5 % of an hour
    assert adapt.extend_seconds(3600, 100) == 60              # the week's room
    assert adapt.extend_seconds(1000, 10_000) == 0            # under a minute
    assert adapt.extend_seconds(3600, -50) == 0


def test_extend_blocked_by_streak_break_pain_or_long_target():
    runs = [good_run(5), good_run(3, rpe=7), good_run(1)]
    assert adapt.decide(runs[-1], adapt.Context(recent_runs=runs),
                        [up(1, 1, room_s=600)], TODAY).changes == []
    good = [good_run(5), good_run(3), good_run(1)]
    assert adapt.decide(good[-1], adapt.Context(recent_runs=good, injury_risk="moderate"),
                        [up(1, 1, room_s=600)], TODAY).changes == []
    # Long runs and hard sessions are never extended.
    assert adapt.decide(good[-1], adapt.Context(recent_runs=good),
                        [up(1, 1, kind="LONG", room_s=600)], TODAY).changes == []


def test_day_words():
    assert adapt.day_word(TODAY, TODAY) == "today"
    assert adapt.day_word(YESTERDAY, TODAY) == "yesterday"
    assert adapt.day_word(TODAY - dt.timedelta(days=3), TODAY) == "on Sun"


# --- §4 strength -----------------------------------------------------------------------

def week_days(kinds_by_offset, monday=dt.date(2026, 10, 12)):
    return [strength.Day(monday + dt.timedelta(days=o), tuple(k)) for o, k in kinds_by_offset.items()]


def test_strength_on_non_run_days_not_before_hard_or_long():
    monday = dt.date(2026, 10, 12)
    days = week_days({1: ["EASY"], 3: ["INTERVALS"], 5: ["EASY"], 6: ["LONG"]})
    placed = strength.place(days, 2, monday, monday + dt.timedelta(days=6))
    dates = [d for d, _ in placed]
    assert len(dates) == 2
    for day in dates:
        weekday = (day - monday).days
        assert weekday not in (1, 3, 5, 6)          # run days
        assert weekday not in (2,)                  # day before intervals
    assert all(abs((a - b).days) > 1 for a in dates for b in dates if a != b)
    assert all(not after for _, after in placed)


def test_strength_after_easy_run_when_no_free_day():
    monday = dt.date(2026, 10, 12)
    days = week_days({0: ["EASY"], 1: ["RUN_WALK"], 2: ["EASY"], 3: ["EASY"], 4: ["EASY"],
                      5: ["TEMPO"], 6: ["LONG"]})
    placed = strength.place(days, 2, monday, monday + dt.timedelta(days=6))
    assert placed and all(after for _, after in placed)
    for day, _ in placed:
        assert (day - monday).days not in (4, 5, 6)   # day before tempo / tempo / long


def test_strength_skips_race_buffer_and_zero():
    monday = dt.date(2026, 10, 12)
    assert strength.place([], 0, monday, monday + dt.timedelta(days=6)) == []
    race = monday + dt.timedelta(days=4)
    placed = strength.place([strength.Day(race, ("RACE",))], 3, monday,
                            monday + dt.timedelta(days=6), race_date=race)
    assert placed == []


def test_strength_levels_progress_every_two_weeks():
    start = dt.date(2026, 10, 1)
    assert strength.level_for(start, start) == 1
    assert strength.level_for(start, start + dt.timedelta(days=13)) == 1
    assert strength.level_for(start, start + dt.timedelta(days=14)) == 2
    assert strength.level_for(start, start + dt.timedelta(days=400)) == strength.MAX_LEVEL
    one, three = strength.exercises(1), strength.exercises(3)
    calf1 = next(e for e in one if e["key"] == "calf")
    calf3 = next(e for e in three if e["key"] == "calf")

    # Progression is by MOVEMENT, not by rep count. This assertion used to read
    # `calf3["reps"] > calf1["reps"]`, which was right for a circuit that got
    # longer and wrong for a ladder that gets harder: ten single-leg calf raises
    # are a great deal more than twelve on two legs, and counting reps says the
    # opposite. Sets still step up, because that part was always about volume.
    assert calf3["name"] != calf1["name"]
    assert calf3["level"] > calf1["level"]
    assert calf3["sets"] == 3 and calf1["sets"] == 2

    core3 = next(e for e in three if e["key"] == "core")
    assert core3["seconds"] and core3["reps"] is None, "rung 3 core is a timed hold"


def test_garmin_strength_payload_shape_and_hash():
    session = {"title": "Strength & drills · level 1", "duration_s": 1200,
               "exercises": strength.exercises(1)}
    payload = garmin_strength.build_payload(session)
    assert payload["sportType"]["sportTypeKey"] == "strength_training"
    steps = payload["workoutSegments"][0]["workoutSteps"]
    # One group per movement pattern. Every one must survive the trip: an
    # exercise Garmin has no name for is mapped to the nearest real movement
    # rather than dropped, so a session on the watch is never quietly short.
    # The lifting, not the warm-up: a wrist timer prompting you through leg
    # swings is noise. Every LIFT must survive the trip, though — an exercise
    # Garmin has no name for is mapped to the nearest real movement rather than
    # dropped, so a session on the watch is never quietly short.
    lifts = [e for e in session["exercises"] if not e.get("is_warmup")]
    assert len(steps) == len(strength.PATTERNS) == len(lifts)
    orders = [steps[0]["stepOrder"]] + [s["stepOrder"] for s in steps[0]["workoutSteps"]]
    assert orders == [1, 2, 3]
    calf = steps[0]["workoutSteps"][0]
    assert calf["category"] == "CALF_RAISE" and calf["endCondition"]["conditionTypeKey"] == "reps"
    # Rung 1 core is a dead bug, which is counted per side rather than held.
    core = steps[-1]["workoutSteps"][0]
    assert core["category"] == "HIP_STABILITY" and core["exerciseName"] == "DEAD_BUG"
    assert core["endCondition"]["conditionTypeKey"] == "reps"
    timed = garmin_strength.build_payload(
        {"title": "t", "duration_s": 1200, "exercises": strength.exercises(2)}
    )["workoutSegments"][0]["workoutSteps"][-1]["workoutSteps"][0]
    assert timed["endCondition"]["conditionTypeKey"] == "time", "rung 2 core is a plank"
    # A per-side movement sends the watch BOTH sides as one step, so the rep
    # count doubles. Getting this wrong halves every single-leg exercise, which
    # is most of the ones that matter for running.
    per_side = next(e for e in lifts if e["per_side"])
    step = next(
        s["workoutSteps"][0] for s in steps
        if s["workoutSteps"][0]["description"].startswith(per_side["name"])
    )
    assert step["endConditionValue"] == float(per_side["reps"] * 2)
    assert step["description"].endswith("(each side)")
    a = garmin_strength.payload_hash(payload, "2026-10-08")
    assert a == garmin_strength.payload_hash(payload, "2026-10-08")
    assert a != garmin_strength.payload_hash(payload, "2026-10-09")


# --- §2 race day ------------------------------------------------------------------------

def test_target_uses_goal_unless_much_faster_than_prediction():
    t = race_day.target(10, 3600, 3700, None)
    assert t["source"] == "goal" and t["time_s"] == 3600 and t["pace_s_per_km"] == 360
    t = race_day.target(10, 3000, 3700, None)
    assert t["source"] == "prediction" and t["time_s"] == 3700 and "faster" in t["note"]
    t = race_day.target(10, None, None, 3500)
    assert t["source"] == "garmin"
    assert race_day.target(10, None, None, None) is None
    hot = race_day.target(10, 3600, None, None, slowdown_pct=8)
    assert hot["time_s"] == 3888 and "Heat" in hot["note"]


@pytest.mark.parametrize("km,strategy", [(10, "even"), (21.1, "negative"), (5, "negative"),
                                         (42.2, "even")])
def test_splits_sum_exactly(km, strategy):
    rows = race_day.splits(km, 6000, strategy)
    assert rows[-1]["elapsed_s"] == 6000
    assert sum(r["split_s"] for r in rows) == 6000
    assert rows[-1]["km"] == pytest.approx(km)


def test_negative_split_first_half_slower():
    rows = race_day.splits(10, 3600, "negative")
    assert rows[0]["pace_s_per_km"] > rows[-1]["pace_s_per_km"]
    even = race_day.splits(10, 3600, "even")
    assert len({r["split_s"] for r in even}) == 1


def test_fueling_by_duration_and_heat():
    short = race_day.fueling(1800, 360, 15, 10, 5)
    assert short["carbs_g_per_h"] == 0 and short["fluid_ml_per_h"] == 0
    assert not any(i["what"].startswith("Gel") for i in short["items"])
    half = race_day.fueling(2 * 3600, 340, 30, 22, 21.1)
    assert half["carbs_g_per_h"] == 45 and half["electrolytes"]
    gels = [i for i in half["items"] if i["what"].startswith("Gel")]
    assert [g["at_s"] for g in gels] == [1800, 3600, 5400]
    assert gels[0]["at_km"] == pytest.approx(5.3, abs=0.1)


def test_taper_checklist_shoes_and_sleep():
    race = TODAY + dt.timedelta(days=5)
    t = race_day.taper(race, TODAY, 10, 6.2, {"name": "Pegasus", "distance_km": 650})
    keys = {i["key"]: i for i in t["items"]}
    assert t["in_taper"] and set(keys) == {"sleep", "carbs", "kit", "route", "bib", "shoes"}
    assert keys["sleep"]["status"] == "warn" and keys["shoes"]["status"] == "warn"
    t = race_day.taper(race, TODAY, 21.1, 7.5, {"name": "New", "distance_km": 5})
    keys = {i["key"]: i for i in t["items"]}
    assert keys["sleep"]["status"] == "ok" and "only 5 km" in keys["shoes"]["detail"]
    assert keys["carbs"]["due_on"] == race - dt.timedelta(days=2)


def test_morning_timeline_and_warmup():
    rows = race_day.morning(6 * 60 + 30, 10)
    assert rows[0]["time"] == "03:30" and rows[-1]["time"] == "06:30"
    assert [r["time"] for r in rows] == sorted(r["time"] for r in rows)
    assert any(s["label"].startswith("2–3") for s in race_day.warmup(5))
    assert not any(s["label"] == "Easy jog" for s in race_day.warmup(42.2))


def test_weather_block_heat():
    w = race_day.weather_block({"temp": 30, "feels_like": 34, "dew_point": 24,
                                "humidity": 80, "precip_prob": 70, "wind": 5},
                               TODAY, "06:00")
    assert w["heat"] in ("hot", "very_hot") and w["pace_slowdown_pct"] >= 8
    assert any("Rain" in a for a in w["advice"])
    assert race_day.weather_block(None, TODAY, "06:00") is None


# --- §3 injury -------------------------------------------------------------------------

def runs_weeks(before_km, this_km):
    out = [injury.Run(TODAY - dt.timedelta(days=d), before_km / 3) for d in (8, 10, 12)]
    out += [injury.Run(TODAY - dt.timedelta(days=d), this_km / 3) for d in (0, 2, 4)]
    return out


def test_ramp_flag_needs_both_ramp_and_acwr():
    assert injury.ramp_flag(runs_weeks(10, 12), 1.5, TODAY)["level"] == "watch"
    assert injury.ramp_flag(runs_weeks(10, 12), 1.2, TODAY) is None
    assert injury.ramp_flag(runs_weeks(10, 10.5), 1.6, TODAY) is None
    assert injury.ramp_flag(runs_weeks(10, 14), 1.6, TODAY)["level"] == "high"


def test_long_run_share_and_cadence_and_gct():
    week = [injury.Run(TODAY, 8), injury.Run(TODAY - dt.timedelta(days=2), 3),
            injury.Run(TODAY - dt.timedelta(days=4), 3)]
    assert injury.long_run_flag(week, TODAY)["value"] == 57
    base = [injury.Run(TODAY - dt.timedelta(days=d), 5, cadence=168) for d in (14, 18, 22, 26)]
    recent = [injury.Run(TODAY - dt.timedelta(days=d), 5, cadence=160) for d in (1, 3, 5)]
    assert injury.cadence_flag(base + recent, TODAY)["value"] == 8.0
    assert injury.cadence_flag(base, TODAY) is None
    gct = [injury.Run(TODAY - dt.timedelta(days=d), 5, gct_balance=52.6) for d in (1, 3)]
    assert "52.6% left" in injury.gct_flag(gct)["text"]
    assert injury.gct_flag([injury.Run(TODAY, 5, gct_balance=51.0)] * 3) is None


def test_pain_signal_two_days_same_spot():
    p = [injury.Pain(TODAY, "knee", "left", 2), injury.Pain(YESTERDAY, "knee", "left", 2)]
    s = injury.pain_signal(p, TODAY)
    assert s["status"] == "watch" and s["label"] == "Knee (left) sore 2 days"
    p.append(injury.Pain(TODAY - dt.timedelta(days=2), "knee", "left", 3))
    assert injury.pain_signal(p, TODAY)["status"] == "bad"
    # Different spots, mild pain or one day only: nothing.
    assert injury.pain_signal([injury.Pain(TODAY, "knee", "left", 2),
                               injury.Pain(YESTERDAY, "knee", "right", 2)], TODAY) is None
    assert injury.pain_signal([injury.Pain(TODAY, "shin", "left", 1),
                               injury.Pain(YESTERDAY, "shin", "left", 1)], TODAY) is None
    assert injury.pain_signal([injury.Pain(TODAY - dt.timedelta(days=5), "hip", "left", 3),
                               injury.Pain(TODAY - dt.timedelta(days=6), "hip", "left", 3)],
                              TODAY) is None


def test_risk_levels_and_guidance_never_diagnose():
    assert injury.risk([]) == "low"
    assert injury.risk([{"level": "watch"}]) == "moderate"
    assert injury.risk([{"level": "watch"}] * 3) == "high"
    assert injury.risk([{"level": "high"}]) == "high"
    result = injury.assess([], None, [injury.Pain(TODAY, "calf", "right", 3),
                                      injury.Pain(YESTERDAY, "calf", "right", 3)],
                           {"name": "Old", "distance_km": 800, "retire_km": 700,
                            "replace_due": True}, TODAY)
    assert result["risk"] == "high"
    assert {f["kind"] for f in result["flags"]} == {"pain", "shoe"}
    assert any("physio" in g for g in result["guidance"])
    words = " ".join(result["guidance"] + [f["text"] for f in result["flags"]]).lower()
    for diagnosis in ("tendin", "fracture", "sprain", "strain", "syndrome"):
        assert diagnosis not in words


# --- §7 run review ----------------------------------------------------------------------

def point(i, days_ago, **kw):
    base = dict(activity_id=i, date=TODAY - dt.timedelta(days=days_ago), kind="EASY", km=4.0,
                pace=420.0, hr=145.0, drift=4.0, cadence=158.0, run_fraction=0.8)
    base.update(kw)
    return run_review.RunPoint(**base)


def test_review_compares_with_similar_runs_only():
    history = [point(1, 20), point(2, 15), point(3, 10, km=9.0), point(4, 5, kind="TEMPO"),
               point(5, 200)]
    run = point(9, 0, pace=405.0, hr=140.0, cadence=163.0, run_fraction=0.9)
    review = run_review.review(run, history + [run], zone_top=150, completion=1.0, rpe=4)
    assert review["compared_with"] == 2 and review["bucket"] == "2to5"
    rows = {r["key"]: r for r in review["metrics"]}
    assert rows["pace"]["better"] is True and rows["pace"]["delta"] == -15
    assert rows["hr_at_pace"]["better"] is True
    assert rows["cadence"]["better"] is True
    assert any("faster" in b for b in review["went_well"])
    assert review["next_time"]


def test_review_flags_drift_hr_cap_and_rpe():
    run = point(9, 0, drift=11.0, hr=158.0)
    review = run_review.review(run, [run], zone_top=150, completion=0.6, rpe=9)
    assert review["compared_with"] == 0
    text = " ".join(review["to_improve"])
    assert "drifted" in text and "above the easy cap" in text
    assert len(review["to_improve"]) <= 3 and len(review["next_time"]) <= 3


def test_bucket_edges():
    assert [run_review.bucket(k) for k in (1.9, 2, 4.99, 5, 8)] == ["lt2", "2to5", "2to5",
                                                                     "5to8", "8plus"]


# --- §8 cravings ---------------------------------------------------------------------------

def test_craving_summary_patterns_and_trend():
    rows = [cravings.Craving(TODAY, 9, 4, "coffee", "Office", False),
            cravings.Craving(TODAY, 9, 3, "coffee", "office", True),
            cravings.Craving(YESTERDAY, 21, 5, "alcohol", "Bar", False),
            cravings.Craving(TODAY - dt.timedelta(days=30), 9, 2, "stress", "", False)]
    s = cravings.summary(rows, TODAY - dt.timedelta(days=27), TODAY,
                         TODAY - dt.timedelta(days=55), TODAY - dt.timedelta(days=28))
    assert s["total"] == 3 and s["resisted"] == 2 and s["resisted_pct"] == 67
    assert s["by_trigger"][0] == {"trigger": "coffee", "label": "Coffee", "count": 2,
                                  "resisted": 1}
    assert s["top_places"][0] == {"place": "Office", "count": 2}
    assert s["peak_hours"][0] == {"hour": 9, "count": 2}
    assert len(s["by_hour"]) == 24
    assert s["trend"] == {"this_period": 3, "previous_period": 1, "change_pct": 200,
                          "direction": "up"}


def test_savings_progress_and_eta():
    s = cravings.savings("New shoes", 6000, 1500.0, 30, TODAY)
    assert s["pct"] == 25 and s["remaining"] == 4500 and s["per_day"] == 50.0
    assert s["eta"] == TODAY + dt.timedelta(days=90) and not s["reached"]
    done = cravings.savings("Watch", 1000, 1200, 40, TODAY)
    assert done["reached"] and done["pct"] == 100 and done["eta"] == TODAY
    assert cravings.savings("", 1000, 10, 1, TODAY) is None
    assert cravings.savings("X", 1000, None, None, TODAY)["eta"] is None


def test_resisted_milestones():
    dates = [TODAY - dt.timedelta(days=i) for i in range(12)]
    reached, count = cravings.resisted_milestones(dates)
    assert count == 12 and set(reached) == {1, 10}


# --- §9 caffeine ---------------------------------------------------------------------------

def test_caffeine_amounts_and_late_days():
    logs = [(TODAY - dt.timedelta(days=2), 8, 1.0, "coffee"),
            (TODAY - dt.timedelta(days=2), 15, 1.0, "tea"),
            (TODAY - dt.timedelta(days=1), 9, 2.0, "energy")]
    a = caffeine.amounts(logs, TODAY - dt.timedelta(days=6), TODAY)
    assert a["total"] == 4.0 and a["late_days"] == 1
    assert a["by_type"] == {"coffee": 1.0, "tea": 1.0, "energy": 2.0, "other": 0.0}
    assert a["series"][0] == {"date": TODAY - dt.timedelta(days=2), "count": 2.0, "late": True}
    assert len(a["series"]) == 3 and a["per_day_avg"] == round(4 / 3, 1)


def test_caffeine_impact_needs_four_each_side():
    series, nights = [], {}
    for i in range(10):
        day = TODAY - dt.timedelta(days=20 - i)
        late = i % 2 == 0
        series.append({"date": day, "count": 1.0, "late": late})
        nights[day + dt.timedelta(days=1)] = {"sleep_score": 70 if late else 80,
                                              "deep_sleep_min": 60, "awake_min": None}
    rows = {r["metric"]: r for r in caffeine.impact(series, nights)}
    assert rows["sleep_score"]["direction"] == "worse" and rows["sleep_score"]["enough_data"]
    assert rows["deep_sleep_min"]["direction"] == "no_clear_difference"
    assert not rows["awake_min"]["enough_data"]
    assert "not enough nights" in rows["awake_min"]["sentence"]


# --- §11 monthly ---------------------------------------------------------------------------

def test_monthly_bullets_and_goal():
    runs = {"count": 10, "previous_count": 8, "km": 50.0, "previous_km": 40.0,
            "planned": 12, "planned_done": 10}
    good, bad, goal = monthly_report.bullets(
        runs=runs, prs=[{"label": "5K", "display": "27:10"}],
        fitness={"vo2max": monthly_report.change(40.0, 41.0),
                 "fitness_age": monthly_report.change(38.0, 38.2)},
        wellness=[], habits=[{"habit": "private", "label": "Private", "this_month": 1,
                              "previous_month": 5, "delta": -4, "better": True}],
        smoke_free_days=12, mood={"mood_avg": 3.0, "previous_mood_avg": 3.6},
        weight={"start": 80, "end": 79.2, "change": -0.8}, diet_goal="lose",
        injury={"flags": 1, "pain_days": 2}, ai_safe=True)
    assert len(good) <= 3 and len(bad) <= 3
    assert "10 of 12 planned runs done" in good
    assert any("Mood" in b for b in bad)
    assert not any("Private" in b for b in good + bad)
    assert goal.startswith("Keep easy days")


def test_monthly_habit_rows_and_mood_block():
    rows = monthly_report.habit_rows({"caffeine": 40.0}, {"caffeine": 50.0}, ["caffeine"])
    assert rows[0]["label"] == "Caffeine (cups)" and rows[0]["better"] is True
    block = monthly_report.mood_block([(4, 3), (2, 3)], [])
    assert block == {"mood_avg": 3.0, "energy_avg": 3.0, "days": 2, "previous_mood_avg": None,
                     "previous_energy_avg": None}


# --- §6 briefing ---------------------------------------------------------------------------

def test_briefing_focus_order():
    common = dict(headline="Keep it easy today", workout_kind="INTERVALS", injury_text="x",
                  sleep_h=7.5)
    assert briefing.focus(verdict="go", injury_risk="high", **common)["key"] == "injury"
    assert briefing.focus(verdict="rest", injury_risk="low", **common)["key"] == "rest"
    assert briefing.focus(verdict="easy", injury_risk="low", **common)["key"] == "easy"
    assert briefing.focus(verdict="go", injury_risk="low", **common)["key"] == "quality"
    assert briefing.focus(verdict="no_plan", injury_risk="low", headline=None,
                          workout_kind=None, injury_text=None, sleep_h=None,
                          has_strength=True)["key"] == "strength"
    assert briefing.greeting("Rohit Gajula") == "Good morning, Rohit"


def test_briefing_notes():
    notes = briefing.notes(injury_risk="moderate", injury_text="Cadence down", drinks=3,
                           smoke_free_days=5, sleep_h=5.5, need_h=8.0, mood=2, reviewed=True)
    assert [n["kind"] for n in notes] == ["injury", "habit", "habit", "sleep", "mood", "review"]
    assert briefing.notes(injury_risk="low", injury_text=None, drinks=1, smoke_free_days=0,
                          sleep_h=8, need_h=8, mood=4, reviewed=False) == []
