"""R11 §B: daytime trends over a range — weekly averages, the weekday stress pattern,
the awake-HR slope and the "busy/stressful days vs that night and the next run" card.
Pure: no Django. Association only; nothing here goes to a model.
"""

from __future__ import annotations

import datetime as dt
from statistics import median

from .day import hhmm

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
CAVEAT = "These are patterns in your own data, not causes."
NIGHT_MIN_N = 5
RUN_MIN_N = 3
PATTERN_MIN_DAYS = 2
HR_TREND_MIN_DAYS = 14
HR_FLAT_PER_WEEK = 0.5

AVG_KEYS = ("steps", "active_min", "sedentary_min", "stress_avg", "stress_high_min",
            "awake_hr_avg", "bb_at_bedtime")


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _r(value, digits=0):
    if value is None:
        return None
    return round(value) if digits == 0 else round(value, digits)


def averages(days: list[dict]) -> dict:
    return {k: _r(_mean([d.get(k) for d in days])) for k in AVG_KEYS}


def weeks(days: list[dict]) -> list[dict]:
    """Monday-based weeks, oldest first."""
    groups: dict[dt.date, list[dict]] = {}
    for d in days:
        start = d["date"] - dt.timedelta(days=d["date"].weekday())
        groups.setdefault(start, []).append(d)
    return [{"week_start": start, "n": len(rows),
             "steps_avg": _r(_mean([r.get("steps") for r in rows])),
             "active_min_avg": _r(_mean([r.get("active_min") for r in rows])),
             "stress_avg": _r(_mean([r.get("stress_avg") for r in rows])),
             "awake_hr_avg": _r(_mean([r.get("awake_hr_avg") for r in rows]))}
            for start, rows in sorted(groups.items())]


def slope_per_week(points: list[tuple[dt.date, float]]) -> float | None:
    if len(points) < 2:
        return None
    first = points[0][0]
    xs = [(d - first).days / 7 for d, _ in points]
    ys = [v for _, v in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if not var:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var


def awake_hr_trend(days: list[dict]) -> dict:
    points = [(d["date"], d["awake_hr_avg"]) for d in days if d.get("awake_hr_avg")]
    if len(points) < HR_TREND_MIN_DAYS:
        return {"per_week": None, "direction": None,
                "sentence": f"Awake heart rate needs {HR_TREND_MIN_DAYS} days to show a trend "
                            f"({len(points)} so far)."}
    slope = slope_per_week(points)
    if slope is None:
        return {"per_week": None, "direction": None, "sentence": "Awake heart rate held steady."}
    per_week = round(slope, 1)
    if abs(slope) < HR_FLAT_PER_WEEK:
        return {"per_week": per_week, "direction": "flat",
                "sentence": "Awake heart rate has held steady over this range."}
    direction = "up" if slope > 0 else "down"
    word = "risen" if slope > 0 else "fallen"
    return {"per_week": per_week, "direction": direction,
            "sentence": f"Awake heart rate has {word} about {abs(per_week):g} bpm a week "
                        "over this range."}


def hourly_means(stress: list) -> dict[int, float]:
    by_hour: dict[int, list[int]] = {}
    for m, v in stress:
        by_hour.setdefault(int(m) // 60, []).append(v)
    return {h: sum(v) / len(v) for h, v in by_hour.items()}


def _peak(day_hours: list[dict[int, float]]) -> dict | None:
    if len(day_hours) < PATTERN_MIN_DAYS:
        return None
    merged: dict[int, list[float]] = {}
    for hours in day_hours:
        for h, v in hours.items():
            if 7 <= h < 23:                      # daytime only: night stress is rest
                merged.setdefault(h, []).append(v)
    usable = {h: sum(v) / len(v) for h, v in merged.items() if len(v) >= PATTERN_MIN_DAYS}
    if not usable:
        return None
    # The peak hour, widened to a neighbouring hour within 5 points of it.
    h = max(sorted(usable), key=lambda k: usable[k])
    start, end = h, h + 1
    if usable.get(h + 1, -100) >= usable[h] - 5:
        end = h + 2
    elif usable.get(h - 1, -100) >= usable[h] - 5:
        start = h - 1
    avg = sum(usable[k] for k in range(start, end)) / (end - start)
    return {"start": hhmm(start * 60), "end": hhmm((end % 24) * 60), "avg": round(avg)}


def weekday_pattern(days: list[dict], stress_by_day: dict[dt.date, list]) -> dict:
    rows = []
    for wd in range(7):
        sel = [d for d in days if d["date"].weekday() == wd]
        rows.append({"weekday": wd, "label": WEEKDAYS[wd], "n": len(sel),
                     "steps_avg": _r(_mean([d.get("steps") for d in sel])),
                     "stress_avg": _r(_mean([d.get("stress_avg") for d in sel]))})
    weekday_hours = [hourly_means(s) for d, s in stress_by_day.items() if s and d.weekday() < 5]
    weekend_hours = [hourly_means(s) for d, s in stress_by_day.items() if s and d.weekday() >= 5]
    wk, we = _peak(weekday_hours), _peak(weekend_hours)
    sentence = None
    if wk:
        sentence = f"Stress tends to peak {wk['start']}–{wk['end']} on weekdays"
        sentence += f" and {we['start']}–{we['end']} at weekends." if we else "."
    elif we:
        sentence = f"Stress tends to peak {we['start']}–{we['end']} at weekends."
    return {"by_weekday": rows, "stress_peak_weekdays": wk, "stress_peak_weekends": we,
            "sentence": sentence}


# --- day → night → run ------------------------------------------------------------------

ROWS = (
    # metric, label, unit, source, digits
    ("sleep_score", "Sleep score that night", "", "night", 0),
    ("hrv", "Overnight HRV", "ms", "night", 0),
    ("sleep_h", "Sleep that night", "h", "night", 1),
    ("easy_hr", "HR at easy pace on the next run", "bpm", "run", 0),
    ("efficiency", "Efficiency on the next run", "m/min/bpm", "run", 3),
)
GROUPS = (
    ("stress_avg", "stress", "Stressful vs calmer days", "Stressful days", "Calmer days"),
    ("steps", "steps", "Busy vs quieter days", "Busy days", "Quieter days"),
)


def split_halves(values: list[tuple[dt.date, float]]) -> tuple[list, list, float | None]:
    """Top and bottom half by value (the middle day dropped when odd)."""
    if len(values) < 2:
        return [], [], None
    ordered = sorted(values, key=lambda p: (p[1], p[0]))
    half = len(ordered) // 2
    return ([d for d, _ in ordered[-half:]], [d for d, _ in ordered[:half]],
            float(median(v for _, v in ordered)))


def next_run(day: dt.date, runs: dict[dt.date, dict]) -> dict | None:
    for offset in (1, 2):
        run = runs.get(day + dt.timedelta(days=offset))
        if run:
            return run
    return None


def _row(metric, label, unit, source, digits, high_days, low_days, nights, runs, high_label,
         low_label) -> dict:
    def values(days):
        out = []
        for d in days:
            src = (nights.get(d + dt.timedelta(days=1)) or {}) if source == "night" else \
                (next_run(d, runs) or {})
            v = src.get(metric)
            if v is not None:
                out.append(v)
        return out

    hi, lo = values(high_days), values(low_days)
    need = NIGHT_MIN_N if source == "night" else RUN_MIN_N
    enough = len(hi) >= need and len(lo) >= need
    h, low = _r(_mean(hi), digits), _r(_mean(lo), digits)
    diff = _r(h - low, digits) if enough and h is not None and low is not None else None
    if enough:
        sentence = (f"{label}: {h:g} after {high_label.lower()} vs {low:g} after "
                    f"{low_label.lower()} (n = {len(hi)} vs {len(lo)}).")
    else:
        sentence = (f"{label}: not enough data yet (n = {len(hi)} vs {len(lo)}; "
                    f"{need} each needed).")
    return {"metric": metric, "label": label, "unit": unit,
            "high": h if enough else None, "low": low if enough else None,
            "n_high": len(hi), "n_low": len(lo), "diff": diff, "enough_data": enough,
            "sentence": sentence}


def day_night_run(days: list[dict], nights: dict[dt.date, dict],
                  runs: dict[dt.date, dict]) -> dict:
    """days: [{date, stress_avg, steps}]; nights keyed by the morning the night ended:
    {sleep_score, hrv, sleep_h}; runs keyed by run date: {easy_hr, efficiency}."""
    groups = []
    for key, gkey, label, high_label, low_label in GROUPS:
        values = [(d["date"], d[key]) for d in days if d.get(key) is not None]
        high_days, low_days, split = split_halves(values)
        groups.append({
            "key": gkey, "label": label, "split": split, "high_label": high_label,
            "low_label": low_label, "n_high": len(high_days), "n_low": len(low_days),
            "rows": [_row(m, lab, unit, src, dig, high_days, low_days, nights, runs,
                          high_label, low_label) for m, lab, unit, src, dig in ROWS],
        })
    return {"caveat": CAVEAT, "groups": groups}
