"""R6 §3 compliance checks (pure) and §7 rounding."""

import datetime as dt

import pytest

from analysis.compliance import evaluate
from planning.generator import Session
from planning.workouts import Bands, build_workout

BANDS = Bands(easy_pace=(420, 480), moderate_pace=(360, 380), hard_pace=(300, 330),
              hr_easy=(120, 145), hr_moderate=(145, 160), hr_hard=(160, 175))


def easy_plan(duration=1800, run=1200):
    return {"kind": "RUN_WALK", "duration_s": duration, "target_zone": "Z2",
            "steps": [{"kind": "run", "intensity": "easy", "duration_s": run},
                      {"kind": "walk", "intensity": "walk", "duration_s": duration - run}]}


def statuses(result):
    return {c["key"]: c["status"] for c in result["checks"]}


def test_a_well_executed_easy_session_scores_100():
    actual = {"duration_s": 1800, "run_duration_s": 1200, "longest_run_s": 300,
              "time_in_zone": {"below": 300, "Z1": 600, "Z2": 800, "Z3": 100},
              "run_blocks": [{"duration_s": 300, "hr_avg": 140, "hr_max": 150}] * 4}
    result = evaluate(easy_plan(), actual, hr_ceiling=155)
    assert statuses(result) == {"duration": "hit", "run_time": "hit", "easy_effort": "hit",
                                "hr_ceiling": "hit"}
    assert result["score"] == 100


def test_too_hard_and_too_short_is_flagged():
    actual = {"duration_s": 1000, "run_duration_s": 500, "longest_run_s": 500,
              "time_in_zone": {"Z2": 200, "Z3": 400, "Z4": 400},
              "run_blocks": [{"duration_s": 250, "hr_avg": 165, "hr_max": 172}] * 2}
    result = evaluate(easy_plan(), actual, hr_ceiling=155)
    assert statuses(result) == {"duration": "missed", "run_time": "missed",
                                "easy_effort": "missed", "hr_ceiling": "missed"}
    assert result["score"] == 0


def test_close_band():
    actual = {"duration_s": 1500, "run_duration_s": 1000, "longest_run_s": 0,
              "time_in_zone": None, "run_blocks": []}
    result = evaluate(easy_plan(), actual)
    assert statuses(result) == {"duration": "close", "run_time": "close"}
    assert result["score"] == 60


def test_long_run_continuous_block():
    plan = {"kind": "LONG", "duration_s": 3600, "target_zone": "Z2", "steps": [
        {"kind": "run", "intensity": "easy", "duration_s": 1200},
        {"kind": "walk", "intensity": "walk", "duration_s": 120},
        {"kind": "run", "intensity": "easy", "duration_s": 1200},
        {"kind": "walk", "intensity": "walk", "duration_s": 1080}]}
    actual = {"duration_s": 3600, "run_duration_s": 2400, "longest_run_s": 900,
              "time_in_zone": None, "run_blocks": []}
    assert statuses(evaluate(plan, actual))["continuous_block"] == "close"


def test_interval_reps_counted_by_pace():
    steps = [{"kind": "warmup", "intensity": "walk", "duration_s": 300}]
    for _ in range(5):
        steps += [{"kind": "interval", "intensity": "hard", "duration_s": 120,
                   "pace_max_s": 330, "hr_min": 160},
                  {"kind": "recovery", "intensity": "walk", "duration_s": 90}]
    plan = {"kind": "INTERVALS", "duration_s": 1500, "target_zone": None, "steps": steps}
    blocks = [{"duration_s": 120, "pace_s_per_km": 320, "hr_avg": 165, "hr_max": 175}] * 4 + [
        {"duration_s": 600, "pace_s_per_km": 450, "hr_avg": 140, "hr_max": 150}]
    actual = {"duration_s": 1500, "run_duration_s": 1080, "longest_run_s": 600,
              "time_in_zone": None, "run_blocks": blocks}
    checks = {c["key"]: c for c in evaluate(plan, actual, hr_ceiling=155)["checks"]}
    assert checks["intervals"]["status"] == "close" and checks["intervals"]["actual"] == "4"
    assert "hr_ceiling" not in checks            # hard sessions are meant to go over it


# --- §7 rounding --------------------------------------------------------------

@pytest.mark.parametrize("kind,phase", [
    ("EASY", "AEROBIC"), ("EASY", "PEAK"), ("RUN_WALK", "FOUNDATION"), ("LONG", "SPECIFIC"),
    ("INTERVALS", "AEROBIC"), ("TEMPO", "PEAK"), ("WALK", "BASE"),
])
@pytest.mark.parametrize("run_min,walk_min", [(12.3, 9.7), (22.4, 13.1), (37.7, 4.2), (6.6, 6.9)])
def test_no_fractional_minute_steps(kind, phase, run_min, walk_min):
    session = Session(date=dt.date(2026, 1, 1), kind=kind, run_minutes=run_min,
                      walk_minutes=walk_min, target_run_m=0, purpose="p", effort="easy",
                      continuous_target_s=437 if kind == "LONG" else None)
    spec = build_workout(session, BANDS, phase)
    assert sum(s.duration_s for s in spec.steps) == spec.duration_s
    assert spec.duration_s % 60 == 0
    for step in spec.steps:
        assert step.duration_s % 30 == 0, (step.label, step.duration_s)
        assert "." not in step.label, step.label
    assert "." not in spec.title


def test_labels_use_clock_format():
    session = Session(date=dt.date(2026, 1, 1), kind="RUN_WALK", run_minutes=14,
                      walk_minutes=12, target_run_m=0, purpose="p", effort="easy")
    labels = [s.label for s in build_workout(session, BANDS, "FOUNDATION").steps]
    assert any(label.startswith("Run ") and ":" in label for label in labels)
    assert any(label.startswith("Walk ") and ":" in label for label in labels)


def test_activity_steps_have_no_decimal_minutes(athlete):
    from apps.planning.presenters import activity_card
    from tests.r6_helpers import make_activity

    run = make_activity(athlete, athlete.local_today, blocks=[
        {"duration_s": 222, "kind": "run"}, {"duration_s": 187, "kind": "walk"}])
    labels = [s["label"] for s in activity_card(athlete, run)["steps"]]
    assert labels == ["Run 3:42", "Walk 3:07"]


def test_dynamics_run_blocks_only_and_stride_fallback():
    from analysis.dynamics import DynamicsSample, summarise

    samples = [DynamicsSample(offset_s=t, cadence_spm=160 if t < 10 else 100,
                              speed_mps=3.0 if t < 10 else 1.2, respiration_rate=30)
               for t in range(20)]
    result = summarise(samples, [(0, 10)])
    assert result["max_run_cadence_spm"] == 160
    assert result["avg_stride_length_m"] == round(3.0 * 60 / 160, 2)
    assert result["avg_vertical_oscillation_cm"] is None and result["avg_ground_contact_ms"] is None
    assert result["avg_respiration"] == 30
