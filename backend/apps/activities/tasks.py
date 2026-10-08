"""Deriving metrics, on a schedule.

Separate from ingestion on purpose: segmentation is pure CPU and needs no network, so
a Garmin rate limit must never stop it, and re-deriving history after an algorithm
change must not touch Garmin at all.
"""

from __future__ import annotations

import logging

from celery import shared_task

from analysis.segmentation import ALGORITHM_VERSION

from .models import Activity
from .services import derive

logger = logging.getLogger(__name__)


@shared_task(name="activities.derive_one")
def derive_one(activity_id: int) -> dict:
    activity = Activity.objects.filter(pk=activity_id).first()
    if activity is None:
        return {"skipped": "gone"}

    metrics = derive(activity)
    queue_after_run(activity)
    # R17 §1: "Recovery routine ready" (opt-in; recent runs only).
    from .recovery import maybe_push

    maybe_push(activity)
    return {"activity": activity_id, "segmented": metrics is not None}


AFTER_RUN_DAYS = 2


def queue_after_run(activity: Activity) -> bool:
    """R13: a recent activity (today or the 2 days before) goes on to auto-adjust, the
    coach review and strength completion. Re-derivations of history never do."""
    import datetime as dt

    from django.db import transaction

    if activity.local_date < activity.athlete.local_today - dt.timedelta(days=AFTER_RUN_DAYS):
        return False

    def send():
        try:
            from apps.planning.tasks import after_run_task

            after_run_task.delay(activity.pk)
        except Exception:  # noqa: BLE001 — no broker in a one-off script
            logger.debug("could not queue after-run work for %s", activity.pk)

    transaction.on_commit(send)
    return True


@shared_task(name="activities.derive_stale")
def derive_stale(limit: int = 200) -> dict:
    """Anything not yet seen by the current algorithm version.

    This is why segmentation_version is an integer rather than a boolean: bump the
    version, and history re-derives itself without anyone remembering to run a command.
    """
    stale = Activity.objects.exclude(segmentation_version=ALGORITHM_VERSION)[:limit]
    for activity in stale:
        derive_one.delay(activity.pk)
    return {"queued": len(stale)}
