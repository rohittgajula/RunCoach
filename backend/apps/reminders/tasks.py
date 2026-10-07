"""R10 §C12: every 5 minutes, send each enabled reminder once per local day at its
time (up to 2 h late). R11 §C: the same beat evaluates the move / breathing / water
nudges (apps.reminders.nudges). A no-op while VAPID is not configured."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="reminders.send_due")
def send_due() -> dict:
    from .models import PushSubscription, ReminderSettings
    from .push import available, send_to_athlete
    from .service import REMINDERS, due, message

    if not available():
        return {"skipped": "not_configured"}
    with_subs = set(PushSubscription.objects.values_list("athlete_id", flat=True))
    sent = 0
    for row in ReminderSettings.objects.filter(athlete_id__in=with_subs).select_related("athlete"):
        athlete = row.athlete
        local_now = athlete.local_now
        changed = False
        for key in REMINDERS:
            if not due(row, key, local_now):
                continue
            row.last_sent = {**(row.last_sent or {}), key: local_now.date().isoformat()}
            changed = True
            try:
                body = message(athlete, key)
            except Exception:  # noqa: BLE001 — one athlete's weather/report must not stop the rest
                logger.exception("reminder %s failed for %s", key, athlete.pk)
                continue
            if body is None:
                continue
            ok, _ = send_to_athlete(athlete, body)
            sent += ok
        if changed:
            row.save(update_fields=["last_sent", "updated_at"])
        # R11 §C: move / breathing / water nudges (their own caps and dedupe).
        try:
            from .nudges import run_for

            sent += run_for(athlete, row, local_now,
                            lambda body, a=athlete: send_to_athlete(a, body)[0] > 0)
        except Exception:  # noqa: BLE001 — one athlete's nudges must not stop the rest
            logger.exception("nudges failed for %s", athlete.pk)
    # R15 §C: run summaries held through quiet hours.
    try:
        from apps.activities.run_summary import send_queued

        sent += send_queued()
    except Exception:  # noqa: BLE001
        logger.exception("queued run summaries failed")
    # R12 §B3: alarm push and bedtime reminder.
    try:
        from .alarms import run_alarms

        sent += run_alarms(lambda a, body: send_to_athlete(a, body)[0] > 0)
    except Exception:  # noqa: BLE001
        logger.exception("alarm pushes failed")
    return {"sent": sent}
