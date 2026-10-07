"""Habits maths (R8 §B): series, streaks, quit savings, milestones and the impact of a
habit on the next morning's numbers. Pure — dates and numbers in, dicts out.

Impact is association, never causation: "on nights after drinking your HRV was X lower
on average (n=…)". A comparison is only `enough_data` with >= 5 nights in each group,
and only a difference past a meaningful threshold gets a direction.
"""

from __future__ import annotations

import datetime as dt
import statistics

MIN_N = 5
# metric -> (label, unit, threshold, threshold is relative?, higher is better?)
METRICS = {
    "hrv": ("Overnight HRV", "ms", 0.05, True, True),
    "rhr": ("Resting HR", "bpm", 2.0, False, False),
    "sleep_score": ("Sleep score", "", 3.0, False, True),
    "body_battery": ("Body Battery high", "", 5.0, False, True),
    "stress": ("Average stress", "", 3.0, False, False),
    "sleep_respiration": ("Sleep breathing rate", "brpm", 0.5, False, False),
    # Runs on the day after: lower HR at easy pace / higher efficiency / lower drift = better.
    "easy_hr": ("HR on easy runs", "bpm", 2.0, False, False),
    "efficiency": ("Efficiency (speed ÷ HR)", "m/min/bpm", 0.03, True, True),
    "hr_drift": ("HR drift", "%", 1.0, False, False),
}
HABIT_WORDS = {"smoke": "smoking", "alcohol": "drinking", "sugar": "sugary food"}

# General public-health timeline after the last cigarette, shown as "typically".
MILESTONES = [
    (dt.timedelta(minutes=20), "20 minutes: heart rate and blood pressure typically start "
                               "to come down"),
    (dt.timedelta(hours=12), "12 hours: carbon monoxide in the blood typically falls to "
                             "normal"),
    (dt.timedelta(hours=24), "24 hours: nicotine is typically mostly out of the blood"),
    (dt.timedelta(hours=48), "48 hours: taste and smell typically start to improve"),
    (dt.timedelta(weeks=2), "2 weeks: circulation and lung function typically begin to "
                            "improve"),
    (dt.timedelta(days=30), "1 month: coughing and shortness of breath typically ease"),
    (dt.timedelta(days=90), "3 months: lung function typically keeps improving — "
                            "running feels easier"),
    (dt.timedelta(days=365), "1 year: the extra risk of heart disease is typically about "
                             "half a smoker's"),
]


def daily_totals(logs: list[tuple[dt.date, float]]) -> dict[dt.date, float]:
    out: dict[dt.date, float] = {}
    for day, qty in logs:
        out[day] = out.get(day, 0.0) + float(qty or 0)
    return out


def series(totals: dict[dt.date, float], start: dt.date, end: dt.date) -> list[dict]:
    days = (end - start).days + 1
    return [{"date": (start + dt.timedelta(days=i)).isoformat(),
             "count": round(totals.get(start + dt.timedelta(days=i), 0.0), 2)}
            for i in range(max(days, 0))]


def trend_per_week(points: list[dict]) -> float | None:
    """Least-squares slope of the daily count, per week (negative = cutting down)."""
    if len(points) < 3:
        return None
    xs = list(range(len(points)))
    ys = [p["count"] for p in points]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if not var:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var * 7, 2)


def streak(totals: dict[dt.date, float], today: dt.date, tracking_start: dt.date | None) -> dict:
    """Smoke-free days. Counted only from when tracking began (quit date or first log):
    a day before anyone was logging is not a smoke-free day. Today counts while it is
    still clean."""
    if tracking_start is None or tracking_start > today:
        return {"current_days": 0, "best_days": 0}
    best = run = 0
    day = tracking_start
    while day <= today:
        run = run + 1 if totals.get(day, 0) <= 0 else 0
        best = max(best, run)
        day += dt.timedelta(days=1)
    return {"current_days": run, "best_days": best}


def since_quit(quit_date: dt.date | None, today: dt.date, baseline_per_day: float | None,
               price: float | None, smoked_since: float) -> dict | None:
    if quit_date is None:
        return None
    days = max((today - quit_date).days, 0)
    avoided = None
    if baseline_per_day:
        avoided = round(max(baseline_per_day * days - smoked_since, 0.0), 1)
    money = round(avoided * price, 2) if avoided is not None and price else None
    return {"days": days, "cigarettes_avoided": avoided, "money_saved": money}


def milestones(quit_at: dt.datetime | None, now: dt.datetime) -> list[dict]:
    if quit_at is None:
        return []
    return [{"label": label, "reached": now >= quit_at + offset,
             "at": (quit_at + offset).isoformat()} for offset, label in MILESTONES]


def compare(habit: str, metric: str, with_values: list[float], without_values: list[float],
            dose: str | None = None) -> dict:
    """One impact row: with vs without, n each, direction past the metric's threshold."""
    label_name, unit, threshold, relative, higher_better = METRICS[metric]
    n_with, n_without = len(with_values), len(without_values)
    with_avg = round(statistics.mean(with_values), 1) if with_values else None
    without_avg = round(statistics.mean(without_values), 1) if without_values else None
    diff = diff_pct = None
    if with_avg is not None and without_avg is not None:
        diff = round(with_avg - without_avg, 2)
        diff_pct = round(diff / without_avg * 100, 1) if without_avg else None
    enough = n_with >= MIN_N and n_without >= MIN_N
    direction = "no_clear_difference"
    if enough and diff is not None:
        size = abs(diff / without_avg) if relative and without_avg else abs(diff)
        if size >= threshold:
            better = (diff > 0) == higher_better
            direction = "better" if better else "worse"
    return {"habit": habit, "metric": metric, "dose": dose,
            "label": _label(habit, metric, label_name, unit, diff, n_with, n_without, dose),
            "with_avg": with_avg, "without_avg": without_avg, "diff": diff,
            "diff_pct": diff_pct, "n_with": n_with, "n_without": n_without,
            "direction": direction, "enough_data": enough}


def _label(habit, metric, name, unit, diff, n_with, n_without, dose) -> str:
    after = "the day after" if metric in ("easy_hr", "efficiency", "hr_drift") else \
        "the morning after"
    words = HABIT_WORDS.get(habit, habit)
    if dose:
        words = f"{dose} drinks"
    if diff is None:
        return f"{name}: not enough data yet {after} {words}."
    amount = f"{abs(diff):g}{(' ' + unit) if unit else ''}"
    side = "higher" if diff > 0 else "lower" if diff < 0 else "no different"
    if side == "no different":
        return (f"{name} {after} {words} was about the same as on other days "
                f"(n={n_with} vs {n_without}).")
    return (f"{name} {after} {words} was {amount} {side} on average "
            f"(n={n_with} vs {n_without}).")


def impact(habit: str, totals: dict[dt.date, float], days: list[dt.date],
           mornings: dict[dt.date, dict], runs: dict[dt.date, dict]) -> list[dict]:
    """Exposure day D (>= 1 log) vs clean day D (none): metrics dated D+1 (the morning
    after) and runs on D+1. `days` are the days to consider (tracking window)."""
    rows = []
    for metric in METRICS:
        source = runs if metric in ("easy_hr", "efficiency", "hr_drift") else mornings
        with_v, without_v = [], []
        for day in days:
            value = (source.get(day + dt.timedelta(days=1)) or {}).get(metric)
            if value is None:
                continue
            (with_v if totals.get(day, 0) > 0 else without_v).append(float(value))
        rows.append(compare(habit, metric, with_v, without_v))
    if habit == "alcohol":
        rows += _dose_rows(totals, days, mornings)
    return rows


def _dose_rows(totals, days, mornings) -> list[dict]:
    """1-2 vs 3+ drinks, HRV only, when both dose groups have at least 3 nights."""
    clean, low, high = [], [], []
    for day in days:
        value = (mornings.get(day + dt.timedelta(days=1)) or {}).get("hrv")
        if value is None:
            continue
        qty = totals.get(day, 0)
        (clean if qty <= 0 else low if qty < 3 else high).append(float(value))
    if len(low) < 3 or len(high) < 3:
        return []
    return [compare("alcohol", "hrv", low, clean, dose="1-2"),
            compare("alcohol", "hrv", high, clean, dose="3+")]


def weekly(start: dt.date, end: dt.date, habit_totals: dict[str, dict[dt.date, float]],
           mornings: dict[dt.date, dict], runs: dict[dt.date, dict]) -> list[dict]:
    """Monday weeks: habit sums and the mean HRV / RHR / sleep score / easy pace /
    efficiency for that week."""
    monday = start - dt.timedelta(days=start.weekday())
    out = []
    while monday <= end:
        week = [monday + dt.timedelta(days=i) for i in range(7)]

        def total(kind):
            return round(sum(habit_totals.get(kind, {}).get(d, 0) for d in week), 1)

        def avg(source, key, digits=1):
            vals = [source[d][key] for d in week if d in source and source[d].get(key) is not None]
            return round(statistics.mean(vals), digits) if vals else None

        out.append({"week_start": monday.isoformat(), "cigarettes": total("smoke"),
                    "drinks": total("alcohol"), "sugar": total("sugar"),
                    "hrv_avg": avg(mornings, "hrv"), "rhr_avg": avg(mornings, "rhr"),
                    "sleep_score_avg": avg(mornings, "sleep_score"),
                    "easy_pace_s_per_km": avg(runs, "easy_pace", 0),
                    "efficiency": avg(runs, "efficiency", 3)})
        monday += dt.timedelta(days=7)
    return out
