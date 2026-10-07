"""Strength sessions in the calendar (R13 §4). Pure — no Django.

`place()` decides which days get a 20-minute strength session; `session()` decides
what is in it. Rules:

* a non-run day first (a rest day or an optional walk day);
* only when there are not enough of those, after an easy run (EASY / RUN_WALK);
* never the day before a long run, a hard session (intervals, tempo) or the race, never
  on the race day or in the last 5 days before it, never on a long/hard day itself;
* never two days in a row, spread across the week;
* nothing in the past (today counts only when `include_today`).

The exercises are the Guides' strength set (frontend StrengthGuide.tsx). Every two
weeks the dose steps up one level (more reps / longer holds, a third set from level 3),
capped at level 6.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

DURATION_S = 20 * 60
MAX_PER_WEEK = 3
SUGGESTED_PER_WEEK = 2
LEVEL_EVERY_WEEKS = 2
MAX_LEVEL = 6
RACE_BUFFER_DAYS = 5

RUN_KINDS = frozenset({"EASY", "RUN_WALK", "LONG", "INTERVALS", "TEMPO", "RACE"})
DEMANDING = frozenset({"LONG", "INTERVALS", "TEMPO", "RACE"})
AFTER_RUN_OK = frozenset({"EASY", "RUN_WALK"})

# key -> (name, base reps | None, base seconds | None, per side, rep step, seconds step, cue)
EXERCISES: list[tuple[str, str, int | None, int | None, bool, int, int, str]] = [
    ("calf", "Calf raise", 12, None, False, 2, 0,
     "Slow up, slower down. Single-leg once easy."),
    ("bridge", "Glute bridge", 10, None, False, 2, 0,
     "Squeeze glutes, ribs down, pause 2 s at the top."),
    ("split", "Split squat", 6, None, True, 1, 0,
     "Front knee over the toes, torso tall, lower slowly."),
    ("plank", "Plank", None, 20, False, 0, 5, "Straight line head to heels; breathe."),
    ("side", "Side plank", None, 15, True, 0, 4, "Hips high, body in one line."),
    ("clam", "Clamshell", 12, None, True, 2, 0,
     "Heels together, open the top knee, don't roll back."),
    ("askip", "A-skip", None, 20, False, 0, 2,
     "Knee to hip height, land under you, quick and light."),
    ("hipflexor", "Hip-flexor stretch", None, 30, True, 0, 0,
     "Tuck the pelvis, gently push hips forward."),
]
REST_S = 30


@dataclass(frozen=True)
class Day:
    date: dt.date
    kinds: tuple[str, ...] = ()      # planned kinds that day (not skipped)


def level_for(start: dt.date, day: dt.date) -> int:
    weeks = max((day - start).days, 0) // 7
    return min(1 + weeks // LEVEL_EVERY_WEEKS, MAX_LEVEL)


def exercises(level: int) -> list[dict]:
    level = max(1, min(level, MAX_LEVEL))
    sets = 2 if level < 3 else 3
    out = []
    for key, name, reps, seconds, per_side, rep_step, sec_step, cue in EXERCISES:
        out.append({
            "key": key, "name": name,
            "sets": 2 if key == "hipflexor" else sets,
            "reps": reps + rep_step * (level - 1) if reps is not None else None,
            "seconds": seconds + sec_step * (level - 1) if seconds is not None else None,
            "per_side": per_side, "rest_s": REST_S, "cue": cue,
        })
    return out


def title_for(level: int) -> str:
    return f"Strength & drills · level {level}"


def _blocked(days: dict[dt.date, Day], day: dt.date, race_date: dt.date | None) -> bool:
    kinds = set(days.get(day, Day(day)).kinds)
    tomorrow = set(days.get(day + dt.timedelta(days=1), Day(day)).kinds)
    if kinds & DEMANDING or tomorrow & DEMANDING:
        return True
    if race_date is not None and race_date - dt.timedelta(days=RACE_BUFFER_DAYS) <= day:
        return True
    return False


def _spread(candidates: list[dt.date], n: int, taken: list[dt.date]) -> list[dt.date]:
    """Pick up to n dates, never adjacent to each other or to `taken`, spread out:
    greedily take the candidate farthest from everything already chosen."""
    chosen = list(taken)
    picked: list[dt.date] = []
    pool = sorted(candidates)
    while len(picked) < n:
        options = [d for d in pool if all(abs((d - c).days) > 1 for c in chosen)]
        if not options:
            break
        if not chosen:
            best = options[0]
        else:
            best = max(options, key=lambda d: (min(abs((d - c).days) for c in chosen), -d.toordinal()))
        picked.append(best)
        chosen.append(best)
        pool.remove(best)
    return sorted(picked)


def place(days: list[Day], per_week: int, first_day: dt.date, last_day: dt.date,
          race_date: dt.date | None = None) -> list[tuple[dt.date, bool]]:
    """[(date, after_run)] for every ISO week touching first_day..last_day."""
    per_week = max(0, min(per_week, MAX_PER_WEEK))
    if per_week == 0 or last_day < first_day:
        return []
    by_date = {d.date: d for d in days}
    out: list[tuple[dt.date, bool]] = []
    week = first_day - dt.timedelta(days=first_day.weekday())
    while week <= last_day:
        dates = [week + dt.timedelta(days=i) for i in range(7)]
        dates = [d for d in dates if first_day <= d <= last_day]
        free, after = [], []
        for day in dates:
            if _blocked(by_date, day, race_date):
                continue
            kinds = set(by_date.get(day, Day(day)).kinds)
            if not kinds & RUN_KINDS:
                free.append(day)
            elif kinds & RUN_KINDS <= AFTER_RUN_OK:
                after.append(day)
        picked = _spread(free, per_week, [])
        after_picked = _spread(after, per_week - len(picked), picked) \
            if len(picked) < per_week else []
        out += [(d, False) for d in picked] + [(d, True) for d in after_picked]
        week += dt.timedelta(days=7)
    return sorted(out)
