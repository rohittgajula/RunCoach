"""What the rest of the plan becomes after an interruption. Pure — no Django.

`adapt.py` answers "what should the next session be", and answers it well. It
cannot answer the question Rohit kept asking, which is what December looks like
after a sore knee in November: its whole reach is the next session and the one
after it.

    FACTORS = {"mild": (0.90, None), "moderate": (0.80, 0.90), "strong": (0.75, 0.85)}
    #            next session ──┘      and the one after ──┘

Easing two sessions and leaving eleven weeks untouched is not adjusting a plan.
It is adjusting a day, and leaving behind a plan that still expects a volume the
athlete is no longer on course to reach — which they then fail to hit, and read
as their own failure rather than the schedule's.

Three rules, and all three are load-bearing.

**A missed session is lost, not owed.** Nothing is carried forward, ever. Adding
Tuesday's four kilometres onto Thursday is the most common mistake in
self-coached training and the most reliable way to turn a missed easy run into
an injury. The week is simply lighter, and the plan accepts that.

**The ramp restarts from what was actually done.** After an interruption the
curve is rebuilt forward from the last week genuinely completed, under the same
weekly increase cap the original plan obeyed. The other mistake is coming back
from four days off and resuming at the volume you would have reached had you not
stopped — the body was not there for the weeks that built it.

**This only ever reduces.** Like every safety rule in this package, no path
through here returns a week harder than the plan already intended. The worst
case is training slightly less than you could have, which costs a little
fitness; the opposite worst case costs a season.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace

# Phases that are a fraction of what was reached rather than a step up from last
# week, so they follow the rebuilt ramp instead of driving it.
TAPERING = frozenset({"TAPER", "RACE", "PEAK_TAPER"})

# How much of the reached volume a taper week carries. Matches the generator's
# own taper so a rebuilt plan tapers the way an untouched one would.
TAPER_FRACTION = 0.6

# Below this, two weeks are the same week as far as a ramp is concerned, and
# treating a 30-second difference as an interruption would rebuild the plan
# every time somebody stopped for a traffic light.
NOISE_S = 120


@dataclass(frozen=True)
class WeekPlan:
    """One future week of a stored plan, as far as the ramp is concerned."""

    index: int
    start: dt.date
    phase: str
    planned_run_s: int
    is_cutback: bool = False


@dataclass(frozen=True)
class Rebuild:
    weeks: list[WeekPlan]
    #: index -> (before, after) for every week that moved.
    changed: dict[int, tuple[int, int]]
    peak_before_s: int
    peak_after_s: int

    @property
    def anything(self) -> bool:
        return bool(self.changed)


def rebuild(
    weeks: list[WeekPlan],
    achieved_run_s: int,
    from_index: int,
    max_weekly_increase_pct: float = 10.0,
    cutback_factor: float = 0.7,
) -> Rebuild:
    """Recompute every week from `from_index` on, starting from what was done.

    `achieved_run_s` is the running actually completed in the interrupted week —
    not what it prescribed. That figure, and not the schedule, is what the rest
    of the plan grows from.

    Weeks before `from_index` are returned untouched. Rewriting the past would
    quietly change the history the baseline is computed from, and the past is
    not a thing a plan gets to adjust.
    """
    growth = 1 + max_weekly_increase_pct / 100
    out: list[WeekPlan] = []
    changed: dict[int, tuple[int, int]] = {}
    carried: int | None = None

    for week in weeks:
        if week.index < from_index:
            out.append(week)
            continue

        if week.index == from_index:
            # The interrupted week is what it turned out to be, and becomes the
            # floor everything downstream builds from.
            new_s = min(int(achieved_run_s), week.planned_run_s)
            carried = max(new_s, 0)
            out.append(replace(week, planned_run_s=new_s))
            if abs(new_s - week.planned_run_s) > NOISE_S:
                changed[week.index] = (week.planned_run_s, new_s)
            continue

        if carried is None:          # defensive; from_index was past the end
            out.append(week)
            continue

        if week.phase in TAPERING:
            # A taper is a fraction of what was reached, so it follows the
            # rebuilt ramp rather than the one the plan hoped for.
            target = min(week.planned_run_s, int(carried * TAPER_FRACTION))
        elif week.is_cutback:
            # A down week stays a down week. Its job is recovery, and recovery
            # is needed more after an interruption, not less.
            target = min(week.planned_run_s, int(carried * cutback_factor))
        else:
            # Never above what the plan already intended for this week: this
            # module exists to reduce load, not to invent any.
            target = min(week.planned_run_s, int(carried * growth))
            carried = target

        out.append(replace(week, planned_run_s=target))
        if abs(target - week.planned_run_s) > NOISE_S:
            changed[week.index] = (week.planned_run_s, target)

    def peak(rows: list[WeekPlan]) -> int:
        building = [w.planned_run_s for w in rows if w.phase not in TAPERING]
        return max(building) if building else 0

    return Rebuild(
        weeks=out,
        changed=changed,
        peak_before_s=peak(weeks),
        peak_after_s=peak(out),
    )


def describe(result: Rebuild, weeks: list[WeekPlan], limit: int = 4) -> list[str]:
    """The change in sentences an athlete can check against their calendar.

    Written from the rebuild itself rather than by hand, so it cannot claim a
    change that did not happen or miss one that did. An athlete who reports a
    sore knee and is told "noted, rest up" has no way to tell whether anything
    happened; the difference between a coach and a notepad is that the coach
    comes back with the new schedule.
    """
    by_index = {w.index: w for w in weeks}
    lines: list[str] = []

    for index in sorted(result.changed)[:limit]:
        before, after = result.changed[index]
        week = by_index.get(index)
        when = f"Week of {week.start:%-d %b}" if week else f"Week {index + 1}"
        lines.append(
            f"{when}: {before / 60:.0f} → {after / 60:.0f} min of running"
        )

    remaining = len(result.changed) - len(lines)
    if remaining > 0:
        lines.append(f"…and {remaining} more week{'s' if remaining > 1 else ''}.")

    if result.peak_after_s < result.peak_before_s - NOISE_S:
        lines.append(
            f"Your peak week comes down from {result.peak_before_s / 60:.0f} to "
            f"{result.peak_after_s / 60:.0f} minutes. That is the honest "
            "consequence of the time off, not a punishment — the ramp restarts "
            "from where you actually get to."
        )
    return lines
