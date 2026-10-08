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
    from apps.health.illness import active as illness_active

    if illness_active(athlete) is not None:
        return {"skipped": "illness"}      # R17 §10: paused while unwell
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


# The local rows are gone by the time a forget runs, so its refs live only in the task.
# While the breaker is open it re-queues itself instead of dropping them.
FORGET_RETRY_S = 30 * 60
FORGET_MAX_ATTEMPTS = 6


@shared_task(name="planning.garmin_forget")
def garmin_forget_task(athlete_id: int, refs: list[list], attempt: int = 0) -> dict:
    """Delete Garmin copies of workouts removed by a plan change (garmin queue)."""
    from django.conf import settings

    from .garmin_push import forget_remote

    result = forget_remote(athlete_id, refs)
    if (result.get("detail") == "rate_limited" and attempt + 1 < FORGET_MAX_ATTEMPTS
            and not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)):
        left = [ref for ref in refs if ref[0] in set(result["failed"])]
        garmin_forget_task.apply_async((athlete_id, left, attempt + 1), countdown=FORGET_RETRY_S)
        result["requeued"] = len(left)
    return result


# How long a request waits for the garmin queue. A long sync can hold the queue (it
# runs at concurrency 1); the athlete then gets a 503 and tries again.
GARMIN_PUSH_WAIT_S = 90


def run_garmin_push(athlete_id: int, workout_ids: list[int], action: str,
                    wait_s: float = GARMIN_PUSH_WAIT_S) -> dict:
    """Run the push on the garmin queue and wait for its per-workout results.

    On a timeout the job stays queued and still runs; the caller gets code "queue"."""
    from django.conf import settings

    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return garmin_push_task.apply(args=(athlete_id, workout_ids, action)).get()
    try:
        async_result = garmin_push_task.apply_async(args=(athlete_id, workout_ids, action))
        return async_result.get(timeout=wait_s, disable_sync_subtasks=False)
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


# --- R13 ---------------------------------------------------------------------------------

@shared_task(name="planning.after_run")
def after_run_task(activity_id: int) -> dict:
    """After a new activity is segmented: a strength activity completes that day's
    strength session; a recent run auto-adjusts the next sessions (§1) and gets its
    coach review (§7)."""
    from apps.activities.models import Activity

    from .auto_adjust import evaluate
    from .strength_service import complete_from_activity

    activity = Activity.objects.filter(pk=activity_id).select_related("athlete").first()
    if activity is None:
        return {"skipped": "gone"}
    athlete = activity.athlete
    out: dict = {"activity": activity_id}
    session = complete_from_activity(activity)
    if session is not None:
        out["strength_completed"] = session.pk
    if "run" not in (activity.sport or "").lower():
        return out
    out["adjusted"] = len(evaluate(athlete, trigger="run", activity=activity))
    from apps.activities.reviews import build_review

    review = build_review(activity, push=True)
    out["review"] = review.pk if review else None
    return out


@shared_task(name="planning.after_checkin")
def after_checkin_task(activity_id: int) -> dict:
    """The post-run check-in brings the RPE: re-evaluate (easier only) and refresh the
    review's bullets."""
    from apps.activities.models import Activity

    from .auto_adjust import evaluate

    activity = Activity.objects.filter(pk=activity_id).select_related("athlete").first()
    if activity is None or "run" not in (activity.sport or "").lower():
        return {"skipped": "gone_or_not_a_run"}
    adjusted = len(evaluate(activity.athlete, trigger="checkin", activity=activity))
    from apps.activities.reviews import build_review

    build_review(activity, push=False)
    return {"activity": activity_id, "adjusted": adjusted}


@shared_task(name="planning.after_pain")
def after_pain_task(athlete_id: int) -> dict:
    from .auto_adjust import evaluate

    athlete = Athlete.objects.filter(pk=athlete_id).first()
    if athlete is None:
        return {"skipped": "gone"}
    return {"athlete": athlete_id, "adjusted": len(evaluate(athlete, trigger="pain"))}


@shared_task(name="planning.garmin_strength_push")
def garmin_strength_push_task(athlete_id: int, session_ids: list[int],
                              action: str = "send") -> dict:
    """R13 §4. Routed to the `garmin` queue (see CELERY_TASK_ROUTES)."""
    from .garmin_strength_push import run_job

    return run_job(athlete_id, session_ids, action)


@shared_task(name="planning.strength_topup")
def strength_topup() -> dict:
    """Nightly: keep 8 weeks of strength sessions placed for athletes who chose them."""
    from .strength_service import place_for

    done = 0
    from apps.health.illness import active as illness_active

    for athlete in Athlete.objects.filter(strength_per_week__gt=0):
        if illness_active(athlete) is not None:
            continue                         # R17 §10: nothing new while unwell
        try:
            place_for(athlete)
            done += 1
        except Exception:  # noqa: BLE001 — one athlete must not stop the rest
            import logging

            logging.getLogger(__name__).exception("strength top-up failed for %s", athlete.pk)
    return {"athletes": done}


# R14 §3: the daily weather check, the evening before (18:xx local), for the next 3 days.
WEATHER_CHECK_HOUR = 18


@shared_task(name="planning.weather_checks")
def weather_checks() -> dict:
    """Hourly. Athletes with an active plan whose local time is 18:xx."""
    from .models import TrainingPlan

    ids = TrainingPlan.objects.filter(status=TrainingPlan.Status.ACTIVE) \
        .values_list("athlete_id", flat=True)
    queued = 0
    for athlete in Athlete.objects.filter(pk__in=list(ids)):
        if athlete.local_now.hour != WEATHER_CHECK_HOUR:
            continue
        weather_check_task.delay(athlete.pk)
        queued += 1
    return {"queued": queued}


@shared_task(name="planning.weather_check")
def weather_check_task(athlete_id: int) -> dict:
    from .weather_swap import check

    athlete = Athlete.objects.filter(pk=athlete_id).first()
    if athlete is None:
        return {"skipped": "gone"}
    return {"athlete": athlete_id, "created": len(check(athlete))}
