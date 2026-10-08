"""R17: deleting an activity (the athlete's choice), tombstones, Garmin-side deletions.

Nothing here runs on its own: an activity Garmin no longer lists becomes a data-review
item; only the athlete's "remove" (or DELETE) deletes it.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.db import transaction
from django.utils import timezone

from .models import Activity, ActivityTombstone, GarminDeletionCheck

logger = logging.getLogger(__name__)


def activity_cache_keys(pk: int, version) -> list[str]:
    keys = [f"progress:fastest1k:{pk}:{version}"]
    keys += [f"route:v1:{pk}:{version}:{hide}" for hide in (0, 1)]
    keys += [f"route-overlay:v1:{pk}:{hide}" for hide in (0, 1)]
    for use in ("cleaned", "raw"):
        keys.append(f"progress:fastest1k:{pk}:{version}:{use}")
        keys += [f"route:v1:{pk}:{version}:{hide}:{use}" for hide in (0, 1)]
        keys += [f"route-overlay:v1:{pk}:{hide}:{use}" for hide in (0, 1)]
    return keys


def is_tombstoned(athlete, *, garmin_activity_id=None, sha256: str = "") -> bool:
    qs = ActivityTombstone.objects.filter(athlete=athlete)
    if garmin_activity_id is not None and qs.filter(
            garmin_activity_id=garmin_activity_id).exists():
        return True
    return bool(sha256) and qs.filter(sha256=sha256).exists()


def tombstoned_garmin_ids(athlete) -> set[int]:
    return set(ActivityTombstone.objects.filter(athlete=athlete,
                                                garmin_activity_id__isnull=False)
               .values_list("garmin_activity_id", flat=True))


def delete_activity(activity: Activity, reason: str = ActivityTombstone.Reason.USER) -> dict:
    from apps.health.models import Achievement
    from apps.journal.models import JournalEntry
    from apps.planning.models import PlannedWorkout, StrengthSession

    athlete = activity.athlete
    pk, version, day = activity.pk, activity.segmentation_version, activity.local_date
    raw = activity.raw_file
    file_name = raw.file.name if raw is not None and raw.file else ""
    with transaction.atomic():
        tomb = ActivityTombstone.objects.create(
            athlete=athlete, garmin_activity_id=activity.garmin_activity_id,
            sha256=raw.sha256 if raw is not None else "", local_date=day,
            sport=activity.sport, distance_m=activity.total_distance_m or 0, reason=reason)
        reopened = []
        for w in PlannedWorkout.objects.filter(athlete=athlete, completed_activity=activity):
            w.completed_activity = None
            if w.status == PlannedWorkout.Status.COMPLETED:
                w.status = PlannedWorkout.Status.PLANNED
            w.save(update_fields=["completed_activity", "status"])
            reopened.append(w.pk)
        StrengthSession.objects.filter(athlete=athlete, completed_activity=activity,
                                       auto_completed=True).update(
            status=StrengthSession.Status.PLANNED, auto_completed=False,
            completed_activity=None)
        # The post-run check-in belongs to this run alone.
        JournalEntry.objects.filter(athlete=athlete, activity=activity,
                                    extracted__has_key="checkin").delete()
        prs = list(Achievement.objects.filter(
            athlete=athlete, kind=Achievement.Kind.PR, key__startswith="pr:computed:",
            earned_on=day).values_list("key", flat=True))
        Achievement.objects.filter(athlete=athlete, key__in=prs).delete()
        activity.delete()
        if raw is not None and not Activity.objects.filter(raw_file=raw).exists():
            raw.delete()

    def cleanup():
        from django.core.cache import cache
        from django.core.files.storage import default_storage

        try:
            cache.delete_many(activity_cache_keys(pk, version))
        except Exception:  # noqa: BLE001
            logger.debug("cache cleanup failed for deleted activity %s", pk)
        if file_name:
            try:
                default_storage.delete(file_name)
            except Exception:  # noqa: BLE001
                logger.warning("could not remove the FIT file of deleted activity %s", pk)
        try:
            from apps.health.achievements import award

            award(athlete)            # computed PRs re-evaluated without this run
        except Exception:  # noqa: BLE001
            logger.exception("re-awarding after deleting activity %s failed", pk)

    transaction.on_commit(cleanup)
    return {"deleted": pk, "tombstone_id": tomb.pk, "workouts_reopened": reopened,
            "records_removed": prs}


def tombstone_json(t: ActivityTombstone) -> dict:
    return {"id": t.pk, "garmin_activity_id": t.garmin_activity_id, "date": t.local_date,
            "sport": t.sport, "distance_m": round(t.distance_m or 0, 1),
            "deleted_at": t.deleted_at, "reason": t.reason,
            "can_reimport": t.garmin_activity_id is not None}


# --- Garmin-side deletions ---------------------------------------------------------

def check_listing(athlete, entries: list, page_full: bool, now: dt.datetime | None = None
                  ) -> list[int]:
    """Compare one Garmin listing with what we hold. Creates review items (never
    deletes). Returns the activity ids newly flagged."""
    from analysis import garmin_deletions as maths
    from apps.ingest.garmin import _entry_date

    now = now or timezone.now()
    today = athlete.local_today
    listed_ids = {e.get("activityId") for e in entries if e.get("activityId") is not None}
    dates = [d for d in (_entry_date(e) for e in entries) if d is not None]
    start = maths.covered_from(dates, page_full, today)
    ours = list(Activity.objects.filter(athlete=athlete, garmin_activity_id__isnull=False,
                                        local_date__gte=start)
                .values_list("pk", "garmin_activity_id", "local_date", "started_at"))
    flagged = []
    for pk in maths.missing(ours, listed_ids, start, now):
        _, created = GarminDeletionCheck.objects.get_or_create(
            activity_id=pk, defaults={"athlete": athlete})
        if created:
            flagged.append(pk)
    # Listed again (a glitch, or restored in Garmin): no longer a question.
    GarminDeletionCheck.objects.filter(athlete=athlete, decision="",
                                       activity__garmin_activity_id__in=listed_ids).delete()
    return flagged


def reimport(athlete, tomb: ActivityTombstone) -> dict:
    """Remove the tombstone; fetch the activity from Garmin again when it has an id."""
    garmin_id = tomb.garmin_activity_id
    if garmin_id is None:
        tomb.delete()
        return {"reimported": False, "activity_id": None,
                "detail": "Upload the file again to bring it back."}
    from apps.ingest.tasks import garmin_blocked

    if garmin_blocked():
        return {"error": "Garmin is rate-limiting this server — try again later."}
    if not athlete.garmin_connected:
        return {"error": "Connect Garmin first."}
    tomb.delete()
    from apps.ingest.tasks import run_reimport

    result = run_reimport(athlete.pk, garmin_id)
    if result.get("code") in ("rate_limited", "auth", "queue"):
        # Garmin could not be asked: keep the deletion as it was.
        ActivityTombstone.objects.create(
            athlete=athlete, garmin_activity_id=garmin_id, sha256=tomb.sha256,
            local_date=tomb.local_date, sport=tomb.sport, distance_m=tomb.distance_m,
            reason=tomb.reason)
        return {"error": result.get("detail") or "Garmin is unavailable."}
    return {"reimported": bool(result.get("activity_id")),
            "activity_id": result.get("activity_id"),
            "detail": result.get("detail") or ""}
