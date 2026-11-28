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


@shared_task(name="activities.rezone_athlete")
def rezone_athlete(athlete_id: int) -> dict:
    """Recount time-in-zone on every activity after the athlete's zones changed
    (zones method, max or resting HR). Only time_in_zone is rewritten: segments and
    every other metric stay as they are, and no after-run work is triggered — so the
    zone history stays comparable without re-running the coach on old runs."""
    from analysis import zones as zone_maths
    from apps.athletes.models import Athlete

    from .models import ActivityMetrics
    from .services import load_samples

    athlete = Athlete.objects.filter(pk=athlete_id).first()
    zones = athlete.zones() if athlete else None
    if zones is None:
        return {"rezoned": 0}
    done = 0
    for metrics in ActivityMetrics.objects.filter(activity__athlete=athlete).select_related("activity"):
        samples = load_samples(metrics.activity)
        metrics.time_in_zone = zone_maths.time_in_zones(
            ((s.offset_s, s.heart_rate) for s in samples), zones)
        metrics.save(update_fields=["time_in_zone"])
        done += 1
    return {"rezoned": done}
