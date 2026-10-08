"""R18 §B: per-athlete data version.

An opaque, increasing integer per athlete, bumped on every write to the athlete's data
(model signals, see apps.athletes.apps) and every successful mutating API request
(config.middleware.DataVersionMiddleware). Derived computations cache under it
(`cached`), so the next read after any change recomputes; the frontend invalidates all
athlete queries when a response carries a different `data_version`.

Lives in the shared cache (Redis): starting from the wall-clock milliseconds means a
flushed cache never hands out a version an old client already saw.
"""

from __future__ import annotations

import logging
import time

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

DEFAULT_TTL_S = 15 * 60
_KEY = "dv:{}"
_AT = "dvt:{}"


def _seed() -> int:
    return int(time.time() * 1000)


def current(athlete_id: int | None) -> int:
    if not athlete_id:
        return 0
    key = _KEY.format(athlete_id)
    try:
        value = cache.get(key)
        if value is None:
            cache.add(key, _seed(), None)
            value = cache.get(key)
        return int(value or 0)
    except Exception:  # noqa: BLE001 — a cache outage must not break a page
        logger.debug("data version unavailable for %s", athlete_id)
        return 0


def _incr(athlete_id: int) -> int:
    key = _KEY.format(athlete_id)
    try:
        try:
            value = cache.incr(key)
        except ValueError:
            current(athlete_id)
            value = cache.incr(key)
        cache.set(_AT.format(athlete_id), timezone.now().isoformat(), None)
        return int(value)
    except Exception:  # noqa: BLE001
        logger.debug("could not bump the data version for %s", athlete_id)
        return 0


def bump(athlete_id: int | None) -> int:
    """Bump now, and again when the surrounding transaction commits (a reader between
    the two could otherwise cache pre-commit data under the new version)."""
    if not athlete_id:
        return 0
    value = _incr(athlete_id)
    if transaction.get_connection().in_atomic_block:
        transaction.on_commit(lambda: _incr(athlete_id))
    return value


def changed_at(athlete_id: int):
    """When the athlete's data last changed (None: unknown)."""
    import datetime as dt

    try:
        raw = cache.get(_AT.format(athlete_id))
        return dt.datetime.fromisoformat(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


def is_stale(athlete_id: int, generated_at) -> bool:
    at = changed_at(athlete_id)
    return bool(at and generated_at and at > generated_at)


def cached(athlete, name: str, compute, *parts, ttl: int = DEFAULT_TTL_S):
    """compute() once per (athlete, data version, local date, name, parts)."""
    version = current(athlete.pk)
    if not version:
        return compute()
    key = "dvc:{}:{}:{}:{}:{}".format(athlete.pk, version, athlete.local_today.isoformat(),
                                      name, ":".join(str(p) for p in parts))
    try:
        hit = cache.get(key)
    except Exception:  # noqa: BLE001
        hit = None
    if hit is not None:
        return hit
    value = compute()
    try:
        cache.set(key, value, ttl)
    except Exception:  # noqa: BLE001 — unpicklable or cache down: just don't cache
        logger.debug("could not cache %s for %s", name, athlete.pk)
    return value


# --- signals --------------------------------------------------------------------------

# Logs, caches and outputs derived from the data — writing them is not a data change
# (and an AI summary saved must not mark itself stale).
SKIP = {"athletes.DataExport", "coaching.AIRequestLog", "coaching.AIAnalysis",
        "coaching.ChatThread", "coaching.ChatMessage", "health.MorningBriefing",
        "health.WeeklyReport", "health.MonthlyReport", "reminders.PushSubscription",
        "activities.RecoveryPush", "activities.GarminDeletionCheck", "planning.GarminUpload",
        "planning.CalendarFeed", "planning.CalendarFeedItem"}


def athlete_id_of(instance) -> int | None:
    label = instance._meta.label
    if label in SKIP:
        return None
    if label == "athletes.Athlete":
        return instance.pk
    athlete_id = getattr(instance, "athlete_id", None)
    if athlete_id:
        return athlete_id
    activity_id = getattr(instance, "activity_id", None)
    if activity_id and instance._meta.app_label == "activities":
        from apps.activities.models import Activity

        return Activity.objects.filter(pk=activity_id).values_list("athlete_id",
                                                                   flat=True).first()
    return None


def on_write(sender, instance, **kwargs):
    if kwargs.get("raw"):
        return
    try:
        athlete_id = athlete_id_of(instance)
    except Exception:  # noqa: BLE001
        return
    if athlete_id:
        bump(athlete_id)
