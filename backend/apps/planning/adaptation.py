"""Weekly plan adaptation (R6 §2), the Django half. Rules: planning/adaptation.py.

Runs after each sync and on Monday morning. Idempotent per ISO week: the first run in
a week writes a PlanAdjustment row for it, and every later run that week finds the row
and does nothing — so a sync on Tuesday cannot shrink the week a second time.
"""

from __future__ import annotations

import datetime as dt
import logging
import re

from django.db import IntegrityError, transaction

from apps.activities.models import Activity
from apps.athletes.models import Athlete
from nutrition.fueling import fueling_for
from nutrition.targets import FALLBACK_WEIGHT_KG
from planning.adaptation import decide
from planning.generator import Session
from planning.workouts import build_workout

from .models import INACTIVE_STATUSES, PlanAdjustment, PlannedWorkout, TrainingPlan

logger = logging.getLogger(__name__)


def run_seconds(workout: PlannedWorkout) -> int:
    """Prescribed running time: every step that is not walking."""
    return sum(int(s.get("duration_s") or 0) for s in (workout.steps or [])
               if s.get("intensity") != "walk")


def _walk_seconds(workout: PlannedWorkout) -> int:
    return sum(int(s.get("duration_s") or 0) for s in (workout.steps or [])
               if s.get("intensity") == "walk")


def _effort(description: str) -> str:
    match = re.search(r"Effort: (.+?)\.?$", description or "")
    return match.group(1) if match else "easy"


def rescale(workout: PlannedWorkout, factor: float, athlete: Athlete) -> None:
    """Rebuild a workout at `factor` of its volume through the normal builder, so the
    steps stay on the half-minute grid and planned load uses the same formula."""
    from .plan_store import bands_for

    longest = max((int(s.get("duration_s") or 0) for s in workout.steps or []
                   if s.get("kind") == "run"), default=0)
    session = Session(
        date=workout.date, kind=workout.kind,
        run_minutes=run_seconds(workout) * factor / 60,
        walk_minutes=_walk_seconds(workout) * factor / 60,
        target_run_m=0.0, purpose=workout.purpose, effort=_effort(workout.description),
        continuous_target_s=longest * factor if workout.kind == "LONG" and longest else None,
        target_zone=workout.target_zone,
    )
    phase = workout.phase.generator_phase if workout.phase else "FOUNDATION"
    spec = build_workout(session, bands_for(athlete), phase)
    workout.title = spec.title[:120]
    workout.duration_s = spec.duration_s
    workout.load = spec.load
    workout.steps = [s.as_dict() for s in spec.steps]
    workout.description = spec.description
    workout.fueling = fueling_for(spec.kind, spec.duration_s,
                                  athlete.weight_kg or FALLBACK_WEIGHT_KG).as_dict()
    workout.save(update_fields=["title", "duration_s", "load", "steps", "description",
                                "fueling"])


def _accepted_on(plan: TrainingPlan, athlete: Athlete) -> dt.date | None:
    if plan.accepted_at is None:
        return None
    return plan.accepted_at.astimezone(athlete.local_now.tzinfo).date()


def adapt_week(athlete: Athlete, today: dt.date | None = None) -> PlanAdjustment | None:
    plan = TrainingPlan.objects.filter(athlete=athlete, status=TrainingPlan.Status.ACTIVE).first()
    if plan is None:
        return None
    today = today or athlete.local_today
    this_monday = today - dt.timedelta(days=today.weekday())
    reviewed = this_monday - dt.timedelta(days=7)

    existing = PlanAdjustment.objects.filter(plan=plan, week_start=this_monday).first()
    if existing is not None:
        return existing

    planned = list(plan.workouts.filter(
        date__gte=reviewed, date__lt=this_monday,
    ).exclude(status__in=INACTIVE_STATUSES))
    if not planned:
        return None        # the plan had not started last week: nothing to compare

    count_from = max(reviewed, _accepted_on(plan, athlete) or reviewed)
    actual_run_s = sum(
        a.metrics.run_duration_s
        for a in Activity.objects.filter(
            athlete=athlete, local_date__gte=count_from, local_date__lt=this_monday,
        ).select_related("metrics")
        if getattr(a, "metrics", None) is not None
    )
    planned_run_s = sum(run_seconds(w) for w in planned)
    upcoming = list(plan.workouts.filter(
        date__gte=this_monday, date__lt=this_monday + dt.timedelta(days=7),
    ).exclude(status__in=INACTIVE_STATUSES).select_related("phase"))
    decision = decide(planned_run_s, actual_run_s, sum(run_seconds(w) for w in upcoming))

    try:
        with transaction.atomic():
            adjustment = PlanAdjustment.objects.create(
                athlete=athlete, plan=plan, week_start=this_monday, reason=decision.reason,
                factor=decision.factor, planned_run_s=round(planned_run_s),
                actual_run_s=round(actual_run_s),
            )
            if decision.factor < 1.0:
                for workout in upcoming:
                    # Only future, not-completed workouts; the race is never resized.
                    # R16: a session the athlete edited keeps their version.
                    if (workout.date >= today and workout.kind != "RACE"
                            and workout.status == PlannedWorkout.Status.PLANNED
                            and workout.completed_activity_id is None
                            and workout.edited_by != "user"):
                        rescale(workout, decision.factor, athlete)
    except IntegrityError:
        # Another worker adapted this week between the check and the insert.
        return PlanAdjustment.objects.filter(plan=plan, week_start=this_monday).first()
    logger.info("adapted plan %s for week %s: %s", plan.pk, this_monday, decision.rule)
    return adjustment
