"""Sleep details (R10 §B4): bedtime regularity, sleep debt, averages, "tonight".

Pure — numbers and naive local datetimes in, dicts out. A night is dated by the
morning it ends (Garmin's convention).
"""

from __future__ import annotations

import datetime as dt
import statistics

MIN_REGULARITY_NIGHTS = 3
REGULARITY_BETTER_MIN = 5          # SD must fall by at least this much to be "better"
DEBT_NIGHTS = 7
FALL_ASLEEP_MIN = 15
SHORT_H, LONG_H = 6, 7
MIN_RUNS_EACH = 3


def minutes_after_noon(moment: dt.datetime | None) -> float | None:
    """Clock time as minutes after 12:00, so 22:30 → 630 and 01:00 → 780: a bedtime
    either side of midnight stays on one continuous scale."""
    if moment is None:
        return None
    minutes = moment.hour * 60 + moment.minute
    return float((minutes - 720) % 1440)


def minutes_of_day(moment: dt.datetime | None) -> float | None:
    if moment is None:
        return None
    return float(moment.hour * 60 + moment.minute)


def clock(minutes: float | None, after_noon: bool = False) -> str | None:
    """'HH:MM' for minutes of day (or minutes after noon)."""
    if minutes is None:
        return None
    total = round(minutes + (720 if after_noon else 0)) % 1440
    return f"{total // 60:02d}:{total % 60:02d}"


def mean(values, digits: int | None = 0):
    values = [v for v in values if v is not None]
    if not values:
        return None
    value = sum(values) / len(values)
    return round(value) if digits == 0 else round(value, digits)


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def sd_minutes(values: list[float | None]) -> int | None:
    values = [v for v in values if v is not None]
    if len(values) < MIN_REGULARITY_NIGHTS:
        return None
    return round(statistics.pstdev(values))


def regularity(bedtimes: list[dt.datetime | None],
               previous_bedtimes: list[dt.datetime | None]) -> dict:
    now = sd_minutes([minutes_after_noon(b) for b in bedtimes])
    before = sd_minutes([minutes_after_noon(b) for b in previous_bedtimes])
    better = None
    if now is not None and before is not None:
        if now <= before - REGULARITY_BETTER_MIN:
            better = True
        elif now >= before + REGULARITY_BETTER_MIN:
            better = False
    return {"bedtime_sd_min": now, "previous_bedtime_sd_min": before,
            "n": sum(1 for b in bedtimes if b is not None), "better": better}


def debt(nights: list[tuple[int | None, int | None]]) -> dict:
    """nights: (sleep_s, need_s), oldest first. Uses the last 7 with both values:
    Σ(need − actual), floored at 0."""
    both = [(s, n) for s, n in nights if s is not None and n]
    recent = both[-DEBT_NIGHTS:]
    if not recent:
        return {"need_s": None, "debt_s": None, "short_nights": 0, "nights": 0,
                "short_by_s": None}
    short = [n - s for s, n in recent if s < n]
    return {
        "need_s": round(statistics.median(n for _, n in recent)),
        "debt_s": max(round(sum(n - s for s, n in recent)), 0),
        "short_nights": len(short),
        "nights": len(recent),
        "short_by_s": round(sum(short) / len(short)) if short else None,
    }


def averages(nights: list[dict]) -> dict:
    """Mean of each nightly field (nights as built by the view)."""
    def clock_avg(key, after_noon):
        convert = minutes_after_noon if after_noon else minutes_of_day
        return clock(mean([convert(n.get(key)) for n in nights]), after_noon=after_noon)

    return {
        "sleep_s": mean([n.get("sleep_s") for n in nights]),
        "need_s": mean([n.get("need_s") for n in nights]),
        "score": mean([n.get("score") for n in nights]),
        "deep_s": mean([n.get("deep_s") for n in nights]),
        "rem_s": mean([n.get("rem_s") for n in nights]),
        "spo2_avg": mean([n.get("spo2_avg") for n in nights], 1),
        "breathing_rate": mean([n.get("breathing_rate") for n in nights], 1),
        "restless_moments": mean([n.get("restless_moments") for n in nights]),
        "bedtime": clock_avg("bedtime_dt", True),
        "wake_time": clock_avg("wake_dt", False),
    }


def tonight(wake_times: list[dt.datetime | None], need_s: int | None) -> dict:
    """Median wake time of the recent nights; bedtime = wake − need − 15 min."""
    wake = median([minutes_of_day(w) for w in wake_times])
    bedtime = None
    if wake is not None and need_s:
        bedtime = clock(wake - need_s / 60 - FALL_ASLEEP_MIN)
    return {"need_s": need_s, "wake_time": clock(wake), "bedtime": bedtime}


def sleep_vs_runs(pairs: list[tuple[float | None, float | None]]) -> dict:
    """pairs: (hours slept the night before, easy-pace HR on that day's runs)."""
    short = [hr for h, hr in pairs if h is not None and hr is not None and h < SHORT_H]
    long_ = [hr for h, hr in pairs if h is not None and hr is not None and h >= LONG_H]
    short_hr, long_hr = mean(short, 1), mean(long_, 1)
    enough = len(short) >= MIN_RUNS_EACH and len(long_) >= MIN_RUNS_EACH
    diff = round(short_hr - long_hr, 1) if short_hr is not None and long_hr is not None else None
    sentence = None
    if enough and diff is not None:
        if abs(diff) < 2:
            sentence = (f"HR at easy pace was about the same after short and longer nights "
                        f"(n={len(short)} and {len(long_)}).")
        else:
            word = "lower" if diff > 0 else "higher"
            sentence = (f"HR at easy pace was {abs(diff):g} bpm {word} after nights of "
                        f"{LONG_H} h or more than after nights under {SHORT_H} h "
                        f"(n={len(long_)} and {len(short)}).")
    return {"short_h": SHORT_H, "long_h": LONG_H,
            "short": {"easy_hr": short_hr, "n": len(short)},
            "long": {"easy_hr": long_hr, "n": len(long_)},
            "diff_bpm": diff, "enough_data": enough, "sentence": sentence}
