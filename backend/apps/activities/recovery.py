"""R17 §1: the post-run recovery routine (analysis/recovery_routine.py decides)."""

from __future__ import annotations

import datetime as dt
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from analysis import recovery_routine as maths

from .models import Activity, RecoveryLog, RecoveryPush

logger = logging.getLogger(__name__)

SHOW_FOR = dt.timedelta(hours=6)
PAIN_DAYS = 3


def is_run(activity: Activity) -> bool:
    return "run" in (activity.sport or "").lower()


def show_until(activity: Activity) -> dt.datetime:
    seconds = activity.total_elapsed_s or activity.total_timer_s or 0
    return activity.started_at + dt.timedelta(seconds=seconds) + SHOW_FOR


def _inputs(activity: Activity) -> maths.RoutineInputs:
    from apps.health.models import PainReport
    from apps.planning.models import PlannedWorkout

    metrics = getattr(activity, "metrics", None)
    zones = (metrics.time_in_zone or {}) if metrics else {}
    total = sum(v or 0 for v in zones.values())
    hard = ((zones.get("Z4", 0) or 0) + (zones.get("Z5", 0) or 0)) / total if total else None
    kind = (PlannedWorkout.objects.filter(athlete=activity.athlete, completed_activity=activity)
            .values_list("kind", flat=True).first())
    day = activity.local_date
    pains = [(p.location, p.side, p.severity) for p in PainReport.objects.filter(
        athlete=activity.athlete, date__gte=day - dt.timedelta(days=PAIN_DAYS), date__lte=day)]
    pains += [(p.location, p.side, p.severity) for p in PainReport.objects.filter(
        athlete=activity.athlete, activity=activity).exclude(
        date__gte=day - dt.timedelta(days=PAIN_DAYS), date__lte=day)]
    try:
        from apps.health.injury import injury_payload

        risk = injury_payload(activity.athlete)["risk"]
    except Exception:  # noqa: BLE001 — the routine must not depend on injury data
        risk = "low"
    return maths.RoutineInputs(
        duration_s=activity.total_timer_s or activity.total_elapsed_s or 0,
        distance_m=activity.total_distance_m or 0, kind=kind,
        elevation_gain_m=activity.total_ascent_m,
        hard_share=hard,
        cadence_spm=(metrics.avg_run_cadence_spm if metrics else None)
        or activity.avg_cadence_spm,
        ground_contact_ms=metrics.avg_ground_contact_ms if metrics else None,
        pains=pains, injury_risk=risk)


def _run_flags(athlete) -> list[tuple[dt.date, bool, int]]:
    """[(date, done, activity id)] for every run, oldest first."""
    runs = list(Activity.objects.filter(athlete=athlete, sport__icontains="run")
                .order_by("started_at", "id").values_list("pk", "local_date"))
    done = set(RecoveryLog.objects.filter(athlete=athlete).values_list("activity_id",
                                                                         flat=True))
    return [(day, pk in done, pk) for pk, day in runs]


def streak(athlete) -> dict:
    current, best = maths.recovery_streak([d for _, d, _ in _run_flags(athlete)])
    return {"current": current, "best": best}


def payload(activity: Activity) -> dict:
    log = RecoveryLog.objects.filter(activity=activity).first()
    base = {"activity_id": activity.pk, "done": log is not None,
            "done_at": log.done_at if log else None, "streak": streak(activity.athlete),
            "show_until": show_until(activity)}
    if not is_run(activity):
        return {**base, "available": False, "reason_unavailable": "not_a_run", "minutes": 0,
                "total_s": 0, "reason": "", "focus": [], "steps": [], "avoided": [],
                "notes": []}
    r = maths.build(_inputs(activity))
    return {**base, "available": True, "reason_unavailable": None, "minutes": r.minutes,
            "total_s": r.total_s, "reason": r.reason, "focus": r.focus, "steps": r.steps,
            "avoided": r.avoided, "notes": r.notes}


def mark_done(activity: Activity, skipped: list[str]) -> dict:
    from apps.health.achievements import award
    from apps.health.models import Achievement

    athlete = activity.athlete
    before = set(Achievement.objects.filter(athlete=athlete, key__startswith="recovery_streak_")
                 .values_list("key", flat=True))
    try:
        with transaction.atomic():
            log, _ = RecoveryLog.objects.get_or_create(
                activity=activity, defaults={"athlete": athlete, "done_at": timezone.now(),
                                             "skipped": skipped[:20]})
    except IntegrityError:
        log = RecoveryLog.objects.get(activity=activity)
    award(athlete)
    new = list(Achievement.objects.filter(athlete=athlete, key__startswith="recovery_streak_")
               .exclude(key__in=before).values("key", "label"))
    return {"activity_id": activity.pk, "done": True, "done_at": log.done_at,
            "streak": streak(athlete), "new_badges": new}


def today(athlete) -> dict | None:
    now = timezone.now()
    for activity in (Activity.objects.filter(athlete=athlete, sport__icontains="run",
                                             started_at__gte=now - dt.timedelta(days=2))
                     .order_by("-started_at")):
        if show_until(activity) <= now:
            continue
        if RecoveryLog.objects.filter(activity=activity).exists():
            continue                      # done: the card goes away
        minutes = payload(activity)["minutes"]
        return {"activity_id": activity.pk, "minutes": minutes,
                "title": f"Recovery · {minutes} min", "show_until": show_until(activity),
                "done": False}
    return None


def maybe_push(activity: Activity) -> str:
    """"Recovery routine ready" — once per run, off by default, never in quiet hours
    and never for a run that ended more than 6 h ago (backfills)."""
    try:
        from apps.reminders.push import available, send_to_athlete
        from apps.reminders.service import settings_for

        from .run_summary import quiet_until

        if not is_run(activity) or not available():
            return "skipped"
        row = settings_for(activity.athlete)
        if not row.recovery_ready or show_until(activity) <= timezone.now():
            return "skipped"
        if quiet_until(row, activity.athlete.local_now) is not None:
            return "skipped"
        try:
            with transaction.atomic():
                RecoveryPush.objects.create(athlete=activity.athlete, activity=activity)
        except IntegrityError:
            return "skipped"
        minutes = payload(activity)["minutes"]
        ok, _ = send_to_athlete(activity.athlete, {
            "title": "Recovery routine ready",
            "body": f"{minutes} min for your legs after that run.",
            "url": f"/activities/{activity.pk}?recovery=1", "tag": "recovery"})
        return "sent" if ok else "failed"
    except Exception:  # noqa: BLE001 — a push must never fail derivation
        logger.exception("recovery push failed for %s", activity.pk)
        return "failed"
