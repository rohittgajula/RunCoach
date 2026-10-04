"""Where a plan starts: the most recent block of real running, detrained for the gap.

The first version looked back four weeks only. An athlete whose last run was six weeks
ago then looked like someone who had never run, and got beginner defaults — throwing
away the August weeks he had demonstrably absorbed. Fitness fades after a break, but
not to zero, and not in a fortnight.

So: look back up to 16 weeks for the most recent *block* of running (runs no more than
two weeks apart), take its best week, then scale by a detraining factor for the gap
since the last run. The result is never below the beginner default — a long break
makes a plan cautious, not smaller than a couch-to-5K.

Pure: plain dataclasses in, plain numbers out.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

HISTORY_WEEKS = 16
# Runs further apart than this belong to different blocks.
BLOCK_GAP_DAYS = 14
BEGINNER_RUN_KM_PER_WEEK = 5.0

# (max gap days, factor). Above the last band: LONG_GAP_FACTOR.
DETRAINING_BANDS = ((14, 1.0), (28, 0.85), (56, 0.7))
LONG_GAP_FACTOR = 0.5


@dataclass(frozen=True)
class RunPoint:
    date: dt.date
    run_distance_m: float
    longest_run_s: float
    run_pace_s_per_km: float | None = None
    walk_pace_s_per_km: float | None = None


@dataclass(frozen=True)
class HistoryBaseline:
    source: str                     # "history" | "beginner_defaults"
    run_km_per_week: float
    longest_run_s: float
    run_pace_s_per_km: float | None
    walk_pace_s_per_km: float | None
    last_run_date: dt.date | None = None
    gap_days: int | None = None
    detraining_factor: float = 1.0
    best_week_start: dt.date | None = None
    best_week_km: float = 0.0
    best_longest_run_s: float = 0.0
    warning: str | None = None


def detraining_factor(gap_days: int) -> float:
    for limit, factor in DETRAINING_BANDS:
        if gap_days <= limit:
            return factor
    return LONG_GAP_FACTOR


def recent_block(runs: list[RunPoint], today: dt.date) -> list[RunPoint]:
    """The most recent stretch of runs, none more than BLOCK_GAP_DAYS apart."""
    since = today - dt.timedelta(weeks=HISTORY_WEEKS)
    recent = sorted((r for r in runs if since <= r.date <= today), key=lambda r: r.date,
                    reverse=True)
    block: list[RunPoint] = []
    for run in recent:
        if block and (block[-1].date - run.date).days > BLOCK_GAP_DAYS:
            break
        block.append(run)
    return block


def _median(values: list[float]) -> float | None:
    values = sorted(v for v in values if v)
    return values[len(values) // 2] if values else None


def _gap_phrase(gap_days: int) -> str:
    if gap_days >= 14:
        return f"{round(gap_days / 7)} weeks ago"
    return f"{gap_days} day{'s' if gap_days != 1 else ''} ago"


def from_history(runs: list[RunPoint], today: dt.date) -> HistoryBaseline:
    block = recent_block(runs, today)
    if not block:
        return HistoryBaseline(
            source="beginner_defaults", run_km_per_week=BEGINNER_RUN_KM_PER_WEEK,
            longest_run_s=0.0, run_pace_s_per_km=None, walk_pace_s_per_km=None,
        )

    by_week: dict[dt.date, float] = {}
    for run in block:
        monday = run.date - dt.timedelta(days=run.date.weekday())
        by_week[monday] = by_week.get(monday, 0.0) + run.run_distance_m
    best_start, best_m = max(by_week.items(), key=lambda item: (item[1], item[0]))
    best_km = best_m / 1000
    longest = max(r.longest_run_s for r in block)

    last = block[0].date
    gap = (today - last).days
    factor = detraining_factor(gap)
    run_km = max(best_km * factor, BEGINNER_RUN_KM_PER_WEEK)

    warning = None
    if factor < 1.0 and best_km * factor >= BEGINNER_RUN_KM_PER_WEEK:
        warning = (
            f"Your last run was {_gap_phrase(gap)}, so this starts at ~{round(factor * 100)} % "
            f"of your best {best_start:%B} week."
        )
    elif factor < 1.0:
        warning = (
            f"Your last run was {_gap_phrase(gap)}, so this starts at ~{round(factor * 100)} % "
            f"of your best {best_start:%B} week — lifted to the "
            f"{BEGINNER_RUN_KM_PER_WEEK:g} km beginner floor."
        )
    return HistoryBaseline(
        source="history",
        run_km_per_week=run_km,
        longest_run_s=longest * factor,
        run_pace_s_per_km=_median([r.run_pace_s_per_km for r in block]),
        walk_pace_s_per_km=_median([r.walk_pace_s_per_km for r in block]),
        last_run_date=last,
        gap_days=gap,
        detraining_factor=factor,
        best_week_start=best_start,
        best_week_km=round(best_km, 2),
        best_longest_run_s=longest,
        warning=warning,
    )
