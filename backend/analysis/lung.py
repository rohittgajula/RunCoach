"""Lung recovery tracker (R10 §C9): breathing and heart numbers since the quit date
against the 14 days before it. Association only — never "quitting did this". Pure."""

from __future__ import annotations

import datetime as dt

BEFORE_DAYS = 14
NOW_DAYS = 14
MIN_N = 5
NOTE = ("These numbers move with sleep, training, heat and illness too. They show how "
        "things changed since you quit — they can't show the cause.")

# key -> (label, unit, threshold, lower is better, digits)
METRICS = {
    "sleep_breathing_rate": ("Breathing rate while asleep", "brpm", 0.5, True, 1),
    "spo2": ("Overnight SpO2", "%", 1.0, False, 1),
    "resting_hr": ("Resting heart rate", "bpm", 2.0, True, 1),
    "easy_hr": ("Heart rate at easy pace", "bpm", 2.0, True, 1),
}


def _mean(values, digits):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), digits) if values else None


def windows(quit_date: dt.date, today: dt.date) -> tuple[tuple[dt.date, dt.date],
                                                         tuple[dt.date, dt.date]]:
    """(before start, before end), (now start, now end)."""
    before = (quit_date - dt.timedelta(days=BEFORE_DAYS), quit_date - dt.timedelta(days=1))
    now_start = max(quit_date, today - dt.timedelta(days=NOW_DAYS - 1))
    return before, (now_start, today)


def _sentence(key, label, unit, before, now, better, enough, before_n, now_n) -> str:
    name = label[0].lower() + label[1:]
    if not enough:
        return (f"Not enough {name} readings yet to compare ({before_n} before quitting, "
                f"{now_n} recently; {MIN_N} each needed).")
    diff = round(now - before, 1)
    if better is None:
        return (f"Your {name} is about the same as in the two weeks before you quit "
                f"({before:g} → {now:g} {unit}).")
    word = "lower" if diff < 0 else "higher"
    return (f"Your {name} has been {abs(diff):g} {unit} {word} than in the two weeks before "
            f"you quit ({before:g} → {now:g}). That fits recovery, though sleep, training "
            f"and heat move it too.")


def metric(key: str, values: dict[dt.date, float], quit_date: dt.date,
           today: dt.date) -> dict:
    label, unit, threshold, lower_better, digits = METRICS[key]
    (b0, b1), (n0, n1) = windows(quit_date, today)
    before_vals = [v for d, v in values.items() if b0 <= d <= b1 and v is not None]
    now_vals = [v for d, v in values.items() if n0 <= d <= n1 and v is not None]
    before, now = _mean(before_vals, digits), _mean(now_vals, digits)
    enough = len(before_vals) >= MIN_N and len(now_vals) >= MIN_N
    change = round(now - before, digits) if before is not None and now is not None else None
    better = None
    if enough and change is not None and abs(change) >= threshold:
        better = (change < 0) if lower_better else (change > 0)
    series = [{"date": d, "value": round(values[d], digits)}
              for d in sorted(values) if b0 <= d <= today and values[d] is not None]
    return {"key": key, "label": label, "unit": unit, "before": before,
            "before_n": len(before_vals), "now": now, "now_n": len(now_vals),
            "change": change, "better": better, "enough_data": enough, "series": series,
            "sentence": _sentence(key, label, unit, before, now, better, enough,
                                  len(before_vals), len(now_vals))}
