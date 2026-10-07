"""R12 §B3: the alarm push (a notification at "My alarm" time — not a real alarm) and
the bedtime reminder (tomorrow's planned bedtime − lead). Each at most once per local
day, up to 15 minutes late. Quiet hours do not apply: the athlete picked these times."""

from __future__ import annotations

import datetime as dt
import logging

logger = logging.getLogger(__name__)

LATE = dt.timedelta(minutes=15)

MESSAGES = {
    "alarm": {"title": "Alarm", "body": "Time to get up. (A RunCoach notification, not a "
              "phone alarm.)", "url": "/health/sleep", "tag": "alarm"},
    "bedtime": {"title": "Wind down", "body": "Bedtime is coming up — start winding down "
                "for tomorrow.", "url": "/health/sleep", "tag": "bedtime"},
}


def _at(local_now: dt.datetime, minute: int) -> dt.datetime:
    return local_now.replace(hour=minute // 60, minute=minute % 60, second=0, microsecond=0)


def _due(local_now: dt.datetime, minute: int | None) -> bool:
    if minute is None:
        return False
    at = _at(local_now, minute)
    return at <= local_now < at + LATE


def bedtime_minute(athlete, local_now: dt.datetime) -> int | None:
    """Today's bedtime-reminder minute: from tomorrow's plan when it falls in the
    evening, else from today's plan when it falls after midnight (before noon)."""
    from analysis.wake import minutes
    from apps.health.wake_views import wake_plan

    today = local_now.date()
    evening = minutes(wake_plan(athlete, today + dt.timedelta(days=1))["bedtime_reminder_at"])
    if evening is not None and evening >= 12 * 60:
        return evening
    early = minutes(wake_plan(athlete, today)["bedtime_reminder_at"])
    return early if early is not None and early < 12 * 60 else None


def due_messages(athlete, row, local_now: dt.datetime) -> list[str]:
    from analysis.wake import minutes

    today = local_now.date().isoformat()
    keys = []
    sent = row.last_sent or {}
    if row.enabled and row.push and row.time and local_now.weekday() in (row.days or []) \
            and sent.get("alarm") != today and _due(local_now, minutes(row.time)):
        keys.append("alarm")
    if row.bedtime_reminder and sent.get("bedtime") != today \
            and _due(local_now, bedtime_minute(athlete, local_now)):
        keys.append("bedtime")
    return keys


def run_alarms(send) -> int:
    """For every athlete with an alarm push or bedtime reminder and a device."""
    from django.db.models import Q

    from .models import Alarm, PushSubscription

    with_subs = set(PushSubscription.objects.values_list("athlete_id", flat=True))
    sent = 0
    rows = (Alarm.objects.filter(athlete_id__in=with_subs)
            .filter(Q(enabled=True, push=True) | Q(bedtime_reminder=True))
            .select_related("athlete"))
    for row in rows:
        local_now = row.athlete.local_now
        try:
            keys = due_messages(row.athlete, row, local_now)
        except Exception:  # noqa: BLE001 — one athlete's plan must not stop the rest
            logger.exception("alarm check failed for %s", row.athlete_id)
            continue
        if not keys:
            continue
        row.last_sent = {**(row.last_sent or {}), **{k: local_now.date().isoformat() for k in keys}}
        row.save(update_fields=["last_sent", "updated_at"])
        for key in keys:
            if send(row.athlete, dict(MESSAGES[key])):
                sent += 1
    return sent

