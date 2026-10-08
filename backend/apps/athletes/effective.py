"""R18 §B: effective settings — override > Garmin > default, in one place.

Every calculation that needs the athlete's sleep need or usual run time reads it here,
so a value set in Settings (or applied from memory / chat) changes every screen at once.
"""

from __future__ import annotations

import datetime as dt
import statistics

DEFAULT_SLEEP_NEED_S = 8 * 3600
GARMIN_NIGHTS = 7


def _hours(minutes: int) -> str:
    h, m = divmod(int(round(minutes)), 60)
    return f"{h} h" if not m else f"{h} h {m:02d} min" if h else f"{m} min"


def garmin_sleep_need_s(athlete, today: dt.date | None = None) -> int | None:
    """Median of Garmin's sleep need over the last 7 days that have one."""
    from apps.ingest.models import DailyMetrics

    today = today or athlete.local_today
    values = [v for v in DailyMetrics.objects.filter(
        athlete=athlete, metric_date__gt=today - dt.timedelta(days=GARMIN_NIGHTS),
        metric_date__lte=today, sleep_need_seconds__isnull=False)
        .values_list("sleep_need_seconds", flat=True) if v]
    return round(statistics.median(values)) if values else None


def sleep_need(athlete, garmin_s=None) -> dict:
    """{seconds, minutes, source: memory|user|garmin|default, garmin_minutes, label,
    fact_id}. Memory fact vs app setting: the more recent wins (profile_params)."""
    from .profile_params import resolve

    eff = resolve(athlete, "sleep_need_minutes")
    source = {"memory": "memory", "setting": "user", "garmin": "garmin",
              "default": "default"}[eff["source"]]
    minutes = int(eff["value"] or DEFAULT_SLEEP_NEED_S // 60)
    suffix = {"memory": "from memory", "user": "set by you", "garmin": "Garmin",
              "default": "default"}[source]
    garmin_min = eff["garmin_value"]
    return {"seconds": minutes * 60, "minutes": minutes, "source": source,
            "garmin_minutes": garmin_min, "label": f"{_hours(minutes)} ({suffix})",
            "fact_id": eff["fact_id"]}


def sleep_need_s(athlete) -> int:
    return sleep_need(athlete)["seconds"]


def override_s(need: dict) -> int | None:
    """The athlete's own need (memory or setting), else None (= use Garmin's per night)."""
    return need["seconds"] if need["source"] in ("memory", "user") else None


def night_need_s(need: dict, garmin_night_s: int | None) -> int | None:
    """One night's need: the athlete's own value when set, else Garmin's for that night."""
    return override_s(need) or garmin_night_s


def usual_run_minute(athlete) -> int | None:
    from .profile_params import effective_value

    value = effective_value(athlete, "usual_run_time")
    if not value:
        return None
    hour, minute = str(value)[:5].split(":")
    return int(hour) * 60 + int(minute)


def loop_distance_km(athlete) -> float | None:
    from .profile_params import effective_value

    value = effective_value(athlete, "loop_distance_km")
    return float(value) if value else None


def hours_label(minutes: int | None) -> str:
    return _hours(minutes) if minutes else "—"
