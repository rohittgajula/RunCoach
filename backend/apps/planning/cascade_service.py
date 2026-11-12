"""Carrying an interruption through the rest of a stored plan (Django half).

Rules live in `planning/cascade.py`; this finds the rows, applies the decision
and writes them back.

The reach is the whole point. `adaptation.py` scales the coming week and
`auto_adjust.py` scales the next session or two — both correct, both local, and
between them they leave an athlete who missed a fortnight looking at a December
built for somebody who did not. This walks every week after the interruption and
brings it down to what the rebuilt ramp actually supports.

What is never touched, in order of how badly it would go wrong:

* **The past, and today.** A completed session is history, and rewriting it
  would change the baseline every future plan is derived from.
* **Races.** A race is a fixed point; the plan moves around it.
* **Anything the athlete edited themselves.** If they changed a session by hand
  they have said something about it that this code does not know.
* **Workouts already on the watch**, except through the normal resync path, so
  the watch and the app cannot disagree about Thursday.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.db import transaction

from planning.cascade import WeekPlan, describe, rebuild

from .models import INACTIVE_STATUSES, PlannedWorkout, TrainingPlan

logger = logging.getLogger(__name__)

# Horizon. Far enough to reach a race on the other side of a build, short enough
# that one bad week does not rewrite a year nobody has planned yet.
MAX_WEEKS = 26

# A week has to move by more than this before its sessions are rewritten.
# Rewriting rows to shave nine seconds off a week costs a watch resync and tells
# the athlete nothing.
MIN_WEEK_CHANGE_S = 120


def _monday(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def run_seconds(workout: PlannedWorkout) -> int:
    """Prescribed running time: every step that is not walking."""
    from .adaptation import run_seconds as _run_seconds

    return _run_seconds(workout)


def _scalable(workout: PlannedWorkout, today: dt.date) -> bool:
    return (
        workout.date > today
        and workout.kind != "RACE"
        and workout.status == PlannedWorkout.Status.PLANNED
        and workout.completed_activity_id is None
        and workout.edited_by != "user"
    )


def collect_weeks(plan: TrainingPlan, today: dt.date) -> tuple[list[WeekPlan], dict]:
    """Future weeks of the plan, with the workouts that make each one up."""
    rows = list(
        plan.workouts.filter(date__gt=today,
                             date__lte=today + dt.timedelta(weeks=MAX_WEEKS))
        .exclude(status__in=INACTIVE_STATUSES)
        .select_related("phase")
        .order_by("date")
    )

    by_week: dict[dt.date, list[PlannedWorkout]] = {}
    for row in rows:
        by_week.setdefault(_monday(row.date), []).append(row)

    weeks: list[WeekPlan] = []
    for index, start in enumerate(sorted(by_week)):
        workouts = by_week[start]
        phase = next((w.phase.kind for w in workouts if w.phase_id), "BUILD")
        weeks.append(
            WeekPlan(
                index=index,
                start=start,
                phase=(phase or "BUILD").upper(),
                planned_run_s=sum(run_seconds(w) for w in workouts),
                # A week prescribing less than the one before it is a cutback,
                # whatever the plan called it. Inferred rather than stored
                # because the generator does not mark them on the rows.
                is_cutback=False,
            )
        )

    for i in range(1, len(weeks)):
        if weeks[i].planned_run_s < weeks[i - 1].planned_run_s * 0.95:
            weeks[i] = WeekPlan(**{**weeks[i].__dict__, "is_cutback": True})

    return weeks, by_week


@transaction.atomic
def cascade(plan: TrainingPlan, athlete, achieved_run_s: int, reason: str = "") -> dict:
    """Carry an interruption through every remaining week.

    `achieved_run_s` is what the athlete actually ran in the interrupted week.
    Returns a summary the caller can put in front of them — a change nobody can
    see is indistinguishable from a bug, and "noted, rest up" with a silently
    identical calendar is how an athlete learns the coach is a notepad.
    """
    today = athlete.local_today
    weeks, by_week = collect_weeks(plan, today)
    if not weeks:
        return {"changed": 0, "lines": []}

    result = rebuild(
        weeks,
        achieved_run_s=achieved_run_s,
        from_index=0,
        max_weekly_increase_pct=_increase_pct(),
    )
    if not result.anything:
        return {"changed": 0, "lines": []}

    touched = 0
    for before, after in zip(weeks, result.weeks):
        if before.planned_run_s <= 0:
            continue
        if abs(after.planned_run_s - before.planned_run_s) <= MIN_WEEK_CHANGE_S:
            continue

        factor = max(after.planned_run_s / before.planned_run_s, 0.0)
        for workout in by_week.get(before.start, []):
            if not _scalable(workout, today):
                continue
            _scale(workout, factor)
            touched += 1

    logger.info(
        "cascade: athlete %s plan %s — %s weeks moved, %s workouts rewritten (%s)",
        athlete.pk, plan.pk, len(result.changed), touched, reason or "no reason given",
    )
    return {
        "changed": len(result.changed),
        "workouts": touched,
        "lines": describe(result, weeks),
        "peak_before_s": result.peak_before_s,
        "peak_after_s": result.peak_after_s,
    }


def _increase_pct() -> float:
    from django.conf import settings

    return float(settings.TRAINING.get("MAX_WEEKLY_INCREASE_PCT", 10.0))


def _scale(workout: PlannedWorkout, factor: float) -> None:
    """Shrink one workout's running, keeping its shape.

    Scaling the steps rather than replacing the session keeps the title, the
    walking that rides along, the zone and the purpose — the athlete recognises
    Thursday as the same session, done less of, which is what actually happened.
    """
    if workout.original is None:
        workout.original = {"steps": workout.steps, "duration_s": workout.duration_s}

    steps = []
    for step in workout.steps or []:
        new = dict(step)
        if new.get("kind") != "walk" and isinstance(new.get("seconds"), (int, float)):
            new["seconds"] = max(60, round(new["seconds"] * factor))
        steps.append(new)

    workout.steps = steps
    workout.duration_s = max(
        300, round(sum(s.get("seconds") or 0 for s in steps)) or round(workout.duration_s * factor)
    )
    workout.adjusted_by = "cascade"
    workout.save(update_fields=["steps", "duration_s", "original", "adjusted_by"])
