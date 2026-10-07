"""R10 §C10/§C13 scheduled work (metrics queue)."""

from __future__ import annotations

import logging

from celery import shared_task

from apps.athletes.models import Athlete

logger = logging.getLogger(__name__)


@shared_task(name="health.build_weekly_report")
def build_weekly_report(athlete_id: int) -> dict:
    from .reports import get_or_build, last_complete_week

    athlete = Athlete.objects.filter(pk=athlete_id).first()
    if athlete is None:
        return {"skipped": "gone"}
    report = get_or_build(athlete, last_complete_week(athlete))
    return {"athlete": athlete_id, "week_start": str(report.week_start), "id": report.pk}


@shared_task(name="health.weekly_reports")
def weekly_reports() -> dict:
    """Hourly. Builds last week's report for athletes whose local time is Monday 06:xx
    (idempotent: a report already built is left alone)."""
    from .reports import REPORT_HOUR

    queued = 0
    for athlete in Athlete.objects.all():
        now = athlete.local_now
        if now.weekday() != 0 or now.hour != REPORT_HOUR:
            continue
        build_weekly_report.delay(athlete.pk)
        queued += 1
    return {"queued": queued}


@shared_task(name="health.award_one")
def award_one(athlete_id: int) -> dict:
    from .achievements import award

    athlete = Athlete.objects.filter(pk=athlete_id).first()
    if athlete is None:
        return {"skipped": "gone"}
    earned = sum(1 for b in award(athlete) if b["earned_on"] is not None)
    return {"athlete": athlete_id, "earned": earned}


@shared_task(name="health.award_all")
def award_all() -> dict:
    ids = list(Athlete.objects.values_list("pk", flat=True))
    for athlete_id in ids:
        award_one.delay(athlete_id)
    return {"queued": len(ids)}
