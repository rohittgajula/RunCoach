"""Visual action guides (R9 §E): which guides to suggest, from the last 28 days. Pure.

The guides themselves are static frontend content (no AI). This only decides which to
put in "For you", why, and the few numbers the guides fill in (the metronome bpm).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

GUIDES = ("form", "breathing", "strength", "fueling", "warmup")
WINDOW_DAYS = 28
CADENCE_LOW = 160.0
DRIFT_PCT = 5.0
DRIFT_RUNS = 2
RUN_FRACTION_LOW = 0.85
HOT_FEELS_LIKE = 28.0
LONG_RUN_MIN = 60.0
METRONOME_UPLIFT = 0.05
DEFAULT_METRONOME_BPM = 165
METRONOME_MIN, METRONOME_MAX = 140, 200


@dataclass
class GuideInputs:
    cadences: list[float] = field(default_factory=list)       # avg run cadence per run
    hr_drifts: list[float] = field(default_factory=list)      # HR drift % per run
    run_fractions: list[float] = field(default_factory=list)  # 0-1 per run
    runs: int = 0
    smoke_goal: str = "none"
    smoked_recently: bool = False
    feels_like_max: float | None = None                      # today's forecast max
    longest_upcoming_run_min: float | None = None            # planned this week


def _mean(values):
    values = [float(v) for v in values if v is not None]
    return statistics.mean(values) if values else None


def metronome_bpm(cadence_avg: float | None) -> int:
    """Athlete cadence + 5 %, clamped; a sensible default without cadence data."""
    if cadence_avg is None:
        return DEFAULT_METRONOME_BPM
    bpm = round(cadence_avg * (1 + METRONOME_UPLIFT))
    return max(METRONOME_MIN, min(METRONOME_MAX, bpm))


def for_you(inp: GuideInputs) -> list[dict]:
    """[{key, reason, priority}] — deduped (reasons merged with " · ", the best
    priority kept), sorted by priority (1 = most relevant), then guide order."""
    picks: dict[str, dict] = {}

    def add(key: str, reason: str, priority: int):
        pick = picks.setdefault(key, {"key": key, "reasons": [], "priority": priority})
        if reason not in pick["reasons"]:
            pick["reasons"].append(reason)
        pick["priority"] = min(pick["priority"], priority)

    cadence = _mean(inp.cadences)
    if cadence is not None and cadence < CADENCE_LOW:
        add("form", f"Your cadence averages {cadence:.0f} spm", 2)
    drift_runs = sum(1 for d in inp.hr_drifts if d is not None and d > DRIFT_PCT)
    if drift_runs >= DRIFT_RUNS:
        reason = f"Heart rate drifted more than {DRIFT_PCT:.0f}% on {drift_runs} recent runs"
        add("breathing", reason, 1)
        add("fueling", reason, 1)
    if inp.smoke_goal in ("quit", "reduce") or inp.smoked_recently:
        add("breathing", "Breathing practice helps your lungs recover from smoking", 3)
    fraction = _mean(inp.run_fractions)
    if fraction is not None and fraction < RUN_FRACTION_LOW:
        reason = f"You run {fraction * 100:.0f}% of the time on run/walk days"
        add("strength", reason, 2)
        add("breathing", reason, 2)
    if inp.feels_like_max is not None and inp.feels_like_max >= HOT_FEELS_LIKE:
        add("fueling", f"Hot forecast — feels like {inp.feels_like_max:.0f}°C", 2)
    if inp.longest_upcoming_run_min is not None and inp.longest_upcoming_run_min >= LONG_RUN_MIN:
        add("fueling", f"A {inp.longest_upcoming_run_min:.0f}-minute run is coming up this "
                       "week", 2)
    add("warmup", "A short warm-up makes the first kilometre feel easier", 5)
    out = [{"key": p["key"], "reason": " · ".join(p["reasons"]), "priority": p["priority"]}
           for p in picks.values()]
    return sorted(out, key=lambda p: (p["priority"], GUIDES.index(p["key"])))


def context(inp: GuideInputs) -> dict:
    cadence = _mean(inp.cadences)
    fraction = _mean(inp.run_fractions)
    return {
        "window_days": WINDOW_DAYS, "runs": inp.runs,
        "cadence_avg": round(cadence, 1) if cadence is not None else None,
        "metronome_bpm": metronome_bpm(cadence),
        "hr_drift_runs": sum(1 for d in inp.hr_drifts if d is not None and d > DRIFT_PCT),
        "run_fraction_pct": round(fraction * 100, 1) if fraction is not None else None,
        "smoking": inp.smoke_goal in ("quit", "reduce") or inp.smoked_recently,
        "feels_like_max": inp.feels_like_max,
        "longest_upcoming_run_min": inp.longest_upcoming_run_min,
    }


def guides(inp: GuideInputs) -> dict:
    return {"for_you": for_you(inp), "context": context(inp)}
