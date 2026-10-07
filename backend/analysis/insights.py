"""Insights maths (R6 §5): trends, a computed readiness, and the "focus next" rules.

Pure. Everything the Insights tab shows is calculated here or in the Django layer
that gathers rows for it; the model only ever writes a paragraph about the result.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, field

CADENCE_TARGET = (160, 175)
CADENCE_FOCUS_BELOW = 155
EASY_ABOVE_Z2_LIMIT = 0.30
RUN_FRACTION_SLOW_SLOPE = 0.02      # per week
SLEEP_FOCUS_BELOW_H = 7.0
GAP_FOCUS_DAYS = 7
HRV_LOW_DAYS = 3
RESPIRATION_ELEVATED_RPM = 1.0
MAX_FOCUS = 3


def mean(values, digits: int = 1):
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), digits) if present else None


def slope_per_week(points: list[tuple[dt.date, float]]) -> float | None:
    """Least-squares slope, in units per week. None with fewer than 3 points."""
    points = [(d, v) for d, v in points if v is not None]
    if len(points) < 3:
        return None
    origin = points[0][0]
    xs = [(d - origin).days / 7 for d, _ in points]
    ys = [v for _, v in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var


def pace_cv(paces: list[tuple[float, float]]) -> float | None:
    """Coefficient of variation of run-block pace, weighted by block duration.
    paces: (pace_s_per_km, duration_s). Low = even pacing."""
    paces = [(p, d) for p, d in paces if p and d]
    total = sum(d for _, d in paces)
    if len(paces) < 2 or total <= 0:
        return None
    avg = sum(p * d for p, d in paces) / total
    var = sum(d * (p - avg) ** 2 for p, d in paces) / total
    return round((var ** 0.5) / avg, 3) if avg else None


def hrv_status(garmin_status: str | None) -> str | None:
    value = (garmin_status or "").strip().lower()
    return value if value in {"balanced", "unbalanced", "low", "poor"} else None


def readiness_label(score: int | None) -> str:
    if score is None:
        return "Unknown"
    if score >= 75:
        return "High"
    if score >= 50:
        return "Moderate"
    if score >= 25:
        return "Low"
    return "Poor"


def computed_readiness(*, sleep_h: float | None, hrv: float | None,
                       hrv_baseline: tuple[float | None, float | None],
                       resting_hr: float | None, resting_baseline: float | None,
                       form: float | None) -> tuple[int | None, list[str]]:
    """A transparent stand-in when Garmin gives no readiness score.

    Starts at 70 and moves for each signal present; with no signals at all it is None
    rather than a made-up 70.
    """
    score, drivers, used = 70.0, [], 0
    if sleep_h is not None:
        used += 1
        if sleep_h < 6:
            score -= 15
            drivers.append(f"Short sleep ({sleep_h:.1f} h)")
        elif sleep_h < 7:
            score -= 7
            drivers.append(f"Sleep a little short ({sleep_h:.1f} h)")
        else:
            score += 5
            drivers.append(f"Good sleep ({sleep_h:.1f} h)")
    low, high = hrv_baseline
    if hrv is not None and low is not None:
        used += 1
        if hrv < low:
            score -= 15
            drivers.append("HRV below your baseline")
        elif high is not None and hrv <= high:
            score += 5
            drivers.append("HRV within your baseline")
    if resting_hr is not None and resting_baseline is not None:
        used += 1
        if resting_hr >= resting_baseline + 5:
            score -= 10
            drivers.append(f"Resting HR up {round(resting_hr - resting_baseline)} bpm")
    if form is not None:
        used += 1
        if form < -20:
            score -= 10
            drivers.append("Carrying fatigue from recent training")
        elif form > 5:
            score += 5
            drivers.append("Fresh from lighter training")
    if not used:
        return None, []
    return max(0, min(100, round(score))), drivers


@dataclass
class FocusInputs:
    avg_cadence: float | None = None
    easy_above_z2_share: float | None = None
    run_fraction_slope: float | None = None
    avg_run_fraction: float | None = None
    runs: int = 0
    hrv_last_days: list[float | None] = field(default_factory=list)   # newest first
    hrv_baseline_low: float | None = None
    avg_sleep_h: float | None = None
    gap_days: int | None = None
    respiration_recent: list[float | None] = field(default_factory=list)  # newest first
    respiration_baseline: float | None = None
    # R8 §B: smoking days in the last 14 vs the 14 before; the alcohol -> HRV impact row.
    smoke_days_recent: int | None = None
    smoke_days_before: int | None = None
    smoke_streak_days: int | None = None
    alcohol_hrv: dict | None = None


def _item(key, title, why, how) -> dict:
    return {"key": key, "title": title, "why": why, "how": how}


def focus(inputs: FocusInputs) -> list[dict]:
    """Deterministic "what to improve", most urgent first, at most three."""
    items: list[dict] = []

    recent_resp = [v for v in inputs.respiration_recent[:3] if v is not None]
    if (len(recent_resp) >= 2 and inputs.respiration_baseline is not None
            and statistics.mean(recent_resp) >= inputs.respiration_baseline
            + RESPIRATION_ELEVATED_RPM):
        items.append(_item(
            "breathing", "Breathing / possible illness — easy only",
            f"Breathing rate is up {statistics.mean(recent_resp) - inputs.respiration_baseline:.1f}"
            " breaths/min on your baseline — often the first sign of a cold.",
            "Keep runs easy or walk until it settles; rest if you feel unwell."))

    hrv = inputs.hrv_last_days[:HRV_LOW_DAYS]
    if (inputs.hrv_baseline_low is not None and len(hrv) == HRV_LOW_DAYS
            and all(v is not None and v < inputs.hrv_baseline_low for v in hrv)):
        items.append(_item(
            "recovery", "Recovery first",
            f"HRV has been below your baseline for {HRV_LOW_DAYS}+ days.",
            "Swap any hard session for an easy one and protect sleep until it recovers."))

    if inputs.avg_sleep_h is not None and inputs.avg_sleep_h < SLEEP_FOCUS_BELOW_H:
        items.append(_item(
            "sleep", "Sleep",
            f"You are averaging {inputs.avg_sleep_h:.1f} h a night.",
            "Aim for 7–9 h: a fixed bedtime does more for your running than any session."))

    if inputs.gap_days is not None and inputs.gap_days > GAP_FOCUS_DAYS:
        items.append(_item(
            "consistency", "Consistency",
            f"Your last run was {inputs.gap_days} days ago.",
            "Get two or three short, easy runs in this week — regular beats long."))

    if (inputs.easy_above_z2_share is not None
            and inputs.easy_above_z2_share > EASY_ABOVE_Z2_LIMIT):
        items.append(_item(
            "easy_pace", "Slow the easy days down",
            f"{round(inputs.easy_above_z2_share * 100)} % of your easy running was above Z2.",
            "Run slower, walk sooner — if you can't talk in full sentences, it's too fast."))

    items += habit_focus(inputs)

    if inputs.avg_cadence is not None and inputs.avg_cadence < CADENCE_FOCUS_BELOW:
        items.append(_item(
            "cadence", "Shorter, quicker steps",
            f"Your running cadence averages {round(inputs.avg_cadence)} steps/min.",
            f"Aim for {CADENCE_TARGET[0]}–{CADENCE_TARGET[1]}: take shorter steps at the "
            "same effort rather than pushing off harder."))

    if (inputs.runs >= 3 and inputs.run_fraction_slope is not None
            and inputs.run_fraction_slope < RUN_FRACTION_SLOW_SLOPE
            and (inputs.avg_run_fraction or 0) < 0.9):
        items.append(_item(
            "run_blocks", "Extend run blocks by 30–60 s",
            "The share of time you spend running is rising slowly.",
            "Add 30–60 s to each run block next week, keeping the walks the same."))

    return items[:MAX_FOCUS]


def habit_focus(inputs: FocusInputs) -> list[dict]:
    """R8 §B: smoking days rising -> smoke-free streak; alcohol nights with lower HRV
    (enough data only) -> an alcohol item. Association wording, never causation."""
    items = []
    recent, before = inputs.smoke_days_recent, inputs.smoke_days_before
    if recent is not None and before is not None and recent > before:
        streak = inputs.smoke_streak_days or 0
        items.append(_item(
            "smoke_free", "Smoke-free streak",
            f"You smoked on {recent} of the last 14 days, up from {before} the 14 before.",
            f"Your current smoke-free streak is {streak} day{'s' if streak != 1 else ''} — "
            "aim to add one more today; your lungs and easy runs both benefit."))
    row = inputs.alcohol_hrv
    if row and row.get("enough_data") and row.get("direction") == "worse":
        items.append(_item(
            "alcohol", "Alcohol and recovery",
            f"On nights after drinking your HRV was {abs(row['diff']):g} ms lower on "
            f"average (n={row['n_with']} vs {row['n_without']}).",
            "Keep drinks to the nights before rest days, and not the night before a key run."))
    return items
