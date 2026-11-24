"""Meeting the athlete where they are, after they have stopped.

Rohit's record: ten runs in eleven weeks, a four-week gap through October,
three runs in the week of 9 November, then ten days of nothing. The app noticed
none of it. It kept writing sessions, he kept not doing them, and the only
thing that ever changed was the size of the backlog.

`catchup.py` fixed half of that — the plan now shrinks to what is actually
happening. This is the other half, which is the half about him rather than the
plan. Three things, all the same idea:

**Ask.** After a week of silence, one question. Not a streak, not a badge, not
a notification every morning — one question with answers that do something:
something hurts, it was too much, life got in the way. Each routes somewhere
real. The app has had a journal and a morning check-in for months and neither
of them has ever asked why he stopped.

**Make the first run back look like nothing.** A session that is smaller than
the gap deserves and says so in words. The cascade already shrinks the numbers;
numbers are not the problem. "20 minutes, walk whenever you want, that is the
whole job" is a different thing from a prescription that happens to be short.

**Give him a floor he clears.** Four sessions a week against a man who runs
twice is a week he fails by arithmetic, every week, for as long as he keeps the
app. The floor is the number he actually hits, and a week that hits it is a
good week. It rises when he rises, which is the only direction it should move.

Pure: no Django, no clock, no I/O.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, field

#: Silence shorter than this is a week with something on. Longer and the app
#: should say something, because by then he has stopped rather than skipped.
GAP_NOTICE_DAYS = 7

#: Past this it is a different conversation: not "shall I shrink this" but
#: "shall we start again", and a plan built for October is no longer about him.
GAP_LONG_DAYS = 21

#: The first run back, as a fraction of the longest unbroken block he has ever
#: held. Deliberately brutal. The risk after a lay-off is not that the first
#: run is too easy, it is that there is no second one.
RETURN_FRACTION = 0.5
RETURN_MIN_MINUTES = 12
RETURN_MAX_MINUTES = 30

#: Floors. Nobody's week is zero, and above three this stops being a floor and
#: starts being a plan.
FLOOR_MIN = 1
FLOOR_MAX = 3
FLOOR_WEEKS = 6


@dataclass(frozen=True)
class Answer:
    """One thing the athlete can say back, and what it does."""

    key: str
    label: str
    #: What the app does with it. Named so the caller cannot invent a fourth.
    action: str          # "illness" | "shrink" | "nothing" | "restart"
    note: str


@dataclass(frozen=True)
class Gap:
    days: int
    last_run: dt.date | None
    #: Whether this is worth saying anything about at all.
    noticed: bool
    long: bool
    headline: str
    answers: list[Answer] = field(default_factory=list)


#: The three honest reasons somebody stops, plus the one where nothing is
#: wrong. Each answer has to DO something or it is a survey, and a survey that
#: changes nothing teaches the athlete to ignore the next question.
ANSWERS: tuple[Answer, ...] = (
    Answer("hurt", "Something hurts",
           "illness",
           "Takes the plan down to walking and return sessions until you say it has "
           "settled."),
    Answer("much", "It was too much",
           "shrink",
           "Rebuilds the weeks ahead from what you were actually managing, not what "
           "the plan wanted."),
    Answer("life", "Life got in the way",
           "nothing",
           "Nothing changes. The plan is already waiting where you left it."),
)

RESTART = Answer("restart", "Start again from here", "restart",
                 "Builds a new block from what you can do today rather than carrying "
                 "the old one forward.")


def gap_for(last_run: dt.date | None, today: dt.date) -> Gap:
    """How long it has been, and what to ask about it.

    `last_run` of None means nothing has ever been recorded, which is not a gap
    — it is a first run, and asking somebody why they stopped when they never
    started is the app talking to itself.
    """
    if last_run is None:
        return Gap(days=0, last_run=None, noticed=False, long=False, headline="")

    days = max((today - last_run).days, 0)
    if days < GAP_NOTICE_DAYS:
        return Gap(days=days, last_run=last_run, noticed=False, long=False, headline="")

    long = days >= GAP_LONG_DAYS
    if long:
        headline = (
            f"It has been {days} days. That is long enough that the plan you left "
            "is not about you any more."
        )
        answers = [*ANSWERS, RESTART]
    else:
        headline = f"It has been {days} days since your last run."
        answers = list(ANSWERS)

    return Gap(days=days, last_run=last_run, noticed=True, long=long,
               headline=headline, answers=answers)


@dataclass(frozen=True)
class Return:
    minutes: int
    #: The whole job, in the words it should be said in.
    framing: str
    run_walk: bool


def return_session(gap: Gap, demonstrated_longest_s: float) -> Return | None:
    """The first run back. Smaller than it needs to be, on purpose.

    Sized from the longest unbroken block he has ever held rather than from the
    plan, because the plan is what he did not do. Half of it, floored and
    capped, and always run/walk — the point of the session is that it finishes,
    and a walk break is the thing that makes finishing certain.
    """
    if not gap.noticed:
        return None

    block_minutes = (demonstrated_longest_s or 0) / 60
    minutes = int(round(block_minutes * RETURN_FRACTION)) if block_minutes else 0
    minutes = max(RETURN_MIN_MINUTES, min(minutes or RETURN_MIN_MINUTES, RETURN_MAX_MINUTES))

    framing = (
        f"{minutes} minutes. Walk whenever you want to — that is the whole job. "
        "Getting out is the session; the running is a detail."
    )
    return Return(minutes=minutes, framing=framing, run_walk=True)


def week_floor(weekly_run_counts: list[int]) -> int:
    """The number of runs that makes a week a good week.

    Taken from what he actually does, not from what a plan wants, which is the
    entire point: a target he misses every week is a weekly reminder that he is
    failing, and nobody opens an app to be told that. The median of recent
    weeks is the number he clears about half the time — low enough to be
    reachable on a bad week and high enough to be worth clearing.

    Zero weeks count. A man who ran in two of the last six weeks has a floor of
    one, not of whatever he managed in the weeks he showed up.
    """
    recent = [max(int(n), 0) for n in (weekly_run_counts or [])][-FLOOR_WEEKS:]
    if not recent:
        return FLOOR_MIN
    median = statistics.median(recent)
    return int(max(FLOOR_MIN, min(round(median), FLOOR_MAX)))


def floor_met(runs_this_week: int, floor: int) -> bool:
    return runs_this_week >= floor


def floor_line(runs_this_week: int, floor: int) -> str:
    """What the week says about itself. Never a scold.

    A week under the floor is reported as what is left, not as what is missing,
    because those are the same number and only one of them is a thing you can
    go and do.
    """
    if floor_met(runs_this_week, floor):
        extra = runs_this_week - floor
        if extra > 0:
            return f"{runs_this_week} runs this week — {extra} past a good week."
        return f"{runs_this_week} of {floor}. That is a good week."
    left = floor - runs_this_week
    if runs_this_week == 0:
        return f"{left} run{'s' if left != 1 else ''} makes this a good week."
    return f"{runs_this_week} down, {left} to go for a good week."
