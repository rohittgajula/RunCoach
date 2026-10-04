"""R7 §1: decide() — the morning check-in rules (pure)."""

import pytest

from planning.checkin import WorkoutSummary, decide, signals
from planning.readiness import WellnessSnapshot

BASE = [50] * 10          # HRV history (fallback baseline)
RHR_BASE = [55] * 10      # resting HR baseline -> mean 55


def snap(**kw):
    defaults = dict(sleep_hours=7.5, hrv=55, hrv_baseline=BASE, hrv_baseline_low=45,
                    resting_hr=55, resting_hr_baseline=RHR_BASE, body_battery_high=80,
                    readiness=70, acwr=1.0)
    defaults.update(kw)
    return WellnessSnapshot(**defaults)


def status(snapshot, signal):
    reasons, _ = signals(snapshot)
    return next((r["status"] for r in reasons if r["signal"] == signal), None)


def run_walk():
    steps = [{"kind": "warmup", "duration_s": 300, "intensity": "walk", "label": "Walk warm-up",
              "pace_min_s": None, "pace_max_s": None, "hr_min": None, "hr_max": None}]
    for _ in range(3):
        steps += [{"kind": "run", "duration_s": 240, "intensity": "easy", "label": "Run 4:00",
                   "pace_min_s": 600, "pace_max_s": 645, "hr_min": 130, "hr_max": 145},
                  {"kind": "walk", "duration_s": 120, "intensity": "walk", "label": "Walk 2:00",
                   "pace_min_s": None, "pace_max_s": None, "hr_min": None, "hr_max": None}]
    return WorkoutSummary(title="25m run/walk", kind="RUN_WALK",
                          duration_s=sum(s["duration_s"] for s in steps), steps=steps,
                          target_zone="Z2", easy_pace=(600, 645), hr_easy=(130, 145))


def intervals():
    steps = [{"kind": "warmup", "duration_s": 300, "intensity": "walk", "label": "w",
              "hr_min": None, "hr_max": None},
             {"kind": "interval", "duration_s": 120, "intensity": "hard", "label": "Rep 1/2",
              "pace_min_s": 300, "pace_max_s": 330, "hr_min": 160, "hr_max": 175},
             {"kind": "recovery", "duration_s": 90, "intensity": "walk", "label": "Walk",
              "hr_min": None, "hr_max": None},
             {"kind": "interval", "duration_s": 120, "intensity": "hard", "label": "Rep 2/2",
              "pace_min_s": 300, "pace_max_s": 330, "hr_min": 160, "hr_max": 175}]
    return WorkoutSummary(title="Intervals 2 × 2:00", kind="INTERVALS", duration_s=630,
                          steps=steps, target_zone="Z4", easy_pace=(600, 645),
                          hr_easy=(130, 145))


def test_all_good_is_go():
    v = decide(snap(), run_walk())
    assert v.verdict == "go" and v.headline == "Go as planned" and v.adjusted is None
    assert v.signals_missing == []


def test_missing_data_is_never_bad():
    v = decide(WellnessSnapshot(), run_walk())
    assert v.verdict == "go"
    assert set(v.signals_missing) == {"sleep", "hrv", "rhr", "body_battery", "readiness", "load"}
    assert all(r["status"] != "bad" for r in v.reasons)


def test_hrv_without_any_baseline_is_missing_not_judged():
    v = decide(WellnessSnapshot(hrv=20), run_walk())
    assert "hrv" in v.signals_missing and v.verdict == "go"


@pytest.mark.parametrize("flag", ["pain_reported", "illness_reported"])
def test_pain_or_illness_is_rest_even_with_perfect_signals(flag):
    v = decide(snap(**{flag: True}), run_walk())
    assert v.verdict == "rest" and v.headline == "Rest today"
    assert v.adjusted["kind"] == "REST" and v.adjusted["steps"] == []
    assert v.reasons[0]["status"] == "bad"


def test_two_bad_is_swap_for_a_walk():
    v = decide(snap(sleep_hours=5.0, readiness=10, body_battery_high=45), run_walk())
    assert v.verdict == "swap" and v.headline == "Swap for a walk"
    assert v.adjusted["kind"] == "WALK"
    assert 20 * 60 <= v.adjusted["duration_s"] <= 30 * 60


def test_mildly_flagged_swap_is_half_run_walk():
    v = decide(snap(sleep_hours=5.0, readiness=10), run_walk())
    assert v.verdict == "swap" and v.adjusted["kind"] == "RUN_WALK"
    assert v.adjusted["duration_s"] == run_walk().duration_s // 2
    assert all(s["duration_s"] % 30 == 0 for s in v.adjusted["steps"])


def test_one_bad_is_easy():
    assert decide(snap(sleep_hours=5.9), run_walk()).verdict == "easy"


def test_two_watch_is_easy_one_watch_is_go():
    assert decide(snap(sleep_hours=6.5, body_battery_high=40), run_walk()).verdict == "easy"
    assert decide(snap(sleep_hours=6.5), run_walk()).verdict == "go"


def test_easy_lowers_hr_cap_and_keeps_duration():
    w = run_walk()
    v = decide(snap(sleep_hours=5.0), w)
    assert v.adjusted["duration_s"] == w.duration_s
    runs = [s for s in v.adjusted["steps"] if s["kind"] == "run"]
    assert all(s["hr_max"] == 140 for s in runs)


def test_easy_turns_hard_blocks_easy():
    v = decide(snap(sleep_hours=5.0), intervals())
    adjusted = v.adjusted
    assert adjusted["kind"] == "EASY" and adjusted["duration_s"] == 630
    assert all(s["intensity"] in ("easy", "walk") for s in adjusted["steps"])
    assert not any(s["kind"] in ("interval", "stride") for s in adjusted["steps"])
    assert [s["hr_max"] for s in adjusted["steps"] if s["intensity"] == "easy"] == [140, 140]


def test_no_workout_is_no_plan_with_note():
    v = decide(snap(sleep_hours=5.0), None)
    assert v.verdict == "no_plan" and v.adjusted is None
    assert "20-min walk" in v.note
    assert any(r["signal"] == "sleep" for r in v.reasons)


def test_race_is_never_rewritten():
    race = WorkoutSummary(title="Race", kind="RACE", duration_s=3600, steps=[])
    v = decide(snap(sleep_hours=5.0, readiness=10), race)
    assert v.verdict == "swap" and v.adjusted is None


# --- thresholds at the boundaries ------------------------------------------------

@pytest.mark.parametrize("hours,expected", [(5.99, "bad"), (6.0, "watch"), (6.99, "watch"),
                                            (7.0, "good")])
def test_sleep_boundaries(hours, expected):
    assert status(snap(sleep_hours=hours), "sleep") == expected


@pytest.mark.parametrize("hrv,expected", [(44, "bad"), (45, "good")])
def test_hrv_against_garmin_baseline_low(hrv, expected):
    assert status(snap(hrv=hrv, hrv_baseline_low=45), "hrv") == expected


@pytest.mark.parametrize("rhr,expected", [(58, "good"), (59, "watch"), (61, "watch"),
                                          (62, "bad")])
def test_rhr_boundaries(rhr, expected):
    assert status(snap(resting_hr=rhr), "rhr") == expected


@pytest.mark.parametrize("value,expected", [(29, "bad"), (30, "watch"), (49, "watch"),
                                            (50, "good")])
def test_body_battery_boundaries(value, expected):
    assert status(snap(body_battery_high=value), "body_battery") == expected


@pytest.mark.parametrize("value,expected", [(24, "bad"), (25, "watch"), (49, "watch"),
                                            (50, "good")])
def test_readiness_boundaries(value, expected):
    assert status(snap(readiness=value), "readiness") == expected


@pytest.mark.parametrize("value,expected", [(1.5, "good"), (1.51, "watch")])
def test_acwr_boundary(value, expected):
    assert status(snap(acwr=value), "load") == expected


@pytest.mark.parametrize("rpe,expected", [(7, "good"), (8, "watch"), (None, None)])
def test_yesterdays_rpe(rpe, expected):
    assert status(snap(last_rpe=rpe), "rpe") == expected
    _, missing = signals(snap(last_rpe=rpe))
    assert "rpe" not in missing


def test_reason_shape_and_order():
    reasons, _ = signals(snap(sleep_hours=5.0, body_battery_high=40))
    assert [r["status"] for r in reasons][:2] == ["bad", "watch"]
    assert all(set(r) == {"signal", "status", "label", "value", "baseline"} for r in reasons)
