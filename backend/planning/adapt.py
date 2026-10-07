"""Auto-adjusting the plan after each run (R13 §1). Pure — no Django.

`decide(run, context, upcoming, today)` reads what the last run and this morning say
and returns the changes to make to the next one or two sessions. Like every safety rule
in this package it only ever makes training easier, with one bounded exception:

* **Easier** (the default direction): when strain signals fire, the next session is
  shortened 10–25 %, turned into an easy run or a run/walk, swapped with a later easy
  day, or replaced by rest (a bad pain report). The session after it may be shortened
  too.
* **The single +5 % rule**: after at least three consecutive easy-and-good runs, with
  nothing amiss now, the next EASY / RUN_WALK session may get up to 5 % more running —
  and never more than the room left under that week's own planned volume (`room_s`), so
  the week can never exceed what the plan prescribed.

Never touched: completed / skipped / past sessions, the race, sessions the athlete
edited (moved, applied a check-in, undid an auto change) and sessions already changed
by auto-adjust. The caller filters with `eligible()`; this module re-checks anyway.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

EASY_KINDS = frozenset({"EASY", "RUN_WALK", "LONG"})
HARD_KINDS = frozenset({"INTERVALS", "TEMPO"})
ADJUSTABLE = EASY_KINDS | HARD_KINDS
EXTENDABLE = frozenset({"EASY", "RUN_WALK"})

RPE_EASY_STRAIN = 8
RPE_ANY_STRAIN = 9
HR_HIGH_BPM = 5
HR_VERY_HIGH_BPM = 10
DRIFT_PCT = 8.0
INCOMPLETE = 0.70
VERY_INCOMPLETE = 0.50
READINESS_LOW = 25
SLEEP_DEBT_S = 5 * 3600
DRINKS = 3
LOOKAHEAD_DAYS = 4

# The +5 % rule.
EXTEND_FRACTION = 0.05
EASY_STREAK = 3
GOOD_COMPLETION = 0.90
GOOD_RPE_MAX = 6
GOOD_DRIFT_MAX = 5.0
MIN_EXTEND_S = 60
# Whole minutes: the workout builder rounds running time to the minute, so an extension
# on this grid lands exactly and never rounds past the cap.
GRID_S = 60

# Severity -> (factor for the next session, factor for the one after).
MILD, MODERATE, STRONG = 1, 2, 4
FACTORS = {"mild": (0.90, None), "moderate": (0.80, 0.90), "strong": (0.75, 0.85)}


@dataclass(frozen=True)
class RunFacts:
    """One completed run, as the rules see it."""

    date: dt.date
    planned_kind: str | None = None        # the plan workout it completed, if any
    planned_run_s: int | None = None
    actual_run_s: float | None = None
    rpe: int | None = None
    avg_hr: int | None = None              # HR over the running blocks
    zone_top: int | None = None            # top of the session's target zone (bpm)
    drift_pct: float | None = None


@dataclass(frozen=True)
class Context:
    """This morning and the last days."""

    readiness: int | None = None
    sleep_debt_s: int | None = None
    drinks_last_night: float | None = None
    pain: str | None = None                # None | "watch" | "bad" (R13 §3)
    pain_label: str | None = None          # "your knee (left) has been sore 2 days"
    injury_risk: str = "low"               # low | moderate | high
    recent_runs: list[RunFacts] = field(default_factory=list)   # oldest first


@dataclass(frozen=True)
class Upcoming:
    id: int
    date: dt.date
    kind: str
    run_s: int
    status: str = "planned"
    adjusted_by: str = ""
    moved: bool = False
    completed: bool = False
    room_s: int = 0        # this plan week's planned run seconds minus what is prescribed now


@dataclass(frozen=True)
class Change:
    workout_id: int
    action: str            # shorten | easier | run_walk | rest | swap | extend
    factor: float | None = None
    new_kind: str | None = None
    new_date: dt.date | None = None
    extend_s: int = 0
    group: str | None = None
    swap_with: int | None = None


@dataclass
class Decision:
    severity: str                           # none | mild | moderate | strong | extend
    signals: list[dict]
    why: str
    changes: list[Change]

    @property
    def changed(self) -> bool:
        return bool(self.changes)


def day_word(day: dt.date, today: dt.date) -> str:
    if day == today:
        return "today"
    if day == today - dt.timedelta(days=1):
        return "yesterday"
    return f"on {day:%a}"


def _signal(key: str, weight: int, label: str) -> dict:
    return {"key": key, "weight": weight, "label": label}


def run_signals(run: RunFacts | None, today: dt.date) -> list[dict]:
    if run is None:
        return []
    out = []
    when = day_word(run.date, today)
    easy = run.planned_kind is None or run.planned_kind in EASY_KINDS
    if run.rpe is not None:
        if run.rpe >= RPE_ANY_STRAIN:
            out.append(_signal("rpe", 2, f"your run {when} felt {run.rpe}/10"))
        elif run.rpe >= RPE_EASY_STRAIN and easy:
            out.append(_signal("rpe", 1, f"your easy run {when} felt {run.rpe}/10"))
    if easy and run.avg_hr and run.zone_top:
        over = run.avg_hr - run.zone_top
        if over >= HR_HIGH_BPM:
            out.append(_signal("hr_high", 2 if over >= HR_VERY_HIGH_BPM else 1,
                               f"your HR ran {over} bpm high {when}"))
    if run.drift_pct is not None and run.drift_pct > DRIFT_PCT:
        out.append(_signal("hr_drift", 1, f"your HR drifted {run.drift_pct:.0f}% {when}"))
    if run.planned_run_s and run.actual_run_s is not None and run.planned_run_s > 0:
        ratio = run.actual_run_s / run.planned_run_s
        if ratio < INCOMPLETE:
            out.append(_signal("incomplete", 2 if ratio < VERY_INCOMPLETE else 1,
                               f"you ran {round(ratio * 100)}% of the planned time {when}"))
    return out


def context_signals(ctx: Context) -> list[dict]:
    out = []
    if ctx.readiness is not None and ctx.readiness < READINESS_LOW:
        out.append(_signal("readiness", 1, f"your readiness is {ctx.readiness}"))
    if ctx.sleep_debt_s is not None and ctx.sleep_debt_s >= SLEEP_DEBT_S:
        hours = round(ctx.sleep_debt_s / 3600, 1)
        out.append(_signal("sleep_debt", 1, f"you're {hours:g} h short on sleep this week"))
    if ctx.drinks_last_night is not None and ctx.drinks_last_night >= DRINKS:
        out.append(_signal("alcohol", 1, f"{ctx.drinks_last_night:g} drinks last night"))
    if ctx.pain in ("watch", "bad"):
        out.append(_signal("pain", 4 if ctx.pain == "bad" else 2,
                           ctx.pain_label or "you've reported pain two days running"))
    if ctx.injury_risk == "high":
        out.append(_signal("injury_risk", 2, "your injury risk is high"))
    return out


def severity(signals: list[dict]) -> str:
    score = sum(s["weight"] for s in signals)
    if score >= STRONG:
        return "strong"
    if score >= MODERATE:
        return "moderate"
    if score >= MILD:
        return "mild"
    return "none"


def eligible(w: Upcoming, today: dt.date) -> bool:
    """A session auto-adjust may change. Everything else is the athlete's or done."""
    return (w.status == "planned" and not w.completed and w.date >= today
            and w.kind in ADJUSTABLE and not w.adjusted_by and not w.moved
            and w.date <= today + dt.timedelta(days=LOOKAHEAD_DAYS))


def easy_and_good(run: RunFacts) -> bool:
    if run.planned_kind not in EASY_KINDS:
        return False
    if not run.planned_run_s or run.actual_run_s is None:
        return False
    if run.actual_run_s / run.planned_run_s < GOOD_COMPLETION:
        return False
    if run.rpe is not None and run.rpe > GOOD_RPE_MAX:
        return False
    if run.avg_hr and run.zone_top and run.avg_hr > run.zone_top:
        return False
    if run.drift_pct is not None and run.drift_pct > GOOD_DRIFT_MAX:
        return False
    return True


def extend_seconds(run_s: int, room_s: int) -> int:
    """At most +5 % of the session's running, in whole minutes, never past the room
    left in the week. 0 when that is under a minute."""
    wanted = int(run_s * EXTEND_FRACTION // GRID_S) * GRID_S
    allowed = min(wanted, int(max(room_s, 0) // GRID_S) * GRID_S)
    return allowed if allowed >= MIN_EXTEND_S else 0


def _why(signals: list[dict]) -> str:
    ordered = sorted(signals, key=lambda s: -s["weight"])
    labels = [s["label"] for s in ordered[:2]]
    return " and ".join(labels)


def _ease(w: Upcoming, factor: float, level: str) -> Change:
    if level == "strong" and w.kind != "RUN_WALK":
        return Change(w.id, "run_walk", factor=factor, new_kind="RUN_WALK")
    if w.kind in HARD_KINDS:
        return Change(w.id, "easier", factor=factor if level != "mild" else 1.0,
                      new_kind="EASY")
    return Change(w.id, "shorten", factor=factor)


def _swap_partner(first: Upcoming, sessions: list[Upcoming],
                  all_sessions: list[Upcoming]) -> Upcoming | None:
    """A later easy session this athlete could do first instead of the hard one, such
    that the hard session does not land the day before (or on) a long/hard day."""
    hard_dates = {s.date for s in all_sessions if s.kind in HARD_KINDS | {"LONG", "RACE"}
                  and s.id != first.id}
    for other in sessions:
        if other.id == first.id or other.kind not in {"EASY", "RUN_WALK"}:
            continue
        if other.date <= first.date:
            continue
        next_day = other.date + dt.timedelta(days=1)
        if next_day in hard_dates or other.date in hard_dates:
            continue
        return other
    return None


def decide(run: RunFacts | None, ctx: Context, upcoming: list[Upcoming],
           today: dt.date) -> Decision:
    """`upcoming`: the plan's sessions from today on (any status), date order."""
    signals = run_signals(run, today) + context_signals(ctx)
    level = severity(signals)
    sessions = sorted((w for w in upcoming if eligible(w, today)), key=lambda w: (w.date, w.id))

    if level == "none":
        return _maybe_extend(run, ctx, sessions, today)
    if not sessions:
        return Decision(level, signals, _why(signals), [])

    first_factor, second_factor = FACTORS[level]
    changes: list[Change] = []
    first = sessions[0]
    if ctx.pain == "bad":
        changes.append(Change(first.id, "rest", new_kind="REST"))
    elif level == "mild" and first.kind in HARD_KINDS:
        partner = _swap_partner(first, sessions, upcoming)
        if partner is not None:
            group = f"swap-{first.id}-{partner.id}"
            changes.append(Change(first.id, "swap", new_date=partner.date, group=group,
                                  swap_with=partner.id))
            changes.append(Change(partner.id, "swap", new_date=first.date, group=group,
                                  swap_with=first.id))
        else:
            changes.append(_ease(first, first_factor, level))
    else:
        changes.append(_ease(first, first_factor, level))

    if second_factor is not None and len(sessions) > 1:
        touched = {c.workout_id for c in changes}
        second = next((w for w in sessions[1:] if w.id not in touched), None)
        if second is not None:
            if second.kind in HARD_KINDS:
                changes.append(Change(second.id, "easier", factor=second_factor,
                                      new_kind="EASY"))
            else:
                changes.append(Change(second.id, "shorten", factor=second_factor))
    return Decision(level, signals, _why(signals), changes)


def _maybe_extend(run: RunFacts | None, ctx: Context, sessions: list[Upcoming],
                  today: dt.date) -> Decision:
    none = Decision("none", [], "", [])
    if run is None or ctx.pain or ctx.injury_risk != "low":
        return none
    if ctx.readiness is not None and ctx.readiness < 50:
        return none
    streak = ctx.recent_runs[-EASY_STREAK:]
    if len(streak) < EASY_STREAK or not all(easy_and_good(r) for r in streak):
        return none
    target = next((w for w in sessions if w.kind in EXTENDABLE), None)
    if target is None:
        return none
    extra = extend_seconds(target.run_s, target.room_s)
    if extra <= 0:
        return none
    signal = _signal("easy_streak", 0,
                     f"your last {EASY_STREAK} runs were easy and felt good")
    return Decision("extend", [signal], signal["label"],
                    [Change(target.id, "extend", extend_s=extra)])
