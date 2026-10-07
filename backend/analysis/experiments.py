"""Self-experiments (R14 §7). Pure — no Django.

An experiment is a rule kept for 7–42 days ("no alcohol", "no caffeine after 14:00",
"bed by 22:30", "10k steps"). Daily adherence comes from the athlete's own logs; the
result compares the same number of days before the start (baseline) with the days
during it. Wording is deliberately non-causal: an experiment of one, with no control,
shows what changed alongside the rule — not that the rule caused it.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass

MIN_DAYS, MAX_DAYS = 7, 42
HABITS = ("alcohol", "caffeine", "sugar", "smoke", "private")
HABIT_WORD = {"alcohol": "drinks", "caffeine": "cups", "sugar": "sugary items",
              "smoke": "cigarettes", "private": "times"}

TEMPLATES = {
    "no_alcohol": {"title": "No alcohol", "rule": {"habit": "alcohol", "max_per_day": 0},
                   "default_days": 21, "source": "habits",
                   "description": "No drinks at all. Logged drinks break the day."},
    "no_late_caffeine": {"title": "No caffeine after 14:00",
                         "rule": {"habit": "caffeine", "max_per_day": 0, "after": "14:00"},
                         "default_days": 14, "source": "caffeine",
                         "description": "Coffee, tea or energy drinks only before 2 pm."},
    "no_sugar": {"title": "No added sugar", "rule": {"habit": "sugar", "max_per_day": 0},
                 "default_days": 21, "source": "habits",
                 "description": "No sweets, sugary drinks or desserts."},
    "smoke_free": {"title": "Smoke-free", "rule": {"habit": "smoke", "max_per_day": 0},
                   "default_days": 21, "source": "habits",
                   "description": "Not a single cigarette."},
    "bed_by": {"title": "In bed by 22:30", "rule": {"bedtime": "22:30"}, "default_days": 14,
               "source": "sleep",
               "description": "Asleep by the time you choose, from your watch's sleep data."},
    "steps": {"title": "10k steps a day", "rule": {"min_steps": 10000}, "default_days": 14,
              "source": "steps", "description": "At least 10,000 steps every day."},
    "custom": {"title": "My own limit", "rule": {"habit": "alcohol", "max_per_day": 0},
               "default_days": 14, "source": "habits",
               "description": "Pick a habit and a daily limit."},
}

# key -> (label, unit, higher_is_better, clear difference, digits)
METRICS = {
    "hrv": ("HRV (overnight)", "ms", True, 3.0, 0),
    "rhr": ("Resting heart rate", "bpm", False, 2.0, 0),
    "sleep_score": ("Sleep score", "", True, 3.0, 0),
    "stress": ("Stress (daily average)", "", False, 3.0, 0),
    "easy_hr": ("Heart rate on easy runs", "bpm", False, 3.0, 0),
    "mood": ("Mood", "1–5", True, 0.4, 1),
    "energy": ("Energy", "1–5", True, 0.4, 1),
}
MIN_N = 4
MIN_N_RUNS = 2
CAVEAT = ("An experiment of one with no control group: these numbers show what changed "
          "alongside the experiment, not that it caused the change. Sleep, training load, "
          "illness, travel and weather all move them too.")


def clock_minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def evening_minutes(at: dt.datetime | dt.time) -> int:
    """Minutes after noon (so 23:30 < 00:30 for a bedtime comparison)."""
    t = at.time() if isinstance(at, dt.datetime) else at
    return (t.hour * 60 + t.minute - 720) % 1440


def bed_date(sleep_start: dt.datetime) -> dt.date:
    """The evening a sleep belongs to: a 00:40 sleep start is the previous evening."""
    return (sleep_start - dt.timedelta(hours=12)).date()


@dataclass(frozen=True)
class DayLog:
    habit: float = 0.0               # the rule's habit total that day
    habit_late: float = 0.0          # caffeine at/after the rule's `after` time
    bedtime: dt.datetime | None = None
    steps: int | None = None


def rule_value(kind: str, rule: dict, log: DayLog | None) -> float | None:
    log = log or DayLog()
    if "min_steps" in rule:
        return float(log.steps) if log.steps is not None else None
    if "bedtime" in rule:
        return float(evening_minutes(log.bedtime)) if log.bedtime else None
    return log.habit_late if rule.get("after") else log.habit


def kept(rule: dict, value: float | None, final: bool) -> bool | None:
    """final: the day is over. A day still running is True only once it can't fail
    (steps reached) and False once it already has (a logged drink), else None."""
    if "min_steps" in rule:
        if value is None:
            return None
        if value >= rule["min_steps"]:
            return True
        return False if final else None
    if "bedtime" in rule:
        if value is None:
            return None
        return value <= evening_minutes(dt.time.fromisoformat(rule["bedtime"]))
    limit = float(rule.get("max_per_day", 0))
    value = value or 0.0
    if value > limit:
        return False
    return True if final else None


def display(rule: dict, value: float | None) -> str | None:
    """The day's value in words: "23:10" (bedtime), "8,412 steps", "2 drinks"."""
    if value is None:
        return None
    if "bedtime" in rule:
        minutes = (int(value) + 720) % 1440
        return f"{minutes // 60:02d}:{minutes % 60:02d}"
    if "min_steps" in rule:
        return f"{int(value):,} steps"
    word = HABIT_WORD.get(rule.get("habit", ""), "")
    number = f"{value:g}"
    return f"{number} {word}".strip()


def adherence(kind: str, rule: dict, start: dt.date, end: dt.date, today: dt.date,
              logs: dict[dt.date, DayLog]) -> dict:
    """Day by day up to today (or the end). Bedtime days are judged on the evening
    itself, so they are final only from the next day on."""
    series = []
    last = min(end, today)
    day = start
    while day <= last:
        final = day < today
        value = rule_value(kind, rule, logs.get(day))
        series.append({"date": day, "kept": kept(rule, value, final),
                       "value": round(value, 1) if value is not None else None,
                       "display": display(rule, value)})
        day += dt.timedelta(days=1)
    counted = [d for d in series if d["kept"] is not None]
    kept_days = sum(1 for d in counted if d["kept"])
    today_row = next((d for d in series if d["date"] == today), None)
    return {"days_counted": len(counted), "days_kept": kept_days,
            "pct": round(kept_days / len(counted) * 100) if counted else None,
            "today": today_row["kept"] if today_row else None, "series": series}


def _mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def compare(series: dict[str, dict[dt.date, float]], baseline: tuple[dt.date, dt.date],
            during: tuple[dt.date, dt.date]) -> list[dict]:
    """Before vs during for each metric. Values are keyed by the date they describe
    (callers shift nightly metrics to the day before the morning they were measured)."""
    out = []
    for key, (label, unit, higher, clear, digits) in METRICS.items():
        values = series.get(key) or {}
        before = [v for d, v in values.items() if baseline[0] <= d <= baseline[1] and v is not None]
        now = [v for d, v in values.items() if during[0] <= d <= during[1] and v is not None]
        b, n = _mean(before), _mean(now)
        need = MIN_N_RUNS if key == "easy_hr" else MIN_N
        enough = len(before) >= need and len(now) >= need
        diff = round(n - b, digits or None) if b is not None and n is not None else None
        if diff is not None and digits == 0:
            diff = int(round(n - b))
        direction = None
        if enough and diff is not None:
            if abs(n - b) < clear:
                direction = "no_clear_difference"
            else:
                direction = "better" if (n > b) == higher else "worse"
        out.append({"key": key, "label": label, "unit": unit,
                    "before": _round(b, digits), "during": _round(n, digits), "diff": diff,
                    "n_before": len(before), "n_during": len(now),
                    "higher_is_better": higher, "enough_data": enough,
                    "direction": direction,
                    "sentence": _sentence(label, unit, b, n, len(before), len(now), enough,
                                          direction, digits, key)})
    return out


def _round(value, digits):
    if value is None:
        return None
    return int(round(value)) if digits == 0 else round(value, digits)


def _fmt(value, unit, digits) -> str:
    text = f"{value:.{digits}f}"
    return f"{text} {unit}" if unit and unit != "1–5" else text


def _sentence(label, unit, before, during, nb, nd, enough, direction, digits, key) -> str:
    what = "runs" if key == "easy_hr" else "days"
    if not enough:
        return (f"{label}: not enough data yet ({nd} {what} during, {nb} before — "
                f"{MIN_N_RUNS if key == 'easy_hr' else MIN_N} each needed).")
    base = (f"{label} averaged {_fmt(during, unit, digits)} during vs "
            f"{_fmt(before, unit, digits)} before ({nd} vs {nb} {what})")
    if direction == "no_clear_difference":
        return base + " — no clear difference."
    return base + (" — moved in a good direction." if direction == "better"
                   else " — moved the other way.")


def _lower(label: str) -> str:
    """"Resting heart rate" -> "resting heart rate"; "HRV (overnight)" stays."""
    return label if label[:2].isupper() else label[0].lower() + label[1:]


def summary(title: str, adherence_pct: int | None, metrics: list[dict], final: bool) -> str:
    better = [_lower(m["label"]) for m in metrics if m["direction"] == "better"]
    worse = [_lower(m["label"]) for m in metrics if m["direction"] == "worse"]
    kept_text = (f"You kept it {adherence_pct}% of days" if adherence_pct is not None
                 else "No days counted yet")
    lead = f"{title}: {kept_text}"
    if not better and not worse:
        rest = "no clear change in your numbers so far" if not final else \
            "no clear change in your numbers alongside it"
        return f"{lead}; {rest}."
    parts = []
    if better:
        parts.append(f"{', '.join(better)} looked better")
    if worse:
        parts.append(f"{', '.join(worse)} looked worse")
    return (f"{lead}. During it, {' and '.join(parts)} than in the same number of days "
            "before.")


def share_lines(title: str, days: int, adherence_pct: int | None, metrics: list[dict]) -> list[str]:
    lines = [f"{days}-day experiment: {title}"]
    if adherence_pct is not None:
        lines.append(f"Kept {adherence_pct}% of days")
    for m in metrics:
        if m["enough_data"] and m["direction"] in ("better", "worse") and m["diff"] is not None:
            sign = "+" if m["diff"] > 0 else ""
            unit = f" {m['unit']}" if m["unit"] and m["unit"] != "1–5" else ""
            lines.append(f"{m['label']}: {sign}{m['diff']}{unit}")
    return lines[:6]
