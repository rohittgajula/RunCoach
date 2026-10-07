"""Keep the athlete's watch in step when a workout that was sent to Garmin changes.

A workout the athlete already sent (garmin_workout_id set) that is then moved,
re-flowed, eased by the check-in, skipped or deleted must not leave a stale copy on
the watch. These helpers queue the existing garmin-queue jobs AFTER the surrounding
transaction commits (a rolled-back save never touches Garmin), and only for workouts
that are on the watch: nothing is ever uploaded that the athlete did not send first.

They never raise into the caller. The job itself honours the rate-limit breaker; if it
cannot run, the workout keeps its old Garmin id and a different payload hash, so the
UI shows garmin_status "changed" and offers "Update on watch".
"""

from __future__ import annotations

import logging

from django.db import transaction

from .models import PlannedWorkout

logger = logging.getLogger(__name__)


def _queue(task, *args) -> None:
    def send():
        try:
            task.delay(*args)
        except Exception as exc:  # noqa: BLE001 — broker down must not break a save
            logger.warning("could not queue %s%r: %s", task.name, args, exc)

    transaction.on_commit(send)


def _on_watch(athlete, workout_ids):
    return PlannedWorkout.objects.filter(athlete=athlete, pk__in=list(workout_ids),
                                         garmin_workout_id__isnull=False)


def resync_on_garmin(athlete, workout_ids) -> int:
    """Re-send workouts whose watch copy is now out of date (date, steps or title).

    The job deletes the old Garmin workout and uploads + schedules the new one.
    Returns how many were queued.
    """
    from .presenters import garmin_status
    from .tasks import garmin_push_task

    ids = [w.pk for w in _on_watch(athlete, workout_ids)
           if w.status == PlannedWorkout.Status.PLANNED and garmin_status(w) == "changed"]
    if ids:
        _queue(garmin_push_task, athlete.pk, ids, "send")
    return len(ids)


def remove_from_garmin(athlete, workout_ids) -> int:
    """Take workouts that still exist here (e.g. skipped) off the watch."""
    from .tasks import garmin_push_task

    ids = list(_on_watch(athlete, workout_ids).values_list("pk", flat=True))
    if ids:
        _queue(garmin_push_task, athlete.pk, ids, "delete")
    return len(ids)


def forget_on_garmin(athlete, workouts) -> int:
    """Queue removal of the Garmin copies of workouts ABOUT TO BE DELETED here.

    The ids are captured now, before the rows go; the job runs after commit.
    """
    from .tasks import garmin_forget_task

    refs = [[w.garmin_workout_id, w.garmin_schedule_id]
            for w in workouts if w.garmin_workout_id]
    if refs:
        _queue(garmin_forget_task, athlete.pk, refs)
    return len(refs)
