"""Plan adaptation on a schedule (R6 §2). Routed to the `planning` queue."""

from __future__ import annotations

from celery import shared_task

from apps.athletes.models import Athlete


@shared_task(name="planning.adapt_week")
def adapt_week_task(athlete_id: int) -> dict:
    from .adaptation import adapt_week

    athlete = Athlete.objects.filter(pk=athlete_id).first()
    if athlete is None:
        return {"skipped": "gone"}
    adjustment = adapt_week(athlete)
    if adjustment is None:
        return {"athlete": athlete_id, "adjusted": False}
    return {"athlete": athlete_id, "week_start": str(adjustment.week_start),
            "factor": adjustment.factor}


@shared_task(name="planning.adapt_all")
def adapt_all() -> dict:
    """Monday morning: every athlete with an active plan."""
    from .models import TrainingPlan

    ids = list(TrainingPlan.objects.filter(status=TrainingPlan.Status.ACTIVE)
               .values_list("athlete_id", flat=True))
    for athlete_id in ids:
        adapt_week_task.delay(athlete_id)
    return {"queued": len(ids)}


@shared_task(name="planning.garmin_push")
def garmin_push_task(athlete_id: int, workout_ids: list[int], action: str = "send") -> dict:
    """R7 §3. Routed to the `garmin` queue (see CELERY_TASK_ROUTES)."""
    from .garmin_push import run_job

    return run_job(athlete_id, workout_ids, action)


@shared_task(name="planning.garmin_forget")
def garmin_forget_task(athlete_id: int, refs: list[list]) -> dict:
    """Delete Garmin copies of workouts removed by a plan change (garmin queue)."""
    from .garmin_push import forget_remote

    return forget_remote(athlete_id, refs)


# How long a request waits for the garmin queue. A long sync can hold the queue (it
# runs at concurrency 1); the athlete then gets a 503 and tries again.
GARMIN_PUSH_WAIT_S = 90


def run_garmin_push(athlete_id: int, workout_ids: list[int], action: str) -> dict:
    """Run the push on the garmin queue and wait for its per-workout results."""
    from django.conf import settings

    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return garmin_push_task.apply(args=(athlete_id, workout_ids, action)).get()
    try:
        async_result = garmin_push_task.apply_async(args=(athlete_id, workout_ids, action))
        return async_result.get(timeout=GARMIN_PUSH_WAIT_S, disable_sync_subtasks=False)
    except Exception as exc:  # noqa: BLE001 — timeout, broker down, worker down
        return {"ok": False, "code": "queue", "results": [],
                "detail": f"The Garmin queue did not answer in time ({type(exc).__name__}). "
                          "A sync may be running — try again in a minute."}


@shared_task(name="planning.morning_checkins")
def morning_checkins() -> dict:
    """Hourly. For athletes whose local time is 07:xx: sync wellness, then compute.

    Never applies anything — the athlete taps "Use this".
    """
    from .models import TrainingPlan

    queued = 0
    ids = TrainingPlan.objects.filter(status=TrainingPlan.Status.ACTIVE) \
        .values_list("athlete_id", flat=True)
    for athlete in Athlete.objects.filter(pk__in=list(ids)):
        if athlete.local_now.hour != MORNING_HOUR:
            continue
        if athlete.garmin_connected:
            from apps.ingest.tasks import sync_wellness_one

            sync_wellness_one.apply_async((athlete.pk,), link=compute_checkin.si(athlete.pk))
        else:
            compute_checkin.delay(athlete.pk)
        queued += 1
    return {"queued": queued}


MORNING_HOUR = 7


@shared_task(name="planning.compute_checkin")
def compute_checkin(athlete_id: int) -> dict:
    """Compute today's verdict (logged; GET /today/ always recomputes on read)."""
    from .checkin_services import compute

    athlete = Athlete.objects.filter(pk=athlete_id).first()
    if athlete is None:
        return {"skipped": "gone"}
    verdict, workout = compute(athlete)
    return {"athlete": athlete_id, "date": str(athlete.local_today),
            "verdict": verdict.verdict, "workout_id": workout.pk if workout else None,
            "signals_missing": verdict.signals_missing}
