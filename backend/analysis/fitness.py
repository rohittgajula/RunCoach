"""Fitness, Fatigue and Form from the custom training load.

    Fitness = 42-day exponentially weighted average of daily load
    Fatigue =  7-day exponentially weighted average of daily load
    Form    = Fitness - Fatigue

The load is the project's own `session_load` (run minutes x 2 + walk minutes x 1), never
Garmin's proprietary figure, so these numbers must be presented as RunCoach's own
measures. They are on a different scale from TrainingPeaks' CTL/ATL and the bands below
are tuned to it, not copied from there.

Pure: takes a {date: load} mapping and returns plain dataclasses, so it is testable
without a database. The Django side only gathers the loads.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable, Literal

FITNESS_DAYS = 42
FATIGUE_DAYS = 7

# Below this much history the averages are still mostly the zero they started from,
# and a "Detraining" label on someone's second week would be a confident wrong answer.
MIN_HISTORY_DAYS = 14

Status = Literal[
    "detraining", "fresh", "maintaining", "gaining", "overtraining", "insufficient_data"
]


@dataclass(frozen=True)
class FitnessPoint:
    date: dt.date
    fitness: float
    fatigue: float
    form: float


def daily_loads(sessions: Iterable[tuple[dt.date, float | None]]) -> dict[dt.date, float]:
    """Sum per-session loads into one value per day. A missing load counts as zero
    rather than being guessed — an unsegmented activity has no honest load."""
    totals: dict[dt.date, float] = {}
    for day, load in sessions:
        totals[day] = totals.get(day, 0.0) + float(load or 0.0)
    return totals


def series(
    loads: dict[dt.date, float], start: dt.date, end: dt.date,
    history_start: dt.date | None = None,
) -> list[FitnessPoint]:
    """One point per day from `start` to `end` inclusive.

    The averages are warmed up from `history_start` (default: the earliest load) so a
    3-month chart does not begin at zero just because the window does. Days with no
    activity are zero-load days, which is what makes fitness decay on rest.
    """
    if end < start:
        return []
    first = min([start, *loads.keys()]) if loads else start
    if history_start is not None:
        first = min(first, history_start)

    k_fit = 1 / FITNESS_DAYS
    k_fat = 1 / FATIGUE_DAYS
    fitness = fatigue = 0.0
    points: list[FitnessPoint] = []

    day = first
    while day <= end:
        load = loads.get(day, 0.0)
        fitness += (load - fitness) * k_fit
        fatigue += (load - fatigue) * k_fat
        if day >= start:
            points.append(
                FitnessPoint(
                    date=day,
                    fitness=round(fitness, 1),
                    fatigue=round(fatigue, 1),
                    form=round(fitness - fatigue, 1),
                )
            )
        day += dt.timedelta(days=1)
    return points


def status(form: float, history_days: int | None = None) -> Status:
    """The training-status band for a Form value.

        detraining   form > 20
        fresh        5 < form <= 20
        maintaining  -10 <= form <= 5
        gaining      -30 <= form < -10
        overtraining form < -30

    `history_days` is how many days of training history exist; below MIN_HISTORY_DAYS
    the answer is `insufficient_data` regardless of the number.
    """
    if history_days is not None and history_days < MIN_HISTORY_DAYS:
        return "insufficient_data"
    if form > 20:
        return "detraining"
    if form > 5:
        return "fresh"
    if form >= -10:
        return "maintaining"
    if form >= -30:
        return "gaining"
    return "overtraining"


def history_days(loads: dict[dt.date, float], today: dt.date) -> int:
    """Days since the first recorded load, inclusive. Zero with no history."""
    if not loads:
        return 0
    return (today - min(loads)).days + 1
