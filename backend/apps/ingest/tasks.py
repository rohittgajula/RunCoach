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

    try:
        result = sync_athlete(athlete).as_dict()
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
