"""R16 §C: Garmin sync status and the auto-sync guard.

The app triggers a sync when it opens (or regains focus) and the last sync is over an
hour old. The server keeps that polite: at most one attempt per athlete every 30 min
(any sync start counts — manual, auto or the scheduled one), never two at once, never
while the rate-limit breaker is open. State lives in the shared cache: a short-lived
"running" lock and the time of the last attempt.
"""

from __future__ import annotations

import datetime as dt
from contextlib import contextmanager

from django.core.cache import cache
from django.utils import timezone

MIN_INTERVAL_S = 30 * 60
STALE_AFTER_S = 60 * 60
AUTO_FROM_HOUR = 5
RUNNING_TTL_S = 15 * 60          # a crashed worker can't hold the lock forever
ATTEMPT_TTL_S = 2 * 24 * 3600


class AlreadyRunning(Exception):
    pass


def _running_key(athlete_id: int) -> str:
    return f"garmin:sync_running:{athlete_id}"


def _attempt_key(athlete_id: int) -> str:
    return f"garmin:sync_attempt:{athlete_id}"


def _now():
    """Seam for tests."""
    return timezone.now()


def is_running(athlete) -> bool:
    return bool(cache.get(_running_key(athlete.pk)))


def last_attempt(athlete) -> dt.datetime | None:
    raw = cache.get(_attempt_key(athlete.pk))
    try:
        return dt.datetime.fromisoformat(raw) if raw else None
    except (TypeError, ValueError):
        return None


@contextmanager
def sync_lock(athlete):
    """Hold the per-athlete "running" lock for one sync; records the attempt."""
    key = _running_key(athlete.pk)
    if not cache.add(key, _now().isoformat(), RUNNING_TTL_S):
        raise AlreadyRunning("A sync is already running.")
    cache.set(_attempt_key(athlete.pk), _now().isoformat(), ATTEMPT_TTL_S)
    try:
        yield
    finally:
        cache.delete(key)


def _breaker_open() -> bool:
    from .tasks import garmin_blocked

    return garmin_blocked()


def status_json(athlete) -> dict:
    now = _now()
    local = now.astimezone(athlete.local_now.tzinfo)
    connected = bool(athlete.garmin_connected)
    running = is_running(athlete)
    breaker = _breaker_open()
    last_sync = athlete.garmin_last_sync
    attempt = last_attempt(athlete)
    can_sync = connected and not running and not breaker
    candidates = [now]
    if attempt:
        candidates.append(attempt + dt.timedelta(seconds=MIN_INTERVAL_S))
    if last_sync:
        candidates.append(last_sync + dt.timedelta(seconds=STALE_AFTER_S))
    if local.hour < AUTO_FROM_HOUR:
        candidates.append(local.replace(hour=AUTO_FROM_HOUR, minute=0, second=0, microsecond=0))
    earliest = max(candidates)
    due = can_sync and earliest <= now
    return {"connected": connected, "last_sync_at": last_sync, "last_attempt_at": attempt,
            "running": running, "breaker_open": breaker, "can_sync_now": can_sync,
            "auto_sync_due": due,
            "next_auto_sync_at": None if due or not can_sync else earliest,
            "min_interval_s": MIN_INTERVAL_S}


def auto_skip_reason(athlete) -> str | None:
    """Why an auto POST must not call Garmin now (None = go)."""
    now = _now()
    if not athlete.garmin_connected:
        return "not_connected"
    if is_running(athlete):
        return "running"
    if _breaker_open():
        return "breaker_open"
    if now.astimezone(athlete.local_now.tzinfo).hour < AUTO_FROM_HOUR:
        return "too_early"
    window = dt.timedelta(seconds=MIN_INTERVAL_S)
    attempt, last_sync = last_attempt(athlete), athlete.garmin_last_sync
    if (attempt and now - attempt < window) or (last_sync and now - last_sync < window):
        return "recent"
    return None
