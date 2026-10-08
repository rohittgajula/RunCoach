"""Apply `planning.reflow` to the athlete's active plan when their training days change.

The plan is not regenerated: workouts keep everything but their date (see the pure
module for the rules). Moved workouts that are on the watch are re-sent; dropped ones
are deleted here and on Garmin.

Dropped workouts are DELETED rather than marked skipped: "skipped" means the athlete
chose not to do a session, and it would count against them in compliance and the
weekly adaptation. A session that no longer fits the days they chose was never theirs
to skip. The plan keeps a record in `summary.reflows`.

`PlanAdjustment` is deliberately not used for that record: its (plan, week_start)
row is the weekly adaptation's idempotency key, so writing one here would stop the
adaptation reviewing that week.
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.utils import timezone

from planning.generator import MAX_RUN_DAYS, run_day_limit
from planning.reflow import Item, reflow

from .garmin_sync import forget_on_garmin, resync_on_garmin
from .models import PlannedWorkout, TrainingPlan
from .plan_services import config_from_settings

REASON = "training days changed"
KEEP_RECORDS = 20


def _limit(plan: TrainingPlan, athlete=None) -> int:
    """Run days per week, the generator's rule on the baseline the plan was built on.
    A plan without a stored baseline gets the regular cap (never more drops). The
    athlete's own `runs_per_week` (R8 §A) wins when set."""
    config = config_from_settings()
    if athlete is not None and athlete.runs_per_week:
        return min(int(athlete.runs_per_week), MAX_RUN_DAYS)
    km = ((plan.summary or {}).get("baseline") or {}).get("run_km_per_week")
    if km is None:
        return config.max_run_days
    return run_day_limit(float(km), config)


def _phase_for(phases, day: dt.date):
    return next((p for p in phases if p.start <= day <= p.end), None)


@transaction.atomic
def reflow_active_plan(athlete) -> dict | None:
    """Move the active plan's future workouts onto the athlete's current days.

    Returns {moved, dropped, watch_updated, watch_removed}, or None when there is no
    active plan or nothing had to change.
    """
    plan = (TrainingPlan.objects.select_for_update(of=("self",))
            .filter(athlete=athlete, status=TrainingPlan.Status.ACTIVE)
            .select_related("race").first())
    if plan is None:
        return None
    today = athlete.local_today
    available = [int(d) for d, on in (athlete.available_days or {}).items() if on]
    last_date = plan.race.date - dt.timedelta(days=1) if plan.race else None

    workouts = {w.pk: w for w in plan.workouts.exclude(status=PlannedWorkout.Status.SKIPPED)}
    items = [Item(id=w.pk, date=w.date, kind=w.kind, duration_s=w.duration_s, status=w.status,
                  edited=w.edited_by == "user")
             for w in workouts.values()]
    result = reflow(items, available=available, long_day=athlete.long_run_day,
                    limit=_limit(plan, athlete), today=today, last_date=last_date)

    summary = dict(plan.summary or {})
    summary["available_days"] = athlete.available_days
    summary["long_run_day"] = athlete.long_run_day
    if result.empty:
        plan.summary = summary
        plan.save(update_fields=["summary"])
        return None

    phases = list(plan.phases.all())
    moved = []
    for pk, new_date in result.moves.items():
        workout = workouts[pk]
        original = workout.moved_from or workout.date
        workout.moved_from = None if new_date == original else original
        workout.date = new_date
        workout.phase = _phase_for(phases, new_date) or workout.phase
        workout.save(update_fields=["date", "moved_from", "phase"])
        moved.append(pk)

    doomed = [workouts[pk] for pk in result.drops]
    watch_removed = forget_on_garmin(athlete, doomed)
    PlannedWorkout.objects.filter(athlete=athlete, pk__in=result.drops).delete()
    watch_updated = resync_on_garmin(athlete, moved)

    record = {"moved": len(moved), "dropped": len(doomed), "watch_updated": watch_updated,
              "watch_removed": watch_removed}
    summary["reflows"] = ([*summary.get("reflows", []), {
        **record, "reason": REASON, "at": timezone.now().isoformat(),
        "available_days": athlete.available_days, "long_run_day": athlete.long_run_day,
    }])[-KEEP_RECORDS:]
    plan.summary = summary
    plan.save(update_fields=["summary"])
    return record
