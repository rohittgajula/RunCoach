"""Re-lay a stored plan's future weeks with a different number of runs (R8 §A).

When the athlete changes `runs_per_week`, each future week keeps its running volume
(the prescribed run seconds already in it — adaptation included) and its phase; only
the split changes. The generator's own layout (`_lay_out_week`) does the splitting, so
long-run share, hard-session rules, the 6-day maximum and the 15-minute minimum
session are the same rules a new plan gets.

The generator works in km at a pace; here a fixed pseudo pace converts the stored run
seconds to km and back, so the run time in and out is the same. The walking that rode
along is scaled so the week's walking time is kept too.

Pure: no Django.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .generator import (
    PHASE_SHAPE, Baseline, PlanConfig, Session, Week, _lay_out_week,
)

PSEUDO_PACE_S_PER_KM = 360.0
RUN_KINDS = frozenset({"RUN_WALK", "EASY", "LONG", "INTERVALS", "TEMPO"})


@dataclass(frozen=True)
class WeekVolume:
    start: dt.date                 # first day of the plan week (7-day block)
    phase: str                     # generator phase (FOUNDATION, AEROBIC, ...)
    run_s: float                   # prescribed running seconds across the week's runs
    walk_s: float                  # walking seconds across them (warm-ups included)
    long_continuous_s: float | None = None


def relayout_week(week: WeekVolume, *, available_days: dict, long_run_day: int,
                  runs: int, config: PlanConfig | None = None,
                  blocked: frozenset = frozenset(),
                  last_date: dt.date | None = None) -> tuple[list[Session], list[str]]:
    """The week's run sessions for `runs` run days (fewer when sessions would be shorter
    than 15 min — the note says so). Optional walks are not returned. Sessions never
    land on `blocked` dates or after `last_date`."""
    config = config or PlanConfig()
    if week.phase not in PHASE_SHAPE or week.phase == "RACE" or week.run_s <= 0:
        return [], []
    available = {str(d): bool(available_days.get(str(d))) and _open(week.start, d, blocked,
                                                                         last_date)
                 for d in range(7)}
    if not any(available.values()):
        return [], []
    baseline = Baseline(
        run_km_per_week=week.run_s / PSEUDO_PACE_S_PER_KM, longest_run_s=0.0,
        run_pace_s_per_km=PSEUDO_PACE_S_PER_KM, walk_pace_s_per_km=900.0,
        available_days=available, long_run_day=long_run_day, runs_per_week=runs,
    )
    gweek = Week(index=0, weeks_out=1, phase=week.phase, start_date=week.start,
                 planned_run_km=week.run_s / PSEUDO_PACE_S_PER_KM,
                 continuous_target_s=week.long_continuous_s or 0.0, is_cutback=False)
    notes: list[str] = []
    sessions = [s for s in _lay_out_week(gweek, baseline, config, notes)
                if not s.optional and s.kind in RUN_KINDS]
    for s in sessions:
        s.target_run_m = 0.0          # pseudo-pace distance would be meaningless
        if s.kind == "LONG" and not week.long_continuous_s:
            s.continuous_target_s = None
    generated_walk = sum(s.walk_minutes for s in sessions)
    if generated_walk > 0:
        factor = (week.walk_s / 60) / generated_walk
        for s in sessions:
            s.walk_minutes = round(s.walk_minutes * factor, 1)
    return sessions, [n.replace(f"{gweek.planned_run_km:g} km", "the week's volume")
                      for n in notes]


def _open(start: dt.date, weekday: int, blocked, last_date) -> bool:
    day = start + dt.timedelta(days=(weekday - start.weekday()) % 7)
    return day not in blocked and (last_date is None or day <= last_date)
