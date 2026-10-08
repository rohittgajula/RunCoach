"""Garmin sync, on a schedule.

Garmin rate-limits by **IP**, and every athlete's sync leaves from this one server.
Three consequences shape everything here, all from docs/HOSTING.md:

* the Garmin queue runs at concurrency 1, so syncs never overlap;
* athletes are staggered rather than all fired at 05:30;
* a 429 stops the whole queue rather than moving to the next athlete, because the
  limit is on the address and continuing lengthens the block for everyone.
"""

from __future__ import annotations

import logging
import random

from celery import shared_task
from django.core.cache import cache

from apps.athletes.models import Athlete

from .garmin import GarminAuthError, GarminRateLimited, sync_athlete

logger = logging.getLogger(__name__)

# Set when Garmin rate-limits us. Shared through Redis so every worker sees it.
BREAKER_KEY = "garmin:blocked_until"
BREAKER_SECONDS = 45 * 60


def garmin_blocked() -> bool:
    return bool(cache.get(BREAKER_KEY))


def trip_breaker(reason: str) -> None:
    logger.warning("garmin circuit breaker tripped: %s", reason)
    cache.set(BREAKER_KEY, reason, BREAKER_SECONDS)


@shared_task(name="ingest.sync_one", bind=True, max_retries=2)
def sync_one(self, athlete_id: int) -> dict:
    """Sync one athlete. Safe to re-run — ingestion is idempotent on two layers."""
    if garmin_blocked():
        logger.info("skipping sync for %s: breaker open", athlete_id)
        return {"skipped": "rate_limited"}

    athlete = Athlete.objects.filter(pk=athlete_id, garmin_connected=True).first()
    if athlete is None:
        return {"skipped": "not_connected"}

    from .sync_status import AlreadyRunning, sync_lock

    try:
        with sync_lock(athlete):
            result = sync_athlete(athlete).as_dict()
    except AlreadyRunning:
        return {"skipped": "running"}       # R16: the athlete's own sync is on it
    except GarminRateLimited as exc:
        trip_breaker(str(exc))
        return {"skipped": "rate_limited"}
    except GarminAuthError as exc:
        # A dead token is not retryable — retrying just burns requests against an
        # address Garmin is already watching. The athlete must reconnect.
        logger.warning("garmin auth failed for %s: %s", athlete_id, exc)
        athlete.garmin_connected = False
        athlete.save(update_fields=["garmin_connected"])
        return {"error": "auth"}

    if any("rate-limited" in e for e in result.get("errors", [])):
        trip_breaker("rate limited mid-sync")
    else:
        queue_slow(athlete)
        queue_intraday(athlete)
    # New runs may change last week's picture: adapt the active plan (idempotent per
    # ISO week, so this is a no-op after the first run of the week).
    try:
        from apps.planning.tasks import adapt_week_task

        adapt_week_task.delay(athlete.pk)
    except Exception:  # noqa: BLE001 — no broker in a one-off script
        logger.debug("could not queue plan adaptation for %s", athlete.pk)
    return result


@shared_task(name="ingest.sync_all")
def sync_all() -> dict:
    """Queue every connected athlete, spread across the hour."""
    if garmin_blocked():
        return {"skipped": "rate_limited"}

    ids = list(
        Athlete.objects.filter(garmin_connected=True).values_list("pk", flat=True)
    )
    for index, athlete_id in enumerate(ids):
        # Deterministic spacing plus jitter: ten athletes at 05:30 is ten bursts from
        # one IP inside a minute, which is what the limiter is looking for.
        delay = index * 180 + random.randint(0, 60)
        sync_one.apply_async((athlete_id,), countdown=delay)

    return {"queued": len(ids)}


@shared_task(name="ingest.sync_wellness_one")
def sync_wellness_one(athlete_id: int) -> dict:
    """R7 morning check-in: wellness only (no activity listing). Breaker applies."""
    from .garmin import _client
    from .garmin_wellness import sync_wellness

    if garmin_blocked():
        return {"skipped": "rate_limited"}
    athlete = Athlete.objects.filter(pk=athlete_id, garmin_connected=True).first()
    if athlete is None:
        return {"skipped": "not_connected"}
    try:
        result = sync_wellness(athlete, _client(athlete), days=2)
    except GarminRateLimited as exc:
        trip_breaker(str(exc))
        return {"skipped": "rate_limited"}
    except GarminAuthError as exc:
        logger.warning("garmin auth failed for %s: %s", athlete_id, exc)
        return {"error": "auth"}
    if result.get("rate_limited"):
        trip_breaker("rate limited during morning wellness sync")
    return {"athlete": athlete_id, **result}


# --- R10 §B: slow-changing Garmin data (once a day per athlete) ------------------------

def queue_slow(athlete) -> bool:
    """Queue today's slow fetch unless it already ran. Never raises."""
    from .models import GarminProfile

    done = GarminProfile.objects.filter(athlete=athlete,
                                        slow_synced_on=athlete.local_today).exists()
    if done or garmin_blocked():
        return False
    try:
        sync_slow_one.apply_async((athlete.pk,), countdown=30)
        return True
    except Exception:  # noqa: BLE001 — no broker in a one-off script
        logger.debug("could not queue the slow garmin fetch for %s", athlete.pk)
        return False


def _slow_client(athlete_id: int):
    from .garmin import _client

    athlete = Athlete.objects.filter(pk=athlete_id, garmin_connected=True).first()
    if athlete is None:
        return None, None
    return athlete, _client(athlete)


@shared_task(name="ingest.sync_slow_one")
def sync_slow_one(athlete_id: int, force: bool = False) -> dict:
    """Endurance score, fitness age, LT, PRs, body composition and gear — at most once
    a day (garmin queue, breaker applies)."""
    from .garmin_slow import sync_slow
    from .garmin_wellness import RateLimited

    if garmin_blocked():
        return {"skipped": "rate_limited"}
    try:
        athlete, client = _slow_client(athlete_id)
        if athlete is None:
            return {"skipped": "not_connected"}
        result = sync_slow(athlete, client, force=force)
    except (GarminRateLimited, RateLimited) as exc:
        trip_breaker(str(exc))
        return {"skipped": "rate_limited"}
    except GarminAuthError as exc:
        logger.warning("garmin auth failed for %s: %s", athlete_id, exc)
        return {"error": "auth"}
    if result.get("rate_limited"):
        trip_breaker("rate limited during the slow garmin fetch")
    return {"athlete": athlete_id, **result}


@shared_task(name="ingest.backfill_r10")
def backfill_r10(athlete_id: int, days: int = 180) -> dict:
    """R10 history backfill (manage.py garmin_backfill_r10). Breaker applies."""
    from .garmin_slow import backfill
    from .garmin_wellness import RateLimited

    if garmin_blocked():
        return {"skipped": "rate_limited"}
    try:
        athlete, client = _slow_client(athlete_id)
        if athlete is None:
            return {"skipped": "not_connected"}
        result = backfill(athlete, client, days=days)
    except (GarminRateLimited, RateLimited) as exc:
        trip_breaker(str(exc))
        return {"skipped": "rate_limited"}
    except GarminAuthError as exc:
        logger.warning("garmin auth failed for %s: %s", athlete_id, exc)
        return {"error": "auth"}
    if result.get("rate_limited"):
        trip_breaker("rate limited during the R10 backfill")
    return {"athlete": athlete_id, **result}


# --- R11 §A: intraday series (today + yesterday after each sync) ------------------------

INTRADAY_DELAY_S = 90
BACKFILL_CHUNK_DAYS = 7


def queue_intraday(athlete, countdown: int = INTRADAY_DELAY_S) -> bool:
    """Queue today's + yesterday's intraday fetch after a successful sync. Never raises."""
    if garmin_blocked():
        return False
    try:
        sync_intraday_one.apply_async((athlete.pk,), countdown=countdown)
        return True
    except Exception:  # noqa: BLE001 — no broker in a one-off script
        logger.debug("could not queue the intraday fetch for %s", athlete.pk)
        return False


def _run_intraday(athlete_id: int, label: str, fn) -> dict:
    from .garmin_wellness import RateLimited

    if garmin_blocked():
        return {"skipped": "rate_limited"}
    try:
        athlete, client = _slow_client(athlete_id)
        if athlete is None:
            return {"skipped": "not_connected"}
        result = fn(athlete, client)
    except (GarminRateLimited, RateLimited) as exc:
        trip_breaker(str(exc))
        return {"skipped": "rate_limited"}
    except GarminAuthError as exc:
        logger.warning("garmin auth failed for %s: %s", athlete_id, exc)
        return {"error": "auth"}
    if result.get("rate_limited"):
        trip_breaker(f"rate limited during {label}")
    return {"athlete": athlete_id, **result}


@shared_task(name="ingest.sync_intraday_one")
def sync_intraday_one(athlete_id: int, today_only: bool = False, minimal: bool = False) -> dict:
    """Today + yesterday (or just today, with only steps + stress, for the nudge
    refresh). Garmin queue; breaker applies."""
    import datetime as dt

    from .garmin_intraday import sync_intraday

    def fetch(athlete, client):
        today = athlete.local_today
        days = [today] if today_only else [today, today - dt.timedelta(days=1)]
        return sync_intraday(athlete, client, days, minimal=minimal)

    return _run_intraday(athlete_id, "the intraday fetch", fetch)


@shared_task(name="ingest.backfill_intraday")
def backfill_intraday(athlete_id: int, days: list[str]) -> dict:
    """One chunk of the intraday backfill (manage.py garmin_backfill_intraday)."""
    import datetime as dt

    from .garmin_intraday import sync_intraday

    wanted = [dt.date.fromisoformat(d) for d in days]
    return _run_intraday(athlete_id, "the intraday backfill",
                         lambda athlete, client: sync_intraday(athlete, client, wanted))


@shared_task(name="ingest.intraday_refresh")
def intraday_refresh() -> dict:
    """R11 §C: for athletes with the move or breathing nudge on (and a device to push
    to), refresh today's steps + stress at most every INTRADAY_REFRESH_MIN minutes while
    inside their nudge hours. Staggered a minute apart; breaker applies."""
    import datetime as dt

    from django.conf import settings
    from django.db.models import Q
    from django.utils import timezone

    from apps.reminders.models import PushSubscription, ReminderSettings
    from apps.reminders.nudges import in_window

    from .models import IntradayDay

    every = getattr(settings, "INTRADAY_REFRESH_MIN", 60)
    if not every or garmin_blocked():
        return {"skipped": "off" if not every else "rate_limited"}
    with_subs = set(PushSubscription.objects.values_list("athlete_id", flat=True))
    rows = (ReminderSettings.objects.filter(athlete_id__in=with_subs,
                                            athlete__garmin_connected=True)
            .filter(Q(move=True) | Q(breathing=True)).select_related("athlete"))
    queued = 0
    stale_before = timezone.now() - dt.timedelta(minutes=every)
    for row in rows:
        athlete = row.athlete
        now = athlete.local_now.time()
        if in_window(now, row.quiet_start, row.quiet_end):
            continue
        active = ((row.move and in_window(now, row.move_start, row.move_end))
                  or (row.breathing and in_window(now, row.breathing_start, row.breathing_end)))
        if not active:
            continue
        fresh = IntradayDay.objects.filter(athlete=athlete, day=athlete.local_today,
                                           fetched_at__gte=stale_before).exists()
        if fresh:
            continue
        try:
            sync_intraday_one.apply_async((athlete.pk,), {"today_only": True, "minimal": True},
                                          countdown=queued * 60)
            queued += 1
        except Exception:  # noqa: BLE001
            logger.debug("could not queue the intraday refresh for %s", athlete.pk)
    return {"queued": queued}
