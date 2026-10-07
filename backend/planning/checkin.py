"""The morning check-in: "Rest or train?" (R7 §1). Pure — no Django.

`decide(snapshot, workout)` reads last night's signals against the athlete's own
baseline and returns a verdict plus what today's session would become. Like
readiness.py it only ever makes a session easier, and missing data never counts
against the athlete: a signal that is absent is listed in `signals_missing`, never
scored "bad".

Rules (deterministic, in this order):
    pain or illness in the journal (last 3 days)  -> rest
    >= 2 "bad" signals                             -> swap
    1 "bad" or >= 2 "watch"                        -> easy
    otherwise                                      -> go
No workout today -> no_plan (signals still reported).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from analysis.load import session_load

from .readiness import WellnessSnapshot

SLEEP_BAD_H = 6.0
SLEEP_WATCH_H = 7.0
RHR_BAD_DELTA = 7
RHR_WATCH_DELTA = 4
BODY_BATTERY_BAD = 30
BODY_BATTERY_WATCH = 50
READINESS_BAD = 25
READINESS_WATCH = 50
ACWR_WATCH = 1.5
RPE_WATCH = 8
EASY_HR_DROP = 5
# R8: drinks yesterday (standard drinks) and air quality (US AQI).
ALCOHOL_WATCH, ALCOHOL_BAD = 3, 5
AQI_WATCH, AQI_BAD = 100, 200
MIN_BASELINE_DAYS = 7
# Only when Garmin has no HRV baseline band yet: a drop this far under the athlete's
# own recent average is a "watch" (never "bad" — the spec's bad rule needs Garmin's band).
HRV_FALLBACK_DROP = 0.12
WALK_MIN_S, WALK_MAX_S = 20 * 60, 30 * 60
GRID_S = 30

HEADLINES = {
    "go": "Go as planned",
    "easy": "Keep it easy today",
    "swap": "Swap for a walk",
    "rest": "Rest today",
    "no_plan": "No session today",
}
NO_PLAN_NOTE = ("Nothing is planned today. Recovery is part of training — an easy "
                "20-min walk keeps you moving without adding load.")
REST_NOTE = "Rest today. If you want to move, keep it to a gentle walk."
STATUS_ORDER = {"bad": 0, "watch": 1, "good": 2}
HARD_KINDS = {"INTERVALS", "TEMPO"}


@dataclass(frozen=True)
class WorkoutSummary:
    """The parts of a PlannedWorkout the check-in needs."""

    title: str
    kind: str
    duration_s: int
    steps: list[dict] = field(default_factory=list)
    target_zone: str | None = None
    easy_pace: tuple[int, int] | None = None
    hr_easy: tuple[int, int] | None = None


@dataclass
class Verdict:
    verdict: str
    headline: str
    reasons: list[dict]
    signals_missing: list[str]
    adjusted: dict | None
    note: str | None = None

    @property
    def counts(self) -> tuple[int, int]:
        bad = sum(1 for r in self.reasons if r["status"] == "bad")
        watch = sum(1 for r in self.reasons if r["status"] == "watch")
        return bad, watch


def _reason(signal, status, label, value=None, baseline=None) -> dict:
    return {"signal": signal, "status": status, "label": label, "value": value,
            "baseline": baseline}


def _hm(hours: float) -> str:
    minutes = int(round(hours * 60))
    return f"{minutes // 60}h {minutes % 60:02d}m"


def signals(s: WellnessSnapshot) -> tuple[list[dict], list[str]]:
    """(reasons, signals_missing). Reasons are sorted bad -> watch -> good."""
    reasons: list[dict] = []
    missing: list[str] = []

    if s.pain_reported:
        reasons.append(_reason("pain", "bad", "Pain reported in the last 3 days", True))
    if s.illness_reported:
        reasons.append(_reason("illness", "bad", "Feeling unwell in the last 3 days", True))

    if s.sleep_hours is None:
        missing.append("sleep")
    else:
        h = s.sleep_hours
        status = "bad" if h < SLEEP_BAD_H else "watch" if h < SLEEP_WATCH_H else "good"
        reasons.append(_reason("sleep", status, f"Sleep {_hm(h)}", round(h, 2)))

    if s.hrv is None:
        missing.append("hrv")
    elif s.hrv_baseline_low is not None:
        status = "bad" if s.hrv < s.hrv_baseline_low else "good"
        reasons.append(_reason("hrv", status, f"HRV {s.hrv} ms", s.hrv, s.hrv_baseline_low))
    elif len(s.hrv_baseline) >= MIN_BASELINE_DAYS:
        mean = statistics.mean(s.hrv_baseline)
        status = "watch" if s.hrv < mean * (1 - HRV_FALLBACK_DROP) else "good"
        reasons.append(_reason("hrv", status, f"HRV {s.hrv} ms", s.hrv, round(mean)))
    else:
        missing.append("hrv")              # a value with nothing to compare it to

    if s.resting_hr is None or len(s.resting_hr_baseline) < MIN_BASELINE_DAYS:
        missing.append("rhr")
    else:
        base = statistics.mean(s.resting_hr_baseline)
        delta = s.resting_hr - base
        status = ("bad" if delta >= RHR_BAD_DELTA else
                  "watch" if delta >= RHR_WATCH_DELTA else "good")
        reasons.append(_reason("rhr", status, f"Resting HR {s.resting_hr} bpm",
                               s.resting_hr, round(base, 1)))

    if s.body_battery_high is None:
        missing.append("body_battery")
    else:
        b = s.body_battery_high
        status = "bad" if b < BODY_BATTERY_BAD else "watch" if b < BODY_BATTERY_WATCH else "good"
        reasons.append(_reason("body_battery", status, f"Body Battery {b}", b))

    if s.readiness is None:
        missing.append("readiness")
    else:
        r = s.readiness
        status = "bad" if r < READINESS_BAD else "watch" if r < READINESS_WATCH else "good"
        reasons.append(_reason("readiness", status, f"Training readiness {r}", r))

    if s.acwr is None:
        missing.append("load")
    else:
        status = "watch" if s.acwr > ACWR_WATCH else "good"
        reasons.append(_reason("load", status, f"Load ratio {s.acwr:.2f}", round(s.acwr, 2),
                               1.0))

    # Yesterday's post-run check-in. No run yesterday is not "missing" data.
    if s.last_rpe is not None:
        status = "watch" if s.last_rpe >= RPE_WATCH else "good"
        reasons.append(_reason("rpe", status, f"Yesterday's run felt {s.last_rpe}/10",
                               s.last_rpe))

    reasons += _r8_signals(s)
    reasons.sort(key=lambda r: STATUS_ORDER[r["status"]])
    return reasons, missing


def _r8_signals(s: WellnessSnapshot) -> list[dict]:
    """Alcohol, heat, air (R8). Only ever watch/bad — none is reported as "good" and none
    counts as missing, so they can only make the verdict easier."""
    out = []
    drinks = s.drinks_yesterday
    if drinks is not None and drinks >= ALCOHOL_WATCH:
        status = "bad" if drinks >= ALCOHOL_BAD else "watch"
        out.append(_reason("alcohol", status, f"{drinks:g} drinks last night", drinks))
    if s.heat_hot:
        bits = [f"feels like {s.heat_feels_like:.0f}°C" if s.heat_feels_like is not None
                else None,
                f"dew point {s.heat_dew_point:.0f}°C" if s.heat_dew_point is not None else None]
        label = "Hot today" + (": " + " · ".join(b for b in bits if b) if any(bits) else "")
        out.append(_reason("heat", "watch", label, s.heat_feels_like))
    if s.aqi is not None and s.aqi > AQI_WATCH:
        status = "bad" if s.aqi > AQI_BAD else "watch"
        out.append(_reason("air", status, f"Air quality AQI {s.aqi:.0f}", s.aqi))
    return out


def verdict_for(reasons: list[dict], has_workout: bool) -> str:
    if not has_workout:
        return "no_plan"
    if any(r["signal"] in ("pain", "illness") and r["status"] == "bad" for r in reasons):
        return "rest"
    bad = sum(1 for r in reasons if r["status"] == "bad")
    watch = sum(1 for r in reasons if r["status"] == "watch")
    if bad >= 2:
        return "swap"
    if bad == 1 or watch >= 2:
        return "easy"
    return "go"


def _clock(seconds: int) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _workout_like(title, kind, steps, target_zone, description) -> dict:
    run_s = sum(s["duration_s"] for s in steps if s.get("intensity") != "walk")
    walk_s = sum(s["duration_s"] for s in steps if s.get("intensity") == "walk")
    return {"title": title, "kind": kind, "duration_s": run_s + walk_s,
            "load": session_load(run_s / 60, walk_s / 60), "steps": steps,
            "target_zone": target_zone, "description": description}


def _eased_steps(w: WorkoutSummary) -> list[dict]:
    """Every hard/moderate/stride block becomes easy; every HR cap drops 5 bpm."""
    out = []
    for raw in w.steps:
        step = dict(raw)
        if step.get("intensity") in ("moderate", "hard"):
            step["intensity"] = "easy"
            if step.get("kind") in ("interval", "stride"):
                step["kind"] = "run"
            step["label"] = f"Easy {_clock(step['duration_s'])}"
            pace, hr = w.easy_pace, w.hr_easy
            step["pace_min_s"], step["pace_max_s"] = pace if pace else (None, None)
            step["hr_min"], step["hr_max"] = hr if hr else (None, None)
        if step.get("hr_max"):
            step["hr_max"] = step["hr_max"] - EASY_HR_DROP
            if step.get("hr_min") and step["hr_min"] > step["hr_max"]:
                step["hr_min"] = step["hr_max"]
        out.append(step)
    return out


def _easy(w: WorkoutSummary) -> dict | None:
    steps = _eased_steps(w)
    if steps == list(w.steps):
        return None                       # nothing to ease (a walk, say)
    hardened = any(s.get("intensity") in ("moderate", "hard") for s in w.steps)
    kind = "EASY" if w.kind in HARD_KINDS else w.kind
    if hardened:
        title = f"{round(w.duration_s / 60)}m easy run"
    else:
        title = w.title
    zone = "Z2" if hardened else w.target_zone
    return _workout_like(title, kind, steps, zone,
                         "Same time on your feet, all of it easy, HR cap 5 bpm lower.")


def _half(w: WorkoutSummary) -> dict:
    steps = []
    for step in _eased_steps(w):
        seconds = int(step["duration_s"] / 2 // GRID_S) * GRID_S
        if seconds <= 0:
            continue
        step = dict(step, duration_s=seconds)
        if step.get("intensity") == "walk":
            step["label"] = f"Walk {_clock(seconds)}"
        else:
            step["label"] = f"Run {_clock(seconds)}"
        steps.append(step)
    total = sum(s["duration_s"] for s in steps)
    return _workout_like(f"{round(total / 60)}m run/walk (shortened)", "RUN_WALK", steps,
                         "Z2", "Half the planned session, all easy, walk whenever you like.")


def _walk(w: WorkoutSummary) -> dict:
    seconds = min(WALK_MAX_S, max(WALK_MIN_S, int(round(w.duration_s / 60)) * 60))
    step = {"kind": "walk", "duration_s": seconds, "intensity": "walk",
            "label": f"Brisk walk {_clock(seconds)}", "pace_min_s": None,
            "pace_max_s": None, "hr_min": None, "hr_max": None}
    return _workout_like(f"{seconds // 60}m brisk walk", "WALK", [step], None,
                         "Brisk walk instead of the run. Movement, not training.")


def _rest() -> dict:
    return {"title": "Rest day", "kind": "REST", "duration_s": 0, "load": 0.0,
            "steps": [], "target_zone": None,
            "description": "No session today. Recover first."}


def adjusted_for(verdict: str, w: WorkoutSummary | None, mild: bool = False) -> dict | None:
    """What `verdict` turns today's workout into. None when nothing changes.

    A race is never rewritten automatically — the verdict and reasons still show.
    """
    if w is None or verdict in ("go", "no_plan") or w.kind == "RACE":
        return None
    if verdict == "rest":
        return _rest()
    if verdict == "swap":
        if w.kind == "WALK":
            return None
        return _half(w) if mild else _walk(w)
    return _easy(w)


def decide(snapshot: WellnessSnapshot, workout: WorkoutSummary | None) -> Verdict:
    reasons, missing = signals(snapshot)
    verdict = verdict_for(reasons, workout is not None)
    bad = sum(1 for r in reasons if r["status"] == "bad")
    watch = sum(1 for r in reasons if r["status"] == "watch")
    # "Only mildly flagged": exactly two bad signals and nothing else amiss.
    mild = verdict == "swap" and bad == 2 and watch == 0
    note = NO_PLAN_NOTE if verdict == "no_plan" else REST_NOTE if verdict == "rest" else None
    return Verdict(verdict=verdict, headline=HEADLINES[verdict], reasons=reasons,
                   signals_missing=missing, adjusted=adjusted_for(verdict, workout, mild),
                   note=note)
