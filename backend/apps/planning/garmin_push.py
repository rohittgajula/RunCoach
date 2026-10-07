"""Send planned workouts to the athlete's Garmin calendar (R7 §3).

Runs on the `garmin` queue (concurrency 1) like every other Garmin call, and honours
the same circuit breaker: a 429 stops the batch and trips it for everyone.

Idempotent per workout. The hash of the exact JSON uploaded (plus its date) is stored;
sending again with the same hash is a no-op, a different hash (check-in applied,
moved, rebuilt) deletes the old Garmin workout and uploads the new one. Every
workout gets its own result — a batch never reports success for a part that failed.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from apps.athletes.models import Athlete
from planning.garmin_workout import build_payload, payload_hash

from .models import PlannedWorkout

logger = logging.getLogger(__name__)


class JobFailed(Exception):
    """The whole job could not run (breaker open, no session, rate limited)."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _client(athlete: Athlete):
    from apps.ingest.garmin import _client as garmin_client

    return garmin_client(athlete)


def _rate_limited(exc: Exception) -> bool:
    text = str(exc)
    return "429" in text or "TooManyRequests" in text


def _not_found(exc: Exception) -> bool:
    return "404" in str(exc) or "Not Found" in str(exc)


def _result(workout: PlannedWorkout, status: str, detail: str = "") -> dict:
    return {"workout_id": workout.pk, "date": workout.date.isoformat(), "status": status,
            "garmin_workout_id": workout.garmin_workout_id,
            "synced_at": workout.garmin_synced_at.isoformat() if workout.garmin_synced_at
            else None, "detail": detail}


def _source(workout: PlannedWorkout) -> dict:
    return {"title": workout.title, "duration_s": workout.duration_s,
            "steps": workout.steps or [], "description": workout.description}


def _clear(workout: PlannedWorkout) -> None:
    workout.garmin_workout_id = None
    workout.garmin_schedule_id = None
    workout.garmin_synced_at = None
    workout.garmin_payload_hash = ""
    workout.save(update_fields=["garmin_workout_id", "garmin_schedule_id",
                                "garmin_synced_at", "garmin_payload_hash"])


def _delete_remote(client, workout: PlannedWorkout) -> None:
    """Unschedule and delete the Garmin copy. A copy already gone is not an error."""
    if workout.garmin_schedule_id:
        try:
            client.unschedule_workout(workout.garmin_schedule_id)
        except Exception as exc:  # noqa: BLE001
            if _rate_limited(exc):
                raise
            logger.info("unschedule %s: %s", workout.garmin_schedule_id, exc)
    try:
        client.delete_workout(workout.garmin_workout_id)
    except Exception as exc:  # noqa: BLE001
        if not _not_found(exc):
            raise


def _schedule_id(response) -> int | None:
    if not isinstance(response, dict):
        return None
    for key in ("workoutScheduleId", "scheduleId", "id"):
        if response.get(key):
            try:
                return int(response[key])
            except (TypeError, ValueError):
                return None
    return None


def send_one(client, workout: PlannedWorkout, today) -> dict:
    """Upload (or update) one workout on the athlete's Garmin calendar."""
    from garminconnect.workout import RunningWorkout

    if workout.status != PlannedWorkout.Status.PLANNED:
        return _result(workout, "skipped", f"Workout is {workout.status}.")
    if workout.date < today:
        return _result(workout, "skipped", "Workout is in the past.")
    steps = [s for s in workout.steps or [] if (s.get("duration_s") or 0) > 0]
    if not steps:
        if workout.garmin_workout_id:
            _delete_remote(client, workout)
            _clear(workout)
            return _result(workout, "removed", "Nothing to do today — removed from the watch.")
        return _result(workout, "skipped", "Nothing to send (rest day).")

    payload = build_payload(_source(workout))
    digest = payload_hash(payload, workout.date.isoformat())
    if workout.garmin_workout_id and workout.garmin_payload_hash == digest:
        return _result(workout, "unchanged")

    replacing = bool(workout.garmin_workout_id)
    if replacing:
        _delete_remote(client, workout)
        _clear(workout)

    uploaded = client.upload_running_workout(RunningWorkout.model_validate(payload))
    garmin_id = (uploaded or {}).get("workoutId") if isinstance(uploaded, dict) else None
    if not garmin_id:
        return _result(workout, "error", "Garmin did not return a workout id.")
    try:
        scheduled = client.schedule_workout(garmin_id, workout.date.isoformat())
    except Exception:
        # Do not leave an unscheduled orphan in the athlete's library.
        try:
            client.delete_workout(garmin_id)
        except Exception:  # noqa: BLE001
            logger.warning("could not remove unscheduled garmin workout %s", garmin_id)
        raise

    workout.garmin_workout_id = int(garmin_id)
    workout.garmin_schedule_id = _schedule_id(scheduled)
    workout.garmin_synced_at = timezone.now()
    workout.garmin_payload_hash = digest
    workout.save(update_fields=["garmin_workout_id", "garmin_schedule_id",
                                "garmin_synced_at", "garmin_payload_hash"])
    return _result(workout, "updated" if replacing else "uploaded")


def remove_one(client, workout: PlannedWorkout) -> dict:
    if not workout.garmin_workout_id:
        return _result(workout, "skipped", "Not on the watch.")
    _delete_remote(client, workout)
    _clear(workout)
    return _result(workout, "removed")


def run_job(athlete_id: int, workout_ids: list[int], action: str) -> dict:
    """Body of the garmin-queue task. Returns {ok, code, detail, results}."""
    from apps.ingest.garmin import GarminAuthError, GarminRateLimited
    from apps.ingest.tasks import garmin_blocked, trip_breaker

    athlete = Athlete.objects.filter(pk=athlete_id).first()
    if athlete is None:
        return {"ok": False, "code": "gone", "detail": "No such athlete.", "results": []}
    if garmin_blocked():
        return {"ok": False, "code": "rate_limited", "results": [],
                "detail": "Garmin is rate-limiting this server. Try again in a while."}
    workouts = list(PlannedWorkout.objects.filter(athlete=athlete, pk__in=workout_ids)
                    .order_by("date", "id"))
    try:
        client = _client(athlete)
    except GarminRateLimited as exc:
        trip_breaker(str(exc))
        return {"ok": False, "code": "rate_limited", "detail": str(exc), "results": []}
    except GarminAuthError as exc:
        return {"ok": False, "code": "auth", "detail": str(exc), "results": []}

    today = athlete.local_today
    results: list[dict] = []
    for index, workout in enumerate(workouts):
        try:
            results.append(remove_one(client, workout) if action == "delete"
                           else send_one(client, workout, today))
        except Exception as exc:  # noqa: BLE001 — every workout gets a result
            if _rate_limited(exc):
                trip_breaker(f"workout push: {exc}")
                results.append(_result(workout, "error", "Garmin rate-limited the upload."))
                results += [_result(w, "error", "Not attempted: Garmin rate limit.")
                            for w in workouts[index + 1:]]
                break
            logger.warning("garmin push failed for workout %s: %s", workout.pk, exc)
            results.append(_result(workout, "error", str(exc)[:300]))
    ok = all(r["status"] != "error" for r in results)
    return {"ok": ok, "code": None if ok else "partial",
            "detail": "" if ok else "Some workouts could not be sent to Garmin.",
            "results": results}


def forget_remote(athlete_id: int, refs: list[list]) -> dict:
    """Remove Garmin copies of workouts that no longer exist here.

    Accepting or rebuilding a plan deletes the old plan's future workouts. Their copies
    on the athlete's Garmin calendar used to stay behind, so the watch showed the same
    day's run three times. `refs` is [[garmin_workout_id, garmin_schedule_id|None], …],
    captured before the local rows were deleted. A copy already gone is fine.
    """
    from types import SimpleNamespace

    from apps.ingest.garmin import GarminAuthError, GarminRateLimited
    from apps.ingest.tasks import garmin_blocked, trip_breaker

    athlete = Athlete.objects.filter(pk=athlete_id).first()
    if athlete is None:
        return {"removed": [], "failed": [r[0] for r in refs], "detail": "gone"}
    if garmin_blocked():
        logger.warning("breaker open: %d garmin workouts left on the watch", len(refs))
        return {"removed": [], "failed": [r[0] for r in refs], "detail": "rate_limited"}
    try:
        client = _client(athlete)
    except GarminRateLimited as exc:
        trip_breaker(str(exc))
        return {"removed": [], "failed": [r[0] for r in refs], "detail": "rate_limited"}
    except GarminAuthError as exc:
        return {"removed": [], "failed": [r[0] for r in refs], "detail": str(exc)}
    removed, failed = [], []
    for index, (garmin_id, schedule_id) in enumerate(refs):
        try:
            _delete_remote(client, SimpleNamespace(garmin_workout_id=garmin_id,
                                                   garmin_schedule_id=schedule_id))
            removed.append(garmin_id)
        except Exception as exc:  # noqa: BLE001 — log and keep going; one failure is not all
            logger.warning("could not remove garmin workout %s: %s", garmin_id, exc)
            failed.append(garmin_id)
            if _rate_limited(exc):
                trip_breaker(f"workout forget: {exc}")
                failed += [ref[0] for ref in refs[index + 1:]]
                break
    return {"removed": removed, "failed": failed}
