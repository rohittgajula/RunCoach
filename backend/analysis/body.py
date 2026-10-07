"""Body composition (R10 §B7): merge Garmin weigh-ins with manual entries. Pure."""

from __future__ import annotations

import datetime as dt

from .insights import slope_per_week


def merge(garmin: list[dict], manual: list[dict]) -> list[dict]:
    """One point per day, oldest first; a Garmin weigh-in wins over a manual entry."""
    by_day: dict[dt.date, dict] = {}
    for point in manual:
        by_day[point["date"]] = {**point, "body_fat_pct": None, "source": "manual"}
    for point in garmin:
        by_day[point["date"]] = {**point, "source": "garmin"}
    return [by_day[d] for d in sorted(by_day)]


def change(series: list[dict], key: str) -> float | None:
    values = [p[key] for p in series if p.get(key) is not None]
    return round(values[-1] - values[0], 1) if len(values) >= 2 else None


def trend(series: list[dict]) -> float | None:
    points = [(p["date"], p["weight_kg"]) for p in series if p.get("weight_kg") is not None]
    slope = slope_per_week(points)
    return round(slope, 2) if slope is not None else None
