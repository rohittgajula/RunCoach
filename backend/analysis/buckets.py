"""R12 §A: periods and bucketing for every Health chart. Pure: no Django.

A period is an inclusive date range; its comparison period is the same number of days
just before it. A series is a list of dicts with a date key; bucketing by week (Monday)
or month (the 1st) folds each bucket into one point: mean for rates and scores, sum for
counts and amounts, last for levels. Text values take the last one. `freq="day"` returns
the series untouched.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

FREQS = ("day", "week", "month")
HOW = ("mean", "sum", "last")
MAX_DAYS = 730
DAY_MAX_DAYS = 92
WEEK_MAX_DAYS = 366


@dataclass(frozen=True)
class Period:
    range_key: str          # a preset, or "custom"
    start: dt.date
    end: dt.date
    freq: str

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def compare_end(self) -> dt.date:
        return self.start - dt.timedelta(days=1)

    @property
    def compare_start(self) -> dt.date:
        return self.start - dt.timedelta(days=self.days)

    def as_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "days": self.days,
                "compare_start": self.compare_start, "compare_end": self.compare_end,
                "freq": self.freq}

    def ranged(self) -> dict:
        return {"range": self.range_key, "start": self.start, "end": self.end,
                "period": self.as_dict()}


def default_freq(days: int) -> str:
    if days <= DAY_MAX_DAYS:
        return "day"
    if days <= WEEK_MAX_DAYS:
        return "week"
    return "month"


def bucket_start(day: dt.date, freq: str) -> dt.date:
    if freq == "week":
        return day - dt.timedelta(days=day.weekday())
    if freq == "month":
        return day.replace(day=1)
    return day


def next_bucket(start: dt.date, freq: str) -> dt.date:
    if freq == "week":
        return start + dt.timedelta(days=7)
    if freq == "month":
        return (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return start + dt.timedelta(days=1)


def _as_date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _fold(values: list, how: str, digits: int | None):
    present = [v for v in values if v is not None]
    if not present:
        return None
    if not all(_is_number(v) for v in present):
        return present[-1]
    if how == "last":
        return present[-1]
    if how == "sum":
        total = sum(present)
        if all(isinstance(v, int) for v in present):
            return total
        return round(total, digits if digits is not None else 2)
    mean = sum(present) / len(present)
    if digits == 0:
        return round(mean)
    return round(mean, digits if digits is not None else 2)


def bucket(points: list[dict], freq: str, how: str | dict = "mean", *, date_key: str = "date",
           digits: int | dict | None = None) -> list[dict]:
    """Fold daily points into week/month points (see module doc). `how` and `digits`
    may be per-key dicts ({"steps": "sum", "*": "mean"})."""
    if freq == "day" or not points:
        return points
    groups: dict[dt.date, list[dict]] = {}
    as_text = isinstance(points[0].get(date_key), str)
    for p in points:
        day = _as_date(p.get(date_key))
        if day is None:
            continue
        groups.setdefault(bucket_start(day, freq), []).append(p)
    out = []
    for start in sorted(groups):
        rows = groups[start]
        keys: list[str] = []
        for r in rows:
            keys += [k for k in r if k != date_key and k not in keys]
        point: dict = {date_key: start.isoformat() if as_text else start}
        for key in keys:
            rule = how.get(key, how.get("*", "mean")) if isinstance(how, dict) else how
            dig = digits.get(key, digits.get("*")) if isinstance(digits, dict) else digits
            point[key] = _fold([r.get(key) for r in rows], rule, dig)
        point["n"] = len(rows)
        out.append(point)
    return out


def bucket_map(values: dict[dt.date, float], freq: str, how: str = "mean",
               digits: int | None = 3) -> dict[dt.date, float]:
    """{day: value} -> {bucket start: folded value} (identity for day)."""
    if freq == "day":
        return values
    groups: dict[dt.date, list[float]] = {}
    for day, value in values.items():
        if value is not None:
            groups.setdefault(bucket_start(day, freq), []).append(value)
    return {start: _fold(vals, how, digits) for start, vals in groups.items()}


def shift_back(values: dict[dt.date, float], freq: str) -> dict[dt.date, float]:
    """Re-key each bucket to the bucket before it (so pairing x with the shifted y at
    the same key means "y one bucket later")."""
    out = {}
    for start, value in values.items():
        if freq == "day":
            out[start - dt.timedelta(days=1)] = value
        elif freq == "week":
            out[start - dt.timedelta(days=7)] = value
        else:
            out[(start - dt.timedelta(days=1)).replace(day=1)] = value
    return out
