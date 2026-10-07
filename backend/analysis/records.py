"""Personal records (R10 §B6). Garmin's PR list mapped to our keys, plus our own
computed bests, formatted for display. Pure."""

from __future__ import annotations

import datetime as dt

NEW_DAYS = 14

# Garmin PR typeId -> (key, label, unit). Others (cycling, steps, swim) are ignored.
GARMIN_TYPES = {
    1: ("1k", "1 km", "s"),
    2: ("mile", "1 mile", "s"),
    3: ("5k", "5 km", "s"),
    4: ("10k", "10 km", "s"),
    5: ("half", "Half marathon", "s"),
    6: ("marathon", "Marathon", "s"),
    7: ("longest_run", "Longest run", "m"),
}
GARMIN_ORDER = [v[0] for v in GARMIN_TYPES.values()]
COMPUTED = {
    "fastest_1k": ("Fastest 1 km split", "s"),
    "longest_distance": ("Longest distance", "m"),
    "longest_continuous": ("Longest unbroken run", "s"),
}


def duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def display(value: float | None, unit: str) -> str | None:
    if value is None:
        return None
    if unit == "m":
        return f"{value / 1000:.1f} km"
    return duration(value)


def _date(entry: dict) -> dt.date | None:
    raw = (entry.get("activityStartDateTimeLocalFormatted")
           or entry.get("prStartTimeLocalFormatted")
           or entry.get("actStartDateTimeInGMTFormatted")
           or entry.get("prStartTimeGmtFormatted") or "")
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def parse_garmin(payload) -> list[dict]:
    """Garmin's get_personal_record() list -> [{key, label, unit, value, date,
    garmin_activity_id}] for the running types only. Bad entries are skipped."""
    out = []
    for entry in payload if isinstance(payload, list) else []:
        if not isinstance(entry, dict):
            continue
        kind = GARMIN_TYPES.get(entry.get("typeId"))
        try:
            value = float(entry.get("value"))
        except (TypeError, ValueError):
            continue
        if kind is None or value <= 0:
            continue
        key, label, unit = kind
        activity = entry.get("activityId")
        out.append({"key": key, "label": label, "unit": unit, "value": round(value, 1),
                    "date": _date(entry),
                    "garmin_activity_id": int(activity) if activity else None})
    return out


def is_new(day: dt.date | None, today: dt.date) -> bool:
    return day is not None and (today - day).days < NEW_DAYS and day <= today


def computed(runs: list[dict]) -> list[dict]:
    """Our own bests from run dicts ({id, date, fastest_1k_s, total_km,
    longest_run_s}). Each record: the best value and the first run that set it."""
    out = []
    specs = [("fastest_1k", "fastest_1k_s", True, 1.0),
             ("longest_distance", "total_km", False, 1000.0),
             ("longest_continuous", "longest_run_s", False, 1.0)]
    for key, field, lowest, scale in specs:
        best = None
        for run in runs:
            value = run.get(field)
            if not value:
                continue
            if best is None or (value < best[field] if lowest else value > best[field]):
                best = run
        if best is None:
            continue
        label, unit = COMPUTED[key]
        out.append({"key": key, "label": label, "unit": unit,
                    "value": round(best[field] * scale, 1),
                    "date": dt.date.fromisoformat(best["date"]), "activity_id": best["id"]})
    return out
