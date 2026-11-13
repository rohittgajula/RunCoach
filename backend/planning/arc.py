"""The arc: every week from where you started to where the plan ends, in one series.

Every screen in this app answers "what do I do now". None of them answers the
question you actually ask yourself, which is whether any of this is going
anywhere. That question needs the past and the future in the same picture, on the
same axis, at the same scale — otherwise the line through them is invisible.

Three decisions worth stating, because they are what make the picture honest.

A week is the unit. A day is noise: one bad night's sleep moves a day by twenty
per cent and moves a week by three. Weeks start Monday, which is what the planner
already assumes.

The future line is the plan's own numbers, not a projection. If the plan says 26
minutes on the week of 7 December, that is what the chart draws. Nothing here
invents a curve the plan has not committed to, so the shape you see is the shape
you have actually agreed to run.

The past line is the longest unbroken run block, not distance. Distance flatters
you — it counts the walking between the running. The block is the thing that has
to grow before 1 km non-stop is possible, so it is the thing the chart tracks,
and it carries its own running record beside it, because a record does not expire
when a week goes badly.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Iterable, NamedTuple

MONDAY = 0
PAST_WEEKS_MAX = 16
FUTURE_WEEKS_MAX = 20


class RunRow(NamedTuple):
    """One run, already segmented. Walking is out of every figure here."""

    day: dt.date
    run_s: float
    run_m: float
    longest_run_s: float


class PlanRow(NamedTuple):
    """One planned session, run or gym, done or not.

    duration_s and block_s are different quantities and must not be mixed. The
    first is how long you are out; the second is the longest unbroken run inside
    it. A 30-minute easy session may hold nothing longer than a 6-minute block,
    and a chart that draws the session time against your longest-ever block
    claims the plan is asking for something it never asked for.
    """

    day: dt.date
    duration_s: int
    block_s: int
    is_run: bool
    done: bool


@dataclass
class Week:
    start: dt.date
    end: dt.date
    # What happened.
    runs_done: int = 0
    run_s: float = 0.0
    run_m: float = 0.0
    longest_run_s: float = 0.0
    gym_done: int = 0
    # What the plan asked for.
    runs_planned: int = 0
    gym_planned: int = 0
    planned_run_s: int = 0
    #: The longest unbroken run block the plan asks for this week, which is the
    #: only planned figure comparable to longest_run_s.
    planned_block_s: int = 0
    # Where it sits relative to today.
    past: bool = False
    current: bool = False
    # The running record as at the end of this week — it only ever goes up.
    best_run_s: float = 0.0
    days: list = field(default_factory=list)

    @property
    def missed(self) -> int:
        """Planned run days in a finished week with no run on them.

        Not the same as runs_planned - runs_done: an extra run you went out for
        off your own back should not cancel out a session you skipped.
        """
        if not self.past:
            return 0
        return max(0, self.runs_planned - self.runs_done)


def monday(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=(day.weekday() - MONDAY) % 7)


def build(
    today: dt.date,
    runs: Iterable[RunRow],
    plans: Iterable[PlanRow],
    *,
    past_weeks: int = PAST_WEEKS_MAX,
    future_weeks: int = FUTURE_WEEKS_MAX,
) -> list[Week]:
    """One Week per week, oldest first, with no gaps.

    A week with nothing in it is still in the list. Gaps are the most
    informative thing in the whole series — five silent weeks is exactly what
    happened here in October, and a chart that skips them tells a kinder story
    than the truth.
    """
    runs = list(runs)
    plans = list(plans)
    here = monday(today)

    starts = [monday(r.day) for r in runs] + [monday(p.day) for p in plans]
    if not starts:
        return []
    first = max(min(starts), here - dt.timedelta(weeks=past_weeks))
    last = min(max(starts + [here]), here + dt.timedelta(weeks=future_weeks))

    weeks: dict[dt.date, Week] = {}
    cursor = first
    while cursor <= last:
        weeks[cursor] = Week(
            start=cursor,
            end=cursor + dt.timedelta(days=6),
            past=cursor < here,
            current=cursor == here,
        )
        cursor += dt.timedelta(weeks=1)

    for row in runs:
        week = weeks.get(monday(row.day))
        if week is None:
            continue
        week.runs_done += 1
        week.run_s += row.run_s
        week.run_m += row.run_m
        week.longest_run_s = max(week.longest_run_s, row.longest_run_s)

    for row in plans:
        week = weeks.get(monday(row.day))
        if week is None:
            continue
        if row.is_run:
            week.runs_planned += 1
            week.planned_run_s += row.duration_s
            week.planned_block_s = max(week.planned_block_s, row.block_s)
        else:
            week.gym_planned += 1
            if row.done:
                week.gym_done += 1

    ordered = [weeks[k] for k in sorted(weeks)]
    best = 0.0
    for week in ordered:
        best = max(best, week.longest_run_s)
        week.best_run_s = best
    return ordered


def peak(weeks: list[Week]) -> dict:
    """The two scales the chart has to fit, so the client never guesses one.

    Two, not one: weekly time and longest block are different quantities and
    share no axis.
    """
    return {
        "run_s": max([w.run_s for w in weeks] + [w.planned_run_s for w in weeks] + [1]),
        "block_s": max(
            [w.longest_run_s for w in weeks] + [w.planned_block_s for w in weeks] + [1]
        ),
    }


def describe(weeks: list[Week], today: dt.date) -> list[str]:
    """Two or three plain sentences about the shape, for the top of the view.

    Deliberately not generated by the model. These are arithmetic, and
    arithmetic should not be able to hallucinate.
    """
    out: list[str] = []
    past = [w for w in weeks if w.past]

    best = max(past, key=lambda w: w.longest_run_s, default=None)
    if best is not None and best.longest_run_s > 0:
        mins, secs = divmod(int(best.longest_run_s), 60)
        out.append(
            f"Your longest unbroken run is {mins}:{secs:02d}, set the week of "
            f"{best.start.strftime('%-d %B')}."
        )

    silent = [w for w in past if w.runs_done == 0 and w.gym_done == 0]
    if len(silent) >= 2:
        run = max(_streaks(silent))
        if run >= 2:
            out.append(f"There is a {run}-week gap in here with nothing recorded in it.")

    future = [w for w in weeks if not w.past and not w.current]
    if future:
        ahead = max(future, key=lambda w: w.planned_block_s)
        if ahead.planned_block_s:
            mins, secs = divmod(int(ahead.planned_block_s), 60)
            out.append(
                f"The plan builds to one unbroken block of {mins}:{secs:02d}, in the week "
                f"of {ahead.start.strftime('%-d %B')}."
            )
    return out


def _streaks(silent: list[Week]) -> list[int]:
    """Lengths of the consecutive runs inside a list of empty weeks."""
    if not silent:
        return [0]
    runs, length = [], 1
    for prev, week in zip(silent, silent[1:]):
        if (week.start - prev.start).days == 7:
            length += 1
        else:
            runs.append(length)
            length = 1
    runs.append(length)
    return runs
