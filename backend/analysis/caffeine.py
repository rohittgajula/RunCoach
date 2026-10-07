"""Caffeine (R13 §9): amounts and late caffeine vs that night's sleep. Pure.

A "late" day has a caffeine log at or after 14:00 local. Its night is the sleep that
ended the next morning (Garmin dates a night by the morning it ends, so the metric row
dated the day after). Late days are compared with caffeine-free-after-14:00 days in the
same period (days from the first caffeine log on), the R9 way: means, n each side,
"better / worse / no clear difference" past a threshold, and only with ≥ 4 nights each.
Association only.
"""

from __future__ import annotations

import datetime as dt
import statistics

LATE_HOUR = 14
MIN_N = 4
TYPES = ("coffee", "tea", "energy", "other")
# metric -> (label, unit, threshold, higher is better)
METRICS = {
    "sleep_score": ("Sleep score", "", 3.0, True),
    "deep_sleep_min": ("Deep sleep", "min", 8.0, True),
    "awake_min": ("Awake time in the night", "min", 5.0, False),
}
CAVEAT = ("Association, not proof: days with late caffeine may differ in other ways "
          "(work, stress, a late night). Garmin has no sleep-latency number, so 'awake "
          "time in the night' stands in for how long it took to settle.")


def amounts(logs: list[tuple[dt.date, int, float, str | None]], start: dt.date,
            end: dt.date) -> dict:
    """logs: (local_date, local hour, cups, subtype)."""
    inside = [l for l in logs if start <= l[0] <= end]
    by_day: dict[dt.date, dict] = {}
    by_type = {t: 0.0 for t in TYPES}
    for day, hour, cups, subtype in inside:
        row = by_day.setdefault(day, {"count": 0.0, "late": False})
        row["count"] += cups
        row["late"] = row["late"] or hour >= LATE_HOUR
        by_type[subtype if subtype in TYPES else "other"] += cups
    first = min((l[0] for l in logs), default=None)
    total = round(sum(l[2] for l in inside), 1)
    days = None
    if first is not None and first <= end:
        days = (end - max(start, first)).days + 1
    series = []
    if first is not None:
        day = max(start, first)
        while day <= end:
            row = by_day.get(day, {"count": 0.0, "late": False})
            series.append({"date": day, "count": round(row["count"], 1), "late": row["late"]})
            day += dt.timedelta(days=1)
    return {"total": total,
            "per_day_avg": round(total / days, 1) if days else None,
            "by_type": {k: round(v, 1) for k, v in by_type.items()},
            "late_days": sum(1 for r in by_day.values() if r["late"]),
            "series": series}


def _sentence(label, unit, late_avg, other_avg, direction, enough, n_late, n_other) -> str:
    if not enough:
        return (f"{label}: not enough nights yet ({n_late} after late caffeine, "
                f"{n_other} without; need {MIN_N} each).")
    if direction == "no_clear_difference":
        return f"{label}: no clear difference after late caffeine."
    unit = f" {unit}" if unit else ""
    return (f"{label} was {late_avg:g}{unit} after days with caffeine after 14:00 vs "
            f"{other_avg:g}{unit} without ({n_late} vs {n_other} nights).")


def impact(series: list[dict], nights: dict[dt.date, dict]) -> list[dict]:
    """series: amounts()['series']; nights: metric-row date -> {sleep_score,
    deep_sleep_min, awake_min}. Only days before the last night we have."""
    rows = []
    for metric, (label, unit, threshold, higher_better) in METRICS.items():
        late, other = [], []
        for point in series:
            night = nights.get(point["date"] + dt.timedelta(days=1))
            value = night.get(metric) if night else None
            if value is None:
                continue
            (late if point["late"] else other).append(value)
        enough = len(late) >= MIN_N and len(other) >= MIN_N
        late_avg = round(statistics.mean(late), 1) if late else None
        other_avg = round(statistics.mean(other), 1) if other else None
        diff = round(late_avg - other_avg, 1) if late_avg is not None and other_avg is not None \
            else None
        direction = "no_clear_difference"
        if enough and diff is not None and abs(diff) >= threshold:
            direction = "better" if (diff > 0) == higher_better else "worse"
        rows.append({"metric": metric, "label": label, "unit": unit, "late_avg": late_avg,
                     "other_avg": other_avg, "diff": diff, "n_late": len(late),
                     "n_other": len(other), "direction": direction, "enough_data": enough,
                     "sentence": _sentence(label, unit, late_avg, other_avg, direction,
                                           enough, len(late), len(other))})
    return rows
