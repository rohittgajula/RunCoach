"""Turning a generator Session into a structured workout: title, steps, load.

The generator decides *how much* (run minutes, walk minutes, the long run's unbroken
target). This module only decides *how it is laid out* — warm-up, blocks, recoveries,
cool-down — and never changes the total. That invariant is tested: the steps of every
workout sum to exactly its duration, because the workout bar draws every block at a
width proportional to its time and a bar that disagrees with the stated duration is a
bug the athlete can see.

Pure: bands come in as plain numbers, so there is no Django here.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from analysis.load import session_load

from .generator import Session

Band = tuple[int, int] | None

# Run-block length per kind, seconds. Run/walk sessions take short blocks; an easy run
# takes long ones. The long run uses the generator's continuous target instead.
BLOCK_S = {"RUN_WALK": 240, "EASY": 600, "LONG": 900}
WARM_WALK_MAX_S = 300
STRIDES = 4
STRIDE_S = 30
STRIDE_RECOVERY_S = 60
# Prescribed blocks land on this grid (half minutes); totals, warm-ups, cool-downs and
# titles on whole minutes. "Run 3.7m" is not something anyone can follow on a watch.
BLOCK_GRID_S = 30
MINUTE_S = 60
# Strides appear on easy runs once the plan is past its foundation: a little speed,
# no fatigue. Not before — a beginner's first weeks are about the aerobic base only.
STRIDE_PHASES = {"SPECIFIC", "PEAK", "TAPER"}


@dataclass(frozen=True)
class Bands:
    """Pace (s/km, fast edge first) and HR bands per intensity."""

    easy_pace: Band
    moderate_pace: Band = None
    hard_pace: Band = None
    hr_easy: Band = None
    hr_moderate: Band = None
    hr_hard: Band = None


@dataclass
class Step:
    kind: str           # warmup|run|walk|stride|recovery|cooldown|interval
    duration_s: int
    intensity: str      # walk|easy|moderate|hard
    label: str
    pace_min_s: int | None = None
    pace_max_s: int | None = None
    hr_min: int | None = None
    hr_max: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class WorkoutSpec:
    title: str
    kind: str
    duration_s: int
    load: float
    steps: list[Step] = field(default_factory=list)
    description: str = ""
    purpose: str = ""
    target_zone: str | None = None

    @property
    def run_s(self) -> int:
        return sum(s.duration_s for s in self.steps if s.intensity != "walk")

    @property
    def walk_s(self) -> int:
        return sum(s.duration_s for s in self.steps if s.intensity == "walk")


def _m(seconds: float) -> str:
    """Clock format, as a watch shows it: 210 -> "3:30", 45 -> "45s"."""
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}:{seconds % 60:02d}"


def _floor(seconds: float, grid: int) -> int:
    return int(seconds // grid) * grid


def _round(seconds: float, grid: int) -> int:
    return int(round(seconds / grid)) * grid


def _split(total: int, parts: int, grid: int = 1) -> list[int]:
    """`parts` integers on `grid`, summing to exactly `total` (a multiple of grid)."""
    if parts <= 0:
        return []
    units = total // grid
    base, extra = divmod(units, parts)
    return [(base + (1 if i < extra else 0)) * grid for i in range(parts)]


class _Builder:
    def __init__(self, bands: Bands):
        self.bands = bands
        self.steps: list[Step] = []

    def add(self, kind: str, seconds: int, intensity: str, label: str) -> None:
        if seconds <= 0:
            return
        pace = {"easy": self.bands.easy_pace, "moderate": self.bands.moderate_pace,
                "hard": self.bands.hard_pace}.get(intensity)
        if kind == "stride":
            pace = None   # strides are by feel; a pace target on 20 s is noise
        hr = {"easy": self.bands.hr_easy, "moderate": self.bands.hr_moderate,
              "hard": self.bands.hr_hard}.get(intensity)
        self.steps.append(Step(
            kind=kind, duration_s=int(seconds), intensity=intensity, label=label,
            pace_min_s=pace[0] if pace else None, pace_max_s=pace[1] if pace else None,
            hr_min=hr[0] if hr else None, hr_max=hr[1] if hr else None,
        ))


def _warm_cool(walk_s: int) -> tuple[int, int, int]:
    """(warm-up walk, cool-down walk, walk left for between blocks)."""
    if walk_s < 120:
        return 0, walk_s, 0
    warm = min(WARM_WALK_MAX_S, _floor(walk_s // 3, MINUTE_S))
    cool = min(WARM_WALK_MAX_S, _floor((walk_s - warm) // 2, MINUTE_S))
    return warm, cool, walk_s - warm - cool


def _blocks(b: _Builder, run_s: int, mid_walk: int, block_s: int, run_label: str) -> int:
    """Run blocks separated by walks. Returns walk seconds not used (goes to cool-down)."""
    n = max(1, math.ceil(run_s / block_s)) if block_s else 1
    if mid_walk <= 0:
        n = 1
    runs = _split(run_s, n, BLOCK_GRID_S)
    walks = _split(mid_walk, n - 1, BLOCK_GRID_S) if n > 1 else []
    for i, seconds in enumerate(runs):
        b.add("run", seconds, "easy", f"{run_label} {_m(seconds)}")
        if i < len(walks):
            b.add("walk", walks[i], "walk", f"Walk {_m(walks[i])}")
    return 0 if n > 1 else mid_walk


def build_workout(
    session: Session,
    bands: Bands,
    phase: str,
    *,
    race_name: str | None = None,
    race_km: float | None = None,
    race_pace_s_per_km: float | None = None,
) -> WorkoutSpec:
    # Whole minutes first; every block below is derived from these, so the steps still
    # sum exactly to the duration and nothing lands off the half-minute grid.
    run_s = _round(session.run_minutes * 60, MINUTE_S)
    walk_s = _round(session.walk_minutes * 60, MINUTE_S)
    if session.run_minutes > 0 and run_s == 0:
        run_s = MINUTE_S
    if session.walk_minutes > 0 and walk_s == 0:
        walk_s = MINUTE_S
    b = _Builder(bands)
    kind = session.kind
    title = ""
    summary = ""

    if kind == "RACE":
        race_s = _round((race_km or 0) * (race_pace_s_per_km or 480), MINUTE_S)
        b.add("warmup", WARM_WALK_MAX_S, "walk", "Walk warm-up")
        b.add("run", race_s, "hard", f"Race {race_km:g} km" if race_km else "Race")
        title = f"Race day: {race_name}" if race_name else "Race day"
        summary = "Start slower than you want to. Walk breaks are allowed and smart."

    elif kind == "INTERVALS":
        warm_walk = min(WARM_WALK_MAX_S, _floor(walk_s // 2, MINUTE_S))
        warm_jog = min(600, _round(run_s * 0.35, MINUTE_S))
        hard = round(run_s * 0.35)
        reps = min(8, max(3, round(hard / 120)))
        rep_s = max(BLOCK_GRID_S, _floor(hard / reps, BLOCK_GRID_S))
        hard = rep_s * reps
        if warm_jog + hard > run_s:
            warm_jog = max(0, _floor(run_s - hard, BLOCK_GRID_S))
        walk_left = walk_s - warm_walk
        recovery = min(120, _floor(walk_left // reps, BLOCK_GRID_S)) if reps > 1 else 0
        jog_recovery = recovery < 30
        if jog_recovery:
            recovery = 0
        b.add("warmup", warm_walk, "walk", "Walk warm-up")
        b.add("warmup", warm_jog, "easy", f"Easy jog {_m(warm_jog)}")
        run_left = run_s - warm_jog - hard
        for i in range(reps):
            b.add("interval", rep_s, "hard", f"Rep {i + 1}/{reps} · {_m(rep_s)} hard")
            if i < reps - 1:
                if jog_recovery:
                    jog = min(90, max(_floor(run_left // reps, BLOCK_GRID_S), 0))
                    b.add("recovery", jog, "easy", f"Easy jog {_m(jog)}")
                    run_left -= jog
                else:
                    b.add("recovery", recovery, "walk", f"Walk {_m(recovery)}")
                    walk_left -= recovery
        b.add("cooldown", run_left, "easy", f"Easy jog {_m(run_left)}")
        b.add("cooldown", walk_left, "walk", "Walk cool-down")
        title = f"Intervals {reps} × {_m(rep_s)}"
        summary = f"{reps} × {_m(rep_s)} controlled hard, easy in between."

    elif kind == "TEMPO":
        warm_walk = min(WARM_WALK_MAX_S, _floor(walk_s // 2, MINUTE_S))
        warm_jog = min(600, _round(run_s * 0.3, MINUTE_S))
        tempo = _round(run_s * 0.4, MINUTE_S)
        b.add("warmup", warm_walk, "walk", "Walk warm-up")
        b.add("warmup", warm_jog, "easy", f"Easy jog {_m(warm_jog)}")
        b.add("run", tempo, "moderate", f"Tempo {_m(tempo)}")
        b.add("cooldown", run_s - warm_jog - tempo, "easy", "Easy jog")
        b.add("cooldown", walk_s - warm_walk, "walk", "Walk cool-down")
        title = f"Tempo run {round(tempo / 60)}m"
        summary = f"{_m(tempo)} comfortably hard in the middle of an easy run."

    else:  # EASY, RUN_WALK, LONG, WALK
        warm, cool, mid = _warm_cool(walk_s)
        strides = (
            kind == "EASY" and phase in STRIDE_PHASES and run_s >= 1200
            and mid + cool >= STRIDES * STRIDE_RECOVERY_S
        )
        stride_run = STRIDES * STRIDE_S if strides else 0
        if strides:
            take = STRIDES * STRIDE_RECOVERY_S
            from_mid = min(mid, take)
            mid -= from_mid
            cool -= take - from_mid

        if kind == "WALK":
            b.add("walk", walk_s, "walk", f"Walk {_m(walk_s)}")
        else:
            b.add("warmup", warm, "walk", "Walk warm-up")
            block = BLOCK_S.get(kind, 600)
            if kind == "LONG" and session.continuous_target_s:
                block = max(120, _round(session.continuous_target_s, BLOCK_GRID_S))
            label = "Run" if kind != "EASY" else "Easy run"
            cool += _blocks(b, run_s - stride_run, mid, block, label)
            if strides:
                for i in range(STRIDES):
                    b.add("stride", STRIDE_S, "hard", f"Stride {i + 1}/{STRIDES} — relaxed, quick")
                    b.add("recovery", STRIDE_RECOVERY_S, "walk", "Walk back")
            b.add("cooldown", cool, "walk", "Walk cool-down")

        total = run_s + walk_s
        runs = [s for s in b.steps if s.kind == "run"]
        if kind == "LONG":
            title = f"Long run {round(total / 60)}m"
        elif kind == "RUN_WALK":
            title = f"{round(total / 60)}m run/walk"
        elif kind == "WALK":
            title = f"{round(total / 60)}m easy walk"
        elif strides:
            title = f"Easy run + {STRIDES} relaxed strides"
        else:
            title = f"{round(total / 60)}m easy aerobic run"
        if len(runs) > 1:
            summary = f"{len(runs)} run blocks of about {_m(runs[0].duration_s)} with walks between."
        elif runs:
            summary = f"One continuous {_m(runs[0].duration_s)} run."

    steps = b.steps
    duration = sum(s.duration_s for s in steps)
    run_minutes = sum(s.duration_s for s in steps if s.intensity != "walk") / 60
    walk_minutes = sum(s.duration_s for s in steps if s.intensity == "walk") / 60

    return WorkoutSpec(
        title=title,
        kind=kind,
        duration_s=duration,
        # The SAME formula as actual activities, so planned and done are comparable.
        load=session_load(run_minutes, walk_minutes),
        steps=steps,
        description=" ".join(p for p in (summary, f"Effort: {session.effort}.") if p),
        purpose=session.purpose,
        target_zone=session.target_zone,
    )


# R7 §3: the easy-day pace guard shown on easy / long / run-walk workouts.
GUARD_KINDS = {"EASY", "LONG", "RUN_WALK"}
GUARD_CADENCE_TARGET = 160     # the low edge of analysis.insights.CADENCE_TARGET


def easy_guard(kind: str, *, z2_high: int | None, hr_ceiling: int | None,
               easy_pace: Band) -> dict | None:
    """{hr_max, pace_min_s, pace_max_s, cadence_target}, or None for other kinds.

    hr_max is the top of Z2 when the athlete has zones, else their HR ceiling.
    """
    if kind not in GUARD_KINDS:
        return None
    return {
        "hr_max": z2_high or hr_ceiling,
        "pace_min_s": easy_pace[0] if easy_pace else None,
        "pace_max_s": easy_pace[1] if easy_pace else None,
        "cadence_target": GUARD_CADENCE_TARGET,
    }
