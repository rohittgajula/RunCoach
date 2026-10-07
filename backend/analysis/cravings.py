"""Quit-smoking support (R13 §8): craving patterns and the savings goal. Pure.

A craving is "resisted" when the athlete did not smoke because of it. Patterns are
counts only — top triggers, hours and places — over the chosen period, with the same
length of time just before it as the trend's comparison.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

TRIGGERS = {"coffee": "Coffee", "alcohol": "Alcohol", "stress": "Stress",
            "after_meal": "After a meal", "boredom": "Boredom", "social": "Social",
            "work_break": "Work break", "morning": "Morning", "other": "Other"}
TOP_PLACES = 5
PEAK_HOURS = 3
FLAT_PCT = 10


@dataclass(frozen=True)
class Craving:
    local_date: dt.date
    hour: int
    intensity: int
    trigger: str
    place: str
    smoked: bool


def summary(rows: list[Craving], start: dt.date, end: dt.date, prev_start: dt.date,
            prev_end: dt.date) -> dict:
    now = [r for r in rows if start <= r.local_date <= end]
    before = [r for r in rows if prev_start <= r.local_date <= prev_end]
    total = len(now)
    resisted = sum(1 for r in now if not r.smoked)
    by_trigger = []
    for key, label in TRIGGERS.items():
        hits = [r for r in now if r.trigger == key]
        if hits:
            by_trigger.append({"trigger": key, "label": label, "count": len(hits),
                               "resisted": sum(1 for r in hits if not r.smoked)})
    by_trigger.sort(key=lambda t: (-t["count"], list(TRIGGERS).index(t["trigger"])))
    hours = [0] * 24
    for r in now:
        hours[r.hour % 24] += 1
    places: dict[str, int] = {}
    for r in now:
        name = (r.place or "").strip()
        if name:
            key = name.lower()
            places[key] = places.get(key, 0) + 1
    display = {}
    for r in now:
        if (r.place or "").strip():
            display.setdefault(r.place.strip().lower(), r.place.strip())
    top_places = sorted(({"place": display[k], "count": c} for k, c in places.items()),
                        key=lambda p: (-p["count"], p["place"]))[:TOP_PLACES]
    peak = sorted(({"hour": h, "count": c} for h, c in enumerate(hours) if c),
                  key=lambda p: (-p["count"], p["hour"]))[:PEAK_HOURS]
    change_pct = direction = None
    if before:
        change_pct = round((total - len(before)) / len(before) * 100)
        direction = "flat" if abs(change_pct) < FLAT_PCT else ("down" if change_pct < 0 else "up")
    elif total:
        direction = "up"
    intensities = [r.intensity for r in now]
    return {
        "total": total, "resisted": resisted,
        "resisted_pct": round(resisted / total * 100) if total else None,
        "avg_intensity": round(sum(intensities) / len(intensities), 1) if intensities else None,
        "by_trigger": by_trigger,
        "by_hour": [{"hour": h, "count": c} for h, c in enumerate(hours)],
        "top_places": top_places, "peak_hours": peak,
        "trend": {"this_period": total, "previous_period": len(before),
                  "change_pct": change_pct, "direction": direction},
    }


def savings(name: str, amount: float | None, saved: float | None, days_since_quit: int | None,
            today: dt.date) -> dict | None:
    """Progress towards the goal from the R8 money saved since the quit date; ETA at the
    average saving per day so far."""
    if not name or not amount:
        return None
    saved = round(saved or 0.0, 2)
    remaining = round(max(amount - saved, 0.0), 2)
    per_day = round(saved / days_since_quit, 2) if days_since_quit and saved > 0 else None
    eta = None
    if remaining <= 0:
        eta = today
    elif per_day:
        eta = today + dt.timedelta(days=math.ceil(remaining / per_day))
    return {"name": name, "amount": amount, "saved": saved, "remaining": remaining,
            "pct": min(100, round(saved / amount * 100)) if amount else 0,
            "reached": remaining <= 0, "per_day": per_day, "eta": eta}


RESISTED_TARGETS = [(1, "First craving beaten", "Didn't smoke through a craving."),
                    (10, "10 cravings beaten", "Rode out ten cravings without smoking."),
                    (50, "50 cravings beaten", "Fifty cravings resisted."),
                    (100, "100 cravings beaten", "A hundred cravings resisted.")]


def resisted_milestones(resisted_dates: list[dt.date]) -> tuple[dict[int, dt.date], int]:
    """(target -> date reached, count) for the achievements catalogue."""
    ordered = sorted(resisted_dates)
    reached = {t: ordered[t - 1] for t, _, _ in RESISTED_TARGETS if len(ordered) >= t}
    return reached, len(ordered)
