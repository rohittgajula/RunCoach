"""R18 §A: full refresh = full sync, as a job.

`start(athlete, kind)` queues one job per athlete on the garmin queue (deduped: a job
already queued/running, or one started in the last SPACING_S, is returned instead) and
`run(athlete_id, job_id)` walks the phases:

  activities → wellness (today + yesterday, re-fetched) → intraday (today + yesterday,
  forced; then the slow fetch if not done today) → derived → done

Progress lives in the shared cache (`status`), read by GET /sync/status/. The breaker is
checked before every phase, phases are GARMIN_SLOW_PAUSE_S apart, the first 429 stops the
job and trips the breaker. kind "run_check" (run-aware auto-sync between full syncs) only
lists activities, and continues through the other phases when a new run arrived.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
import uuid

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

PROGRESS = {"queued": 0, "activities": 10, "wellness": 35, "intraday": 60, "derived": 85,
            "done": 100}
SPACING_S = 60
ACTIVE_TTL_S = 20 * 60
JOB_TTL_S = 2 * 24 * 3600
PARTS = ("activities", "wellness", "intraday", "slow", "derived")


def _job_key(athlete_id: int) -> str:
    return f"garmin:sync_job:{athlete_id}"


def _active_key(athlete_id: int) -> str:
    return f"garmin:sync_job_active:{athlete_id}"


def _now():
    from .sync_status import _now as now

    return now()


def _pause() -> None:
    """Seam for tests: the spacing between phases."""
    seconds = getattr(settings, "GARMIN_SLOW_PAUSE_S", 1.5)
    if seconds:
        time.sleep(seconds)


def get_job(athlete_id: int) -> dict | None:
    return cache.get(_job_key(athlete_id))


def active_job_id(athlete_id: int) -> str | None:
    return cache.get(_active_key(athlete_id))


def _save(athlete_id: int, job: dict) -> None:
    cache.set(_job_key(athlete_id), job, JOB_TTL_S)


def last_full_at(athlete_id: int) -> dt.datetime | None:
    raw = cache.get(f"garmin:last_full:{athlete_id}")
    return dt.datetime.fromisoformat(raw) if raw else None


def _set_phase(athlete_id: int, job: dict, phase: str) -> None:
    job["phase"], job["progress"] = phase, PROGRESS.get(phase, job.get("progress", 0))
    _save(athlete_id, job)


def start(athlete, kind: str = "full") -> tuple[dict, bool]:
    """(job, deduped). Never two jobs for one athlete."""
    from .sync_status import _attempt_key, ATTEMPT_TTL_S

    athlete_id = athlete.pk
    active = active_job_id(athlete_id)
    last = get_job(athlete_id)
    if active and last and last.get("id") == active:
        return last, True
    if last and kind == "full" and last.get("started_at"):
        started = dt.datetime.fromisoformat(last["started_at"])
        if (_now() - started).total_seconds() < SPACING_S:
            return last, True
    job_id = uuid.uuid4().hex[:12]
    if not cache.add(_active_key(athlete_id), job_id, ACTIVE_TTL_S):
        return get_job(athlete_id) or {"id": active_job_id(athlete_id)}, True
    now = _now()
    job = {"id": job_id, "kind": kind, "phase": "queued", "progress": 0,
           "started_at": now.isoformat(), "finished_at": None, "error": None,
           "parts": {p: None for p in PARTS}}
    _save(athlete_id, job)
    # Counts as an attempt for the auto-sync guard right away (R16 rule).
    from . import sync_status

    sync_status.cache.set(_attempt_key(athlete_id), now.isoformat(), ATTEMPT_TTL_S)
    try:
        from .tasks import full_sync

        full_sync.apply_async((athlete_id, job_id), queue="garmin")
    except Exception as exc:  # noqa: BLE001 — no broker: fail visibly, free the slot
        logger.warning("could not queue the full sync for %s: %s", athlete_id, exc)
        _finish(athlete_id, job, error="The sync queue is unavailable. Try again in a minute.")
    return job, False


def _finish(athlete_id: int, job: dict, *, error: str | None = None) -> dict:
    job["phase"] = "failed" if error else "done"
    job["progress"] = job.get("progress", 0) if error else 100
    job["error"] = error
    job["finished_at"] = _now().isoformat()
    _save(athlete_id, job)
    if cache.get(_active_key(athlete_id)) == job["id"]:
        cache.delete(_active_key(athlete_id))
    from apps.athletes.versioning import bump

    bump(athlete_id)
    return job


class _Stop(Exception):
    def __init__(self, error: str, rate_limited: bool = False):
        super().__init__(error)
        self.error, self.rate_limited = error, rate_limited


def _check_breaker() -> None:
    from .tasks import garmin_blocked

    if garmin_blocked():
        raise _Stop("Garmin is rate-limiting this server — try again later.", True)


def run(athlete_id: int, job_id: str) -> dict:
    """The job body (garmin queue)."""
    from apps.athletes.models import Athlete

    from .garmin import GarminAuthError, GarminRateLimited, _client
    from .sync_status import AlreadyRunning, sync_lock
    from .tasks import trip_breaker

    job = get_job(athlete_id)
    if not job or job.get("id") != job_id:
        return {"skipped": "superseded"}
    athlete = Athlete.objects.filter(pk=athlete_id, garmin_connected=True).first()
    if athlete is None:
        return _finish(athlete_id, job, error="Garmin is not connected.")
    try:
        with sync_lock(athlete):
            _check_breaker()
            client = _client(athlete)
            _phases(athlete, client, job)
    except AlreadyRunning:
        return _finish(athlete_id, job, error="A sync is already running.")
    except _Stop as stop:
        if stop.rate_limited:
            trip_breaker(stop.error)
            phase = job.get("phase")
            part = {"activities": "activities", "wellness": "wellness",
                    "intraday": "intraday"}.get(phase)
            if part and (job["parts"].get(part) or {}).get("status") != "rate_limited":
                job["parts"][part] = {**(job["parts"].get(part) or {}), "status": "rate_limited"}
        return _finish(athlete_id, job, error=stop.error)
    except GarminRateLimited as exc:
        trip_breaker(str(exc))
        return _finish(athlete_id, job, error="Garmin is rate-limiting this server.")
    except GarminAuthError as exc:
        athlete.garmin_connected = False
        athlete.save(update_fields=["garmin_connected"])
        return _finish(athlete_id, job, error=f"Garmin rejected the saved session: {exc}")
    except Exception as exc:  # noqa: BLE001 — never a stuck job
        logger.exception("full sync failed for %s", athlete_id)
        return _finish(athlete_id, job, error=f"Sync failed ({type(exc).__name__}).")
    Athlete.objects.filter(pk=athlete_id).update(garmin_last_sync=_now(), garmin_connected=True)
    if job.get("kind") != "run_check" or (job["parts"].get("wellness") or {}).get(
            "status") == "ok":
        cache.set(f"garmin:last_full:{athlete_id}", _now().isoformat(), JOB_TTL_S)
    return _finish(athlete_id, job)


def _phases(athlete, client, job: dict) -> None:
    from .garmin import sync_athlete
    from .garmin_intraday import sync_intraday
    from .garmin_slow import sync_slow
    from .garmin_wellness import sync_wellness
    from .models import GarminProfile

    athlete_id = athlete.pk
    parts = job["parts"]

    # 1. activities (recent page; new runs downloaded, derived below)
    _set_phase(athlete_id, job, "activities")
    result = sync_athlete(athlete, client=client, wellness=False, queue_derive=False)
    rate_limited = any("rate-limited" in e for e in result.errors)
    parts["activities"] = {"status": "rate_limited" if rate_limited else
                           "error" if result.failed and not result.imported else "ok",
                           "imported": result.imported, "skipped": result.skipped,
                           "failed": result.failed, "activity_ids": result.activity_ids}
    _save(athlete_id, job)
    if rate_limited:
        raise _Stop("Garmin rate-limited the activity download.", True)
    new_ids = list(result.activity_ids)
    if job.get("kind") == "run_check" and not new_ids:
        for part in ("wellness", "intraday", "slow", "derived"):
            parts[part] = {"status": "skipped"}
        return

    # 2. wellness: today + yesterday, re-fetched and overwritten
    _pause()
    _check_breaker()
    _set_phase(athlete_id, job, "wellness")
    well = sync_wellness(athlete, client, days=2)
    parts["wellness"] = {"status": "rate_limited" if well.get("rate_limited") else "ok",
                         "days": 2, "written": well.get("days_written", 0)}
    _save(athlete_id, job)
    if well.get("rate_limited"):
        raise _Stop("Garmin rate-limited the wellness download.", True)

    # 3. intraday: today + yesterday, forced (root cause 1); then slow data if due
    _pause()
    _check_breaker()
    _set_phase(athlete_id, job, "intraday")
    today = athlete.local_today
    intra = sync_intraday(athlete, client, [today, today - dt.timedelta(days=1)])
    parts["intraday"] = {"status": "rate_limited" if intra.get("rate_limited") else "ok",
                         "days": intra.get("days", 0), "calls": intra.get("calls", 0)}
    _save(athlete_id, job)
    if intra.get("rate_limited"):
        raise _Stop("Garmin rate-limited the day data download.", True)
    done_today = GarminProfile.objects.filter(athlete=athlete, slow_synced_on=today).exists()
    if done_today:
        parts["slow"] = {"status": "not_due"}
    else:
        _pause()
        _check_breaker()
        slow = sync_slow(athlete, client)
        parts["slow"] = {"status": "rate_limited" if slow.get("rate_limited") else "ok"}
        _save(athlete_id, job)
        if slow.get("rate_limited"):
            raise _Stop("Garmin rate-limited the daily extras.", True)

    # 4. derived: new runs inline, then the post-run work; everything read-time
    #    recomputes on the data_version bump.
    _set_phase(athlete_id, job, "derived")
    parts["derived"] = _derive(athlete, new_ids)
    _save(athlete_id, job)


def _derive(athlete, activity_ids: list[int]) -> dict:
    from apps.activities.models import Activity
    from apps.activities.services import derive
    from apps.activities.tasks import queue_after_run

    from .garmin_wellness import refresh_intraday_totals

    derived = 0
    status = "ok"
    for activity in Activity.objects.filter(athlete=athlete, pk__in=activity_ids):
        try:
            derive(activity)
            derived += 1
            queue_after_run(activity)
            from apps.activities.recovery import maybe_push

            maybe_push(activity)
        except Exception:  # noqa: BLE001 — the 20-min beat re-derives anything stale
            logger.exception("deriving %s in the full sync failed", activity.pk)
            status = "error"
    achievements = 0
    try:
        from apps.health.achievements import award

        achievements = len(award(athlete) or [])
    except Exception:  # noqa: BLE001
        logger.exception("achievements after the full sync failed for %s", athlete.pk)
    today = athlete.local_today
    refresh_intraday_totals(athlete, [today, today - dt.timedelta(days=1)])
    try:
        from apps.planning.tasks import adapt_week_task

        adapt_week_task.delay(athlete.pk)
    except Exception:  # noqa: BLE001
        logger.debug("could not queue plan adaptation for %s", athlete.pk)
    return {"status": status, "derived": derived, "achievements": achievements}


def status_fields(athlete) -> dict:
    job = get_job(athlete.pk)
    if not job:
        return {"job_id": None, "phase": "idle", "progress": 0, "started_at": None,
                "finished_at": None, "error": None, "parts": {p: None for p in PARTS}}
    return {"job_id": job.get("id"), "phase": job.get("phase"),
            "progress": job.get("progress", 0), "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"), "error": job.get("error"),
            "parts": job.get("parts") or {p: None for p in PARTS}}
