"""Long-term goals (R14 §8): progress, milestones and a projected date. Pure.

Progress is the share of the way from the start value to the target, in whichever
direction the goal points (a weight or race-time goal goes down). The projection is a
least-squares line over the recent values and is always labelled an estimate.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

MILESTONES = (25, 50, 75, 100)
PROJECTION_DAYS = 60
MIN_POINTS = 3
MIN_SPAN_DAYS = 14
MAX_YEARS = 3

KINDS = {
    # kind: (unit, title template)
    "race_time": ("s", "{distance} in {target}"),
    "distance": ("km", "Run {target} km"),
    "weight": ("kg", "Reach {target} kg"),
    "smoke_free_days": ("days", "{target} days smoke-free"),
    "vo2max": ("ml/kg/min", "VO2max {target}"),
    "resting_hr": ("bpm", "Resting HR {target} bpm"),
    "weekly_km": ("km", "{target} km a week"),
    "custom": ("", "{target}"),
}
RACE_DISTANCES = {5.0: "5K", 10.0: "10K", 21.1: "Half marathon", 42.2: "Marathon"}


def clock(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def display(kind: str, value: float | None, unit: str = "") -> str | None:
    if value is None:
        return None
    if kind == "race_time":
        return clock(value)
    if kind in ("smoke_free_days",):
        return f"{int(value)} days"
    if kind in ("weight", "distance", "weekly_km"):
        return f"{value:.1f} {unit}".strip()
    if kind == "vo2max":
        return f"{value:.0f}"
    if kind == "resting_hr":
        return f"{value:.0f} bpm"
    return f"{value:g} {unit}".strip()


def direction(start: float | None, target: float, kind: str) -> str:
    if kind in ("race_time", "resting_hr") and start is None:
        return "down"
    if start is None:
        return "up"
    return "down" if target < start else "up"


def progress_pct(start: float | None, current: float | None, target: float,
                 way: str) -> int | None:
    if current is None:
        return None
    if start is None or start == target:
        reached = current <= target if way == "down" else current >= target
        return 100 if reached else 0
    share = (current - start) / (target - start)
    return int(max(0, min(100, round(share * 100))))


def milestone_value(start: float, target: float, pct: int) -> float:
    return start + (target - start) * pct / 100


def reached_on(series: list[tuple[dt.date, float]], start: float | None, target: float,
               way: str) -> dict[int, dt.date | None]:
    """The first date each milestone was reached, from the value series."""
    out: dict[int, dt.date | None] = {pct: None for pct in MILESTONES}
    for day, value in sorted(series):
        pct = progress_pct(start, value, target, way)
        if pct is None:
            continue
        for m in MILESTONES:
            if out[m] is None and pct >= m:
                out[m] = day
    return out


@dataclass(frozen=True)
class Projection:
    date: dt.date | None
    method: str | None
    on_track: bool | None
    note: str


def project(series: list[tuple[dt.date, float]], target: float, way: str, today: dt.date,
            target_date: dt.date | None = None) -> Projection:
    recent = [(d, v) for d, v in series if (today - d).days <= PROJECTION_DAYS]
    if len(recent) < MIN_POINTS or (max(d for d, _ in recent)
                                    - min(d for d, _ in recent)).days < MIN_SPAN_DAYS:
        return Projection(None, None, None,
                          "Not enough recent data for an estimate yet "
                          f"(needs {MIN_POINTS}+ values over {MIN_SPAN_DAYS}+ days).")
    origin = min(d for d, _ in recent)
    xs = [(d - origin).days for d, _ in recent]
    ys = [v for _, v in recent]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    current = my + slope * ((today - origin).days - mx)
    done = current <= target if way == "down" else current >= target
    if done:
        return Projection(today, "trend", True if target_date else None,
                          "At your current trend you're there now (estimate).")
    moving = slope < 0 if way == "down" else slope > 0
    if not moving or slope == 0:
        return Projection(None, "trend", False if target_date else None,
                          "Your recent trend isn't moving towards the target yet.")
    days = (target - current) / slope
    if days > MAX_YEARS * 365:
        return Projection(None, "trend", False if target_date else None,
                          "At the current pace of change this is more than 3 years away.")
    when = today + dt.timedelta(days=int(round(days)))
    on_track = when <= target_date if target_date else None
    note = f"Estimate from your last {PROJECTION_DAYS} days' trend — it will move."
    return Projection(when, "trend", on_track, note)
