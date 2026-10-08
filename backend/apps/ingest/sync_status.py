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
RUN_AWARE_INTERVAL_S = 5 * 60          # R18: while today's planned run hasn't arrived
RUN_WINDOW_BEFORE_MIN = 15
RUN_WINDOW_AFTER_MIN = 3 * 60
STALE_AFTER_S = MIN_INTERVAL_S         # R18: was 60 min; auto-sync every 30 min
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
    from .sync_jobs import active_job_id

    return bool(cache.get(_running_key(athlete.pk)) or active_job_id(athlete.pk))


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


def _typical_minute(athlete) -> int | None:
    from analysis import wake as maths
    from apps.activities.models import Activity

    from apps.health.common import zone_of

    zone = zone_of(athlete)
    starts = [a.astimezone(zone) for a in Activity.objects.filter(
        athlete=athlete, sport__icontains="run").order_by("-started_at")
        .values_list("started_at", flat=True)[:maths.RECENT_RUNS]]
    return maths.typical_run_time([s.hour * 60 + s.minute for s in reversed(starts)])


def run_window(athlete, now: dt.datetime | None = None) -> dict:
    """R18 §A run-aware polling: from (run time − 15 min) to (+3 h) on a day with a planned
    run that hasn't arrived yet, auto-sync every 5 min instead of 30."""
    from apps.activities.models import Activity
    from apps.athletes.effective import usual_run_minute
    from apps.planning.models import PlannedWorkout, TrainingPlan
    from apps.reminders.models import Alarm

    now = now or _now()
    local = now.astimezone(athlete.local_now.tzinfo)
    today = local.date()
    out = {"active": False, "waiting_for_run": False, "workout_id": None, "title": None,
           "run_time": None, "run_time_source": None, "window_start": None,
           "window_end": None, "arrived": False}
    workout = (PlannedWorkout.objects.filter(
        athlete=athlete, date=today, plan__status=TrainingPlan.Status.ACTIVE,
        status__in=[PlannedWorkout.Status.PLANNED, PlannedWorkout.Status.COMPLETED])
        .exclude(kind__in=["REST", "STRENGTH"]).order_by("id").first())
    if workout is None:
        return out
    arrived = (workout.status == PlannedWorkout.Status.COMPLETED or Activity.objects.filter(
        athlete=athlete, local_date=today, sport__icontains="run").exists())
    minute, source = usual_run_minute(athlete), "usual"
    if minute is None:
        alarm = Alarm.objects.filter(athlete=athlete).values_list("run_time", flat=True).first()
        minute, source = (alarm.hour * 60 + alarm.minute, "alarm") if alarm else (None, None)
    if minute is None:
        minute, source = _typical_minute(athlete), "history"
    out.update(workout_id=workout.pk, title=workout.title, arrived=arrived)
    if minute is None:
        return out
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight + dt.timedelta(minutes=minute - RUN_WINDOW_BEFORE_MIN)
    end = midnight + dt.timedelta(minutes=minute + RUN_WINDOW_AFTER_MIN)
    active = not arrived and start <= local <= end
    out.update(active=active, waiting_for_run=active,
               run_time=f"{minute // 60:02d}:{minute % 60:02d}", run_time_source=source,
               window_start=start, window_end=end)
    return out


def interval_s(window: dict) -> int:
    return RUN_AWARE_INTERVAL_S if window.get("active") else MIN_INTERVAL_S


def status_json(athlete) -> dict:
    from apps.athletes.versioning import current

    from .sync_jobs import status_fields

    now = _now()
    window = run_window(athlete, now)
    interval = interval_s(window)
    local = now.astimezone(athlete.local_now.tzinfo)
    connected = bool(athlete.garmin_connected)
    running = is_running(athlete)
    breaker = _breaker_open()
    last_sync = athlete.garmin_last_sync
    attempt = last_attempt(athlete)
    can_sync = connected and not running and not breaker
    candidates = [now]
    if attempt:
        candidates.append(attempt + dt.timedelta(seconds=interval))
    if last_sync:
        candidates.append(last_sync + dt.timedelta(seconds=interval))
    if local.hour < AUTO_FROM_HOUR:
        candidates.append(local.replace(hour=AUTO_FROM_HOUR, minute=0, second=0, microsecond=0))
    earliest = max(candidates)
    due = can_sync and earliest <= now
    return {"connected": connected, "last_sync_at": last_sync, "last_attempt_at": attempt,
            "running": running, "breaker_open": breaker, "can_sync_now": can_sync,
            "auto_sync_due": due,
            "next_auto_sync_at": None if due or not can_sync else earliest,
            "min_interval_s": interval,
            **status_fields(athlete), "run_aware": window,
            "data_version": current(athlete.pk)}


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
    window = dt.timedelta(seconds=interval_s(run_window(athlete, now)))
    attempt, last_sync = last_attempt(athlete), athlete.garmin_last_sync
    if (attempt and now - attempt < window) or (last_sync and now - last_sync < window):
        return "recent"
    return None


def auto_mode(athlete) -> str:
    """full, or run_check (run-aware window and a full sync < 30 min ago)."""
    from .sync_jobs import last_full_at

    now = _now()
    if not run_window(athlete, now)["active"]:
        return "full"
    last = last_full_at(athlete.pk)
    if last and now - last < dt.timedelta(seconds=MIN_INTERVAL_S):
        return "run_check"
    return "full"
