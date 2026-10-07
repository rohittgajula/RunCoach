"""Re-flow a stored plan's future workouts onto new training days.

When the athlete changes their available days (or long-run day) in Settings, the
plan is NOT regenerated: every workout keeps its title, steps, volume, adaptations and
check-in changes. Only dates change. This module decides those dates; the Django side
(`apps.planning.reflow`) loads rows, applies the decision and syncs the watch.

Rules (per ISO week, Monday–Sunday):
- Only planned, non-race workouts after today (and before the race) move. Today's,
  past, completed and race workouts are fixed and still occupy their day.
- A week whose runs already sit on available days, within the weekly run-day limit,
  with the long run on the long-run day, is left exactly as it is. That makes the
  re-flow idempotent and keeps unrelated weeks untouched when a day is only added.
- Otherwise the runs are re-placed on `run_days(...)` (the generator's own spread),
  the long run on the long-run day, hard sessions away from each other and from the
  long run where possible, everything else in its original order.
- Too many runs for the days: the shortest easy / run-walk sessions are dropped. A
  long run, a hard session or a race is never dropped, and nothing gets longer — the
  "only ever easier" rule. Runs that still do not fit stay in the week on a free day.
- Walks (optional, light) fill free days; a walk with no free day left is dropped.
- More days than runs: the runs are spread; nothing is ever added.

Pure: no Django.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from itertools import combinations

from .generator import run_days

HARD = frozenset({"INTERVALS", "TEMPO"})
DROPPABLE = frozenset({"EASY", "RUN_WALK"})
LIGHT = frozenset({"WALK", "REST"})       # not a run: never counts towards the limit


@dataclass(frozen=True)
class Item:
    """One stored workout, reduced to what the re-flow needs."""

    id: int
    date: dt.date
    kind: str
    duration_s: int = 0
    status: str = "planned"           # planned | completed (skipped are left out)


@dataclass
class ReflowResult:
    moves: dict[int, dt.date] = field(default_factory=dict)   # id -> new date
    drops: list[int] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.moves and not self.drops


def _monday(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def is_movable(item: Item, today: dt.date, last_date: dt.date | None) -> bool:
    return (item.status == "planned" and item.kind != "RACE" and item.date > today
            and (last_date is None or item.date <= last_date))


def reflow(items: list[Item], *, available: list[int], long_day: int, limit: int,
           today: dt.date, last_date: dt.date | None = None) -> ReflowResult:
    """Decide new dates for the movable items. `available` are weekdays (0 = Monday);
    `last_date` is the last day anything may be placed on (the day before the race)."""
    available = sorted({int(d) for d in available if 0 <= int(d) <= 6})
    result = ReflowResult()
    if not available:
        return result
    long_wd = long_day if long_day in available else available[-1]
    movable = [i for i in items if is_movable(i, today, last_date)]
    fixed = [i for i in items if not is_movable(i, today, last_date)]
    weeks = sorted({_monday(i.date) for i in movable})
    for monday in weeks:
        _reflow_week(monday, [i for i in movable if _monday(i.date) == monday], fixed,
                     available, long_wd, limit, today, last_date, result)
    return result


def _fits(runs: list[Item], avail_free: list[dt.date], cap: int, long_wd: int) -> bool:
    """True when the week already honours the new days: nothing needs to move."""
    dates = [r.date for r in runs]
    if len(set(dates)) != len(dates) or len(runs) > cap:
        return False
    if any(d not in avail_free for d in dates):
        return False
    long_date = next((d for d in avail_free if d.weekday() == long_wd), None)
    return all(r.date == long_date for r in runs if r.kind == "LONG" and long_date)


def _counts(item: Item, today: dt.date) -> bool:
    """A fixed workout that used up one of the week's run days (a missed past one did not)."""
    return item.kind not in LIGHT and (item.status == "completed" or item.date >= today)


def _reflow_week(monday, runs_and_walks, fixed, available, long_wd, limit, today,
                 last_date, result: ReflowResult) -> None:
    week = [monday + dt.timedelta(days=i) for i in range(7)]
    fixed_by_date = {i.date: i for i in fixed}
    future = [d for d in week if d > today and (last_date is None or d <= last_date)]
    free = [d for d in future if d not in fixed_by_date]
    avail_free = [d for d in free if d.weekday() in available]
    week_fixed = [i for i in fixed if monday <= i.date <= week[-1]]
    cap = max(limit - sum(1 for i in week_fixed if _counts(i, today)), 0)

    order = lambda i: (i.date, i.id)  # noqa: E731
    runs = sorted((i for i in runs_and_walks if i.kind not in LIGHT), key=order)
    walks = sorted((i for i in runs_and_walks if i.kind in LIGHT), key=order)
    if _fits(runs, avail_free, cap, long_wd):
        return

    n_slots = min(cap, len(avail_free))
    # Too many runs: drop the shortest easy ones (never long, hard or race).
    droppable = sorted((r for r in runs if r.kind in DROPPABLE),
                       key=lambda r: (r.duration_s, r.date, r.id))
    while len(runs) > n_slots and droppable:
        gone = droppable.pop(0)
        runs.remove(gone)
        result.drops.append(gone.id)

    placed_n = min(len(runs), n_slots)
    slots: list[dt.date] = []
    if placed_n:
        weekdays = [d.weekday() for d in avail_free]
        long_here = long_wd if long_wd in weekdays else weekdays[-1]
        chosen = run_days(weekdays, long_here, placed_n)
        slots = [d for d in avail_free if d.weekday() in chosen]

    # Which runs get a slot when even the undroppable ones do not all fit.
    priority = sorted(runs, key=lambda r: (r.kind != "LONG", r.kind not in HARD, r.date, r.id))
    placed = sorted(priority[:len(slots)], key=order)
    overflow = sorted(priority[len(slots):], key=order)

    new_dates = _assign(placed, slots, long_wd, fixed_by_date)
    used = set(new_dates.values())
    for run in overflow:
        spot = _nearest_free(run.date, free, used) or run.date
        new_dates[run.id] = spot
        used.add(spot)
    for walk in walks:
        if walk.date in free and walk.date not in used:
            spot = walk.date
        else:
            spot = next((d for d in free if d not in used), None)
        if spot is None:
            result.drops.append(walk.id)
            continue
        new_dates[walk.id] = spot
        used.add(spot)

    for item in runs + walks:
        new = new_dates.get(item.id)
        if new is not None and new != item.date:
            result.moves[item.id] = new


def _nearest_free(day: dt.date, free: list[dt.date], used: set) -> dt.date | None:
    options = [d for d in free if d not in used]
    if not options:
        return None
    return min(options, key=lambda d: (abs((d - day).days), d))


def _assign(runs: list[Item], slots: list[dt.date], long_wd: int,
            fixed_by_date: dict) -> dict[int, dt.date]:
    """Put `runs` (as many as `slots`) on `slots`: long run on the long-run day, hard
    sessions spaced, the rest in their original order."""
    if not runs:
        return {}
    dates: dict[int, dt.date] = {}
    slots = sorted(slots)
    rest = list(runs)
    long_run = next((r for r in rest if r.kind == "LONG"), None)
    long_date = None
    if long_run is not None:
        long_date = next((d for d in slots if d.weekday() == long_wd), slots[-1])
        dates[long_run.id] = long_date
        rest.remove(long_run)
        slots.remove(long_date)

    hard = [r for r in rest if r.kind in HARD]
    easy = [r for r in rest if r.kind not in HARD]
    demanding = {d for d, i in fixed_by_date.items()
                 if i.kind in HARD or i.kind in ("LONG", "RACE")}
    if long_date:
        demanding.add(long_date)

    best = None
    for positions in combinations(range(len(slots)), len(hard)):
        hard_dates = [slots[p] for p in positions]
        easy_dates = [s for k, s in enumerate(slots) if k not in positions]
        penalty = sum(1 for a, b in combinations(hard_dates, 2) if abs((a - b).days) == 1)
        penalty += sum(1 for h in hard_dates for d in demanding if abs((h - d).days) == 1)
        moved = sum(abs((d - r.date).days) for r, d in zip(hard, hard_dates))
        moved += sum(abs((d - r.date).days) for r, d in zip(easy, easy_dates))
        score = (penalty, moved)
        if best is None or score < best[0]:
            best = (score, hard_dates, easy_dates)
    _, hard_dates, easy_dates = best
    dates.update({r.id: d for r, d in zip(hard, hard_dates)})
    dates.update({r.id: d for r, d in zip(easy, easy_dates)})
    return dates
