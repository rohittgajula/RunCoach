"""Heart rate, split by what you were doing. Pure — no Django, no I/O.

Rohit: "add a HeartRate section in health with multiple hr filters like while
sleeping, running, walking, normal day time ... basically i wanna see how my
hr is changing (heartbeat is increasing or decreasing)".

One number for a day's heart rate answers nothing, because a day contains four
quite different hearts: asleep, running, walking, and sitting at a desk. Each
moves for its own reasons and on its own timescale, and the one that tells you
most about fitness — sleeping heart rate — is the one a daily average buries
under sixteen waking hours.

The input is the intraday series Garmin records every couple of minutes, cut
against three sets of windows:

    running   from the run segments of that day's activities
    walking   from the walk segments
    sleeping  from the night that ENDS on this day
    awake     everything else in the waking hours

Priority matters and runs downhill from the most specific: a sample inside a
run segment is running even if the watch thought you were asleep, and a sample
inside the sleep window is sleeping even if you were restless. The last bucket
is a remainder, never a window of its own, so the four cannot overlap and
nothing is counted twice.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass

#: In priority order. The first window a sample falls inside wins.
CONTEXTS: tuple[str, ...] = ("run", "walk", "sleep", "awake")

LABEL: dict[str, str] = {
    "run": "Running",
    "walk": "Walking",
    "sleep": "Asleep",
    "awake": "Awake, not training",
}

WHY: dict[str, str] = {
    "run": "What your heart does under load. Falling at the same pace is the "
           "clearest sign your training is working.",
    "walk": "Your recovery between run blocks, and how fast it settles.",
    "sleep": "The quietest your heart gets. The single best day-to-day signal "
             "of fatigue, illness and fitness — and the slowest to move.",
    "awake": "Resting life. Rises with stress, caffeine, poor sleep and "
             "illness before anything else does.",
}

#: A bucket needs this many readings in a day before it means anything. At one
#: sample every two minutes this is twenty minutes of being in that state.
MIN_READINGS = 10


@dataclass(frozen=True)
class Window:
    """Minutes from local midnight, half-open: [start, end)."""

    start: float
    end: float
    context: str

    def holds(self, minute: float) -> bool:
        return self.start <= minute < self.end


@dataclass(frozen=True)
class DayHR:
    day: dt.date
    #: context -> mean bpm, only where there were enough readings.
    means: dict[str, float]
    #: context -> how many readings it was built from. Shown rather than
    #: hidden: a mean of eleven samples and a mean of four hundred are
    #: different claims and should not look the same.
    counts: dict[str, int]
    resting: int | None = None


def windows_for(
    run_spans: list[tuple[float, float]],
    walk_spans: list[tuple[float, float]],
    sleep_span: tuple[float, float] | None,
) -> list[Window]:
    """Build the windows in priority order. Spans are minutes from midnight."""
    out = [Window(a, b, "run") for a, b in run_spans if b > a]
    out += [Window(a, b, "walk") for a, b in walk_spans if b > a]
    if sleep_span and sleep_span[1] > sleep_span[0]:
        out.append(Window(sleep_span[0], sleep_span[1], "sleep"))
    return out


def classify(minute: float, windows: list[Window]) -> str:
    """Which bucket a reading belongs to. `awake` is the remainder."""
    for context in CONTEXTS[:-1]:
        for window in windows:
            if window.context == context and window.holds(minute):
                return context
    return "awake"


def bucket_day(
    day: dt.date,
    hr_series: list,
    windows: list[Window],
    resting: int | None = None,
) -> DayHR:
    """One day of intraday heart rate, split four ways.

    `hr_series` is Garmin's `[[minute, bpm]]`. Rows that are malformed or carry
    no bpm are skipped rather than counted as zero — a zero here would drag a
    mean down and look like a resting heart rate nobody has.
    """
    collected: dict[str, list[float]] = {c: [] for c in CONTEXTS}
    for row in hr_series or []:
        try:
            minute, bpm = float(row[0]), float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        if bpm <= 0:
            continue
        collected[classify(minute, windows)].append(bpm)

    return DayHR(
        day=day,
        means={c: round(statistics.mean(v), 1)
               for c, v in collected.items() if len(v) >= MIN_READINGS},
        counts={c: len(v) for c, v in collected.items() if v},
        resting=resting,
    )


def series(days: list[DayHR], context: str) -> list[dict]:
    """One context across days, oldest first, gaps left as gaps.

    A day with too few readings is absent rather than zero or carried forward:
    a flat line through a week the watch was off the wrist is a lie the chart
    would tell convincingly.
    """
    out = []
    for row in sorted(days, key=lambda d: d.day):
        value = row.means.get(context)
        if value is not None:
            out.append({"day": row.day.isoformat(), "bpm": value,
                        "readings": row.counts.get(context, 0)})
    return out


def weekly(days: list[DayHR], context: str) -> list[dict]:
    """The same, averaged per week. Weeks move slowly enough to see a trend in."""
    buckets: dict[dt.date, list[float]] = {}
    for row in sorted(days, key=lambda d: d.day):
        value = row.means.get(context)
        if value is None:
            continue
        monday = row.day - dt.timedelta(days=row.day.weekday())
        buckets.setdefault(monday, []).append(value)
    return [
        {"week": start.isoformat(), "bpm": round(statistics.mean(values), 1),
         "days": len(values)}
        for start, values in sorted(buckets.items())
    ]


def direction(points: list[dict], key: str = "bpm") -> dict:
    """Is it going up or down, and by how much.

    Compares the first third against the last third rather than endpoints: two
    single days are two coin flips, and a trend drawn between them is mostly
    noise. For every context here a FALL is the good direction, which is worth
    stating once rather than leaving each caller to remember.
    """
    values = [p[key] for p in points if p.get(key) is not None]
    if len(values) < 6:
        return {"enough": False}

    third = max(len(values) // 3, 2)
    early = statistics.mean(values[:third])
    late = statistics.mean(values[-third:])
    change = round(late - early, 1)
    return {
        "enough": True,
        "from": round(early, 1),
        "to": round(late, 1),
        "change": change,
        # Named rather than signed, because "-3" reads as worse to most people
        # and this is the one metric where down is the win.
        "better": change < 0,
        "flat": abs(change) < 1.0,
    }
