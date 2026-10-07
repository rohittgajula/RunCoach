"""R9 §C: the habit health report — pure maths in analysis/habits.py."""

import datetime as dt
import re

import pytest

from analysis import habits as h

END = dt.date(2026, 10, 7)
START = END - dt.timedelta(days=27)              # 4 weeks
PREV_END = START - dt.timedelta(days=1)
PREV_START = START - dt.timedelta(days=28)
CAUSAL = re.compile(r"\b(because|caus|due to|leads? to|result(s|ed)? in|makes? you|"
                    r"made your)\b", re.I)


def days(first, last):
    return [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]


def build(habit="smoke", *, totals=None, mornings=None, runs=None, tracking=PREV_START,
          late=None, quit_date=None, impact=None, prev_impact=None, start=START):
    totals = totals or {}
    mornings = mornings or {}
    runs = runs or {}
    window = [d for d in days(max(start, tracking), END) if d < END]
    if impact is None:
        impact = h.impact(habit, totals, window, mornings, runs) if window else []
    return h.habit_report(habit, totals=totals, start=start, end=END, prev_start=PREV_START,
                          prev_end=PREV_END, tracking=tracking, impact_rows=impact,
                          prev_impact_rows=prev_impact or [], mornings=mornings, runs=runs,
                          late_days=late or set(), quit_date=quit_date,
                          previous_label="the previous 4 weeks")


def kinds(report):
    return [f["kind"] for f in report["findings"]]


# --- Spearman -------------------------------------------------------------------

def test_spearman_perfect_and_inverse():
    assert h.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert h.spearman([1, 2, 3, 4], [9, 7, 5, 1]) == pytest.approx(-1.0)


def test_spearman_ties_use_average_ranks():
    # x ranks 1.5,1.5,3,4 ; y ranks 1,2,3,4 -> pearson on ranks
    assert h.spearman([1, 1, 2, 3], [1, 2, 3, 4]) == pytest.approx(0.9487, abs=1e-3)


def test_spearman_constant_or_short_is_none():
    assert h.spearman([2, 2, 2, 2], [1, 2, 3, 4]) is None
    assert h.spearman([1, 2], [2, 1]) is None
    assert h.spearman([1, 2, 3], [1, 2]) is None


# --- amount trend ---------------------------------------------------------------

def test_amount_down_up_steady():
    before = {d: 10 for d in days(PREV_START, PREV_END)}
    down = h.amount_trend({**before, **{d: 6 for d in days(START, END)}},
                          START, END, PREV_START, PREV_END, PREV_START)
    assert down["direction"] == "down" and down["change_pct"] == -40.0
    assert down["now_per_day"] == 6 and down["before_per_day"] == 10
    assert down["now_per_week"] == 42 and down["before_per_week"] == 70
    up = h.amount_trend({**before, **{d: 12 for d in days(START, END)}},
                        START, END, PREV_START, PREV_END, PREV_START)
    assert up["direction"] == "up"
    steady = h.amount_trend({**before, **{d: 9.5 for d in days(START, END)}},
                            START, END, PREV_START, PREV_END, PREV_START)
    assert steady["direction"] == "steady" and steady["change_pct"] == -5.0


def test_amount_needs_a_tracked_week_each_side():
    tracking = START + dt.timedelta(days=3)      # began inside the current range
    out = h.amount_trend({tracking: 2}, START, END, PREV_START, PREV_END, tracking)
    assert out["direction"] is None and out["before_per_day"] is None
    assert h.amount_trend({}, START, END, PREV_START, PREV_END, None)["direction"] is None


def test_amount_from_zero():
    totals = {END: 3}
    out = h.amount_trend(totals, START, END, PREV_START, PREV_END, PREV_START)
    assert out["direction"] == "up" and out["change_pct"] is None
    none = h.amount_trend({}, START, END, PREV_START, PREV_END, PREV_START)
    assert none["direction"] == "steady" and none["change_pct"] == 0.0


# --- per-habit report -----------------------------------------------------------

def test_report_shape_and_status_improving():
    totals = {d: 10 for d in days(PREV_START, PREV_END)} | {d: 5 for d in days(START, END)}
    r = build(totals=totals)
    assert set(r) == {"habit", "status", "headline", "amount", "findings"}
    assert set(r["amount"]) >= {"now_per_day", "before_per_day", "change_pct"}
    assert r["status"] == "improving"
    assert r["headline"] == "Down 50% vs the previous 4 weeks"
    assert r["findings"][0]["kind"] == "amount" and r["findings"][0]["tone"] == "good"
    assert "10 → 5 a day (−50%)" in r["findings"][0]["text"]
    for f in r["findings"]:
        assert set(f) == {"tone", "text", "kind"}
        assert f["tone"] in ("good", "bad", "neutral")


def test_alcohol_amount_is_per_week():
    totals = {d: 1 for d in days(PREV_START, PREV_END)} | {d: 2 for d in days(START, END)}
    r = build("alcohol", totals=totals)
    assert r["status"] == "worsening" and r["headline"].startswith("Up 100%")
    assert "Drinks: 7 → 14 a week" in r["findings"][0]["text"]


def test_not_enough_data_lists_whats_missing_once():
    r = build(totals={END - dt.timedelta(days=2): 1}, tracking=END - dt.timedelta(days=2))
    assert r["status"] == "not_enough_data"
    assert r["headline"] == "Keep logging to see a trend"
    keep = [f for f in r["findings"] if f["kind"] == "keep_logging"]
    assert len(keep) == 1 and keep[0]["tone"] == "neutral"
    assert "amount trend" in keep[0]["text"] and "next-morning effect" in keep[0]["text"]


def mornings_split(exposed, hrv_with, hrv_without, **extra):
    out = {}
    for d in days(PREV_START, END + dt.timedelta(days=1)):
        prev = d - dt.timedelta(days=1)
        out[d] = {"hrv": hrv_with if prev in exposed else hrv_without, **extra}
    return out


def test_next_morning_finding_wording_and_tone():
    exposed = {d for i, d in enumerate(days(START, END)) if i % 2 == 0}
    totals = {d: 2 for d in exposed}
    r = build("alcohol", totals=totals, mornings=mornings_split(exposed, 40, 50))
    nm = [f for f in r["findings"] if f["kind"] == "next_morning"]
    assert nm and nm[0]["tone"] == "bad"
    assert nm[0]["text"].startswith("On mornings after drinking, your HRV averaged 10 ms lower")
    assert "(n=" in nm[0]["text"]


def test_new_bad_next_morning_blocks_improving():
    before = {d: 4 for d in days(PREV_START, PREV_END)}
    exposed = {d for i, d in enumerate(days(START, END)) if i % 2 == 0}
    totals = before | {d: 2 for d in exposed}           # 4/day -> ~1/day: down
    mornings = mornings_split(exposed, 40, 50)
    r = build("alcohol", totals=totals, mornings=mornings)
    assert any(f["kind"] == "next_morning" and f["tone"] == "bad" for f in r["findings"])
    assert r["status"] == "steady"                      # down, but a new bad finding
    # The same finding already bad in the previous range is not "new".
    prev = [{"habit": "alcohol", "metric": "hrv", "dose": None, "enough_data": True,
             "direction": "worse"}]
    assert build("alcohol", totals=totals, mornings=mornings,
                 prev_impact=prev)["status"] == "improving"


def test_dose_needs_three_nights_each():
    nights = days(START, END - dt.timedelta(days=1))
    totals = {}
    mornings = {}
    for i, d in enumerate(nights[:12]):
        qty = 1 if i < 6 else 4
        totals[d] = qty
        mornings[d + dt.timedelta(days=1)] = {"hrv": 50 if qty == 1 else 38, "sleep_score": 80}
    r = build("alcohol", totals=totals, mornings=mornings)
    dose = [f for f in r["findings"] if f["kind"] == "dose"]
    assert dose[0]["tone"] == "bad"
    assert dose[0]["text"].startswith("After 3+ drinks, your HRV the next morning averaged "
                                      "12 ms lower than after 1–2 drinks (n=6 vs 6)")
    few = {d: q for d, q in totals.items() if q == 1} | {nights[20]: 4}
    r = build("alcohol", totals=few, mornings=mornings)
    assert not [f for f in r["findings"] if f["kind"] == "dose"]
    assert "dose comparison" in r["findings"][-1]["text"]


def test_timing_late_vs_early():
    nights = days(START, END - dt.timedelta(days=1))[:10]
    totals = {d: 1 for d in nights}
    late = set(nights[:5])
    mornings = {d + dt.timedelta(days=1): {"sleep_score": 70 if d in late else 80, "hrv": 50}
                for d in nights}
    r = build("sugar", totals=totals, mornings=mornings, late=late)
    timing = [f for f in r["findings"] if f["kind"] == "timing"]
    assert timing[0]["tone"] == "bad"
    assert timing[0]["text"] == ("On mornings after sugary food after 21:00, your sleep score "
                                 "averaged 10 lower than after earlier sugary food (n=5 vs 5).")
    assert any(f["kind"] == "timing" and f["tone"] == "neutral" for f in r["findings"])  # hrv
    # Smoke has no timing finding at all.
    assert "timing" not in kinds(build("smoke", totals=totals, mornings=mornings, late=late))


def test_weekly_link_spearman_threshold_and_wording():
    start = END - dt.timedelta(days=83)                   # 12 weeks
    totals, mornings = {}, {}
    for w in range(12):
        week = days(start + dt.timedelta(days=7 * w), start + dt.timedelta(days=7 * w + 6))
        for d in week:
            totals[d] = w % 4                              # amount varies by week
            mornings[d] = {"hrv": 60 - 3 * (w % 4), "rhr": 55, "sleep_score": 80}
    r = build("smoke", totals=totals, mornings=mornings, start=start, tracking=start)
    link = [f for f in r["findings"] if f["kind"] == "weekly_link"]
    assert link and link[0]["tone"] == "bad"
    assert link[0]["text"].startswith("Weeks with more cigarettes tended to have lower HRV "
                                      "(ρ=−1.00, 12 weeks)")


def test_weekly_link_absent_under_six_weeks():
    r = build("smoke", totals={END: 1})                    # 4-week range: never possible
    assert "weekly_link" not in kinds(r)
    assert "weekly link" not in r["findings"][-1]["text"]


def test_since_quit_comparison():
    quit_date = END - dt.timedelta(days=20)
    mornings = {d: {"rhr": 60 if d < quit_date else 56, "hrv": 45 if d < quit_date else 52,
                    "sleep_score": 75}
                for d in days(quit_date - dt.timedelta(days=14), END)}
    r = build("smoke", mornings=mornings, quit_date=quit_date, tracking=quit_date)
    sq = [f for f in r["findings"] if f["kind"] == "since_quit"]
    texts = " ".join(f["text"] for f in sq)
    assert "Since you quit, your resting HR averaged 4 bpm lower than in the 14 days before" \
        in texts
    assert all(f["tone"] in ("good", "neutral") for f in sq)
    assert any(f["tone"] == "good" for f in sq)


def test_since_quit_waits_a_week():
    r = build("smoke", quit_date=END - dt.timedelta(days=3), tracking=END - dt.timedelta(days=3))
    assert "since_quit" not in kinds(r)
    assert "since-quit comparison (starts 7 days" in r["findings"][-1]["text"]
    assert "since_quit" not in kinds(build("alcohol", quit_date=END - dt.timedelta(days=30)))


def test_next_day_run():
    nights = days(START, END - dt.timedelta(days=1))[:8]
    totals = {d: 1 for d in nights[:4]}
    runs = {d + dt.timedelta(days=1): {"easy_hr": 150 if d in totals else 144,
                                       "efficiency": 1.0}
            for d in nights}
    r = build("smoke", totals=totals, runs=runs)
    run = [f for f in r["findings"] if f["kind"] == "next_day_run"]
    assert run[0]["tone"] == "bad"
    assert run[0]["text"] == ("On runs the day after smoking, your easy-pace HR averaged 6 bpm "
                              "higher (n=4 vs 4).")


def test_private_wording_is_only_private():
    nights = days(START, END - dt.timedelta(days=1))[:10]
    totals = {d: 1 for d in nights}
    late = set(nights[:5])
    mornings = {d + dt.timedelta(days=1): {"sleep_score": 70 if d in late else 80}
                for d in nights}
    r = build("private", totals=totals, mornings=mornings, late=late)
    text = " ".join(f["text"] for f in r["findings"]) + r["headline"]
    assert "Private" in text
    assert set(re.findall(r"[A-Za-z]+", text)) & {"sex", "sexual", "masturbation", "porn"} == set()


def test_no_causal_wording_anywhere():
    quit_date = END - dt.timedelta(days=20)
    exposed = {d for i, d in enumerate(days(START, END)) if i % 2 == 0}
    totals = {d: 4 for d in days(PREV_START, PREV_END)} | {d: 2 for d in exposed}
    mornings = mornings_split(exposed, 40, 50, rhr=58, sleep_score=70)
    runs = {d: {"easy_hr": 150, "efficiency": 1.0} for d in days(START, END)}
    for habit in ("smoke", "alcohol", "sugar", "private"):
        r = build(habit, totals=totals, mornings=mornings, runs=runs, late=set(list(exposed)[:6]),
                  quit_date=quit_date if habit == "smoke" else None)
        for f in r["findings"]:
            assert not CAUSAL.search(f["text"]), f["text"]


# --- garmin + overall -----------------------------------------------------------

def test_garmin_compare_rows():
    mornings = {d: {"hrv": 50 if d >= START else 45, "rhr": 56 if d >= START else 58,
                    "sleep_score": 80, "stress": 30, "body_battery": 70,
                    "sleep_respiration": 14.0} for d in days(PREV_START, END)}
    runs = {START: {"easy_hr": 140, "efficiency": 1.1}}
    rows = {r["metric"]: r for r in h.garmin_compare(mornings, runs, START, END, PREV_START,
                                                     PREV_END)}
    assert list(rows) == ["hrv", "rhr", "sleep_score", "stress", "body_battery_high",
                          "respiration", "easy_pace_hr", "efficiency"]
    assert set(rows["hrv"]) == {"metric", "label", "unit", "now", "before", "delta", "better"}
    assert rows["hrv"]["now"] == 50 and rows["hrv"]["before"] == 45 and rows["hrv"]["better"]
    assert rows["rhr"]["delta"] == -2 and rows["rhr"]["better"] is True
    assert rows["sleep_score"]["better"] is None                 # no change
    assert rows["easy_pace_hr"]["now"] is None and rows["easy_pace_hr"]["better"] is None


def card(status):
    return {"habit": "x", "status": status, "headline": "", "amount": {}, "findings": []}


def vitals(hrv_better=None, rhr_better=None):
    return [{"metric": "hrv", "label": "", "unit": "ms", "now": 50, "before": 45, "delta": 5,
             "better": hrv_better},
            {"metric": "rhr", "label": "", "unit": "bpm", "now": 56, "before": 58,
             "delta": -2, "better": rhr_better}]


def test_overall_rules():
    label = "the previous 4 weeks"
    assert h.overall([], vitals(), label)["status"] == "not_enough_data"
    assert h.overall([card("not_enough_data")], vitals(), label)["status"] == "not_enough_data"
    imp = h.overall([card("improving"), card("improving"), card("steady")], vitals(True), label)
    assert imp["status"] == "improving"
    assert imp["headline"] == ("2 of 3 habits improving vs the previous 4 weeks; HRV 45 → 50 ms, "
                               "resting HR 58 → 56 bpm")
    # Habits improving but HRV worse -> not "improving".
    assert h.overall([card("improving")], vitals(hrv_better=False), label)["status"] == "steady"
    assert h.overall([card("worsening"), card("worsening"), card("improving")], vitals(),
                     label)["status"] == "worsening"
    assert h.overall([card("improving"), card("worsening")], vitals(), label)["status"] == \
        "steady"


def test_report_wraps():
    out = h.report([card("improving")], vitals(), "the previous 4 weeks")
    assert set(out) == {"overall", "garmin", "habits"}
    assert set(out["overall"]) == {"status", "headline"}
