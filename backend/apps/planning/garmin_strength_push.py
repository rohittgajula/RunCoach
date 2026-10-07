"""R13 §4: send a strength session to the athlete's Garmin calendar.

Same rules as the running workouts (garmin_push.py): the `garmin` queue (concurrency 1),
the shared circuit breaker (a 429 trips it for everyone), the existing authenticated
client, and idempotency by payload hash. Uses `Garmin.upload_strength_workout`
(garminconnect 0.3.10) with a `StrengthWorkout` built from planning/garmin_strength.py,
then `schedule_workout`, exactly like the running upload — including the GarminUpload
registry and the same-day sweep of RunCoach leftovers (garmin_registry).

Strength steps stay `no.target` (planning/garmin_strength.py): they are reps and
time, not paced, so there is no heart-rate band to show.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from apps.athletes.models import Athlete
from planning.garmin_strength import build_payload, payload_hash

from . import garmin_registry as registry
from .garmin_push import _client, _rate_limited, _schedule_id, _schedule_or_discard, remove_copy
from .models import StrengthSession

logger = logging.getLogger(__name__)


def _result(session: StrengthSession, status: str, detail: str = "") -> dict:
    return {"strength_id": session.pk, "date": session.date.isoformat(), "status": status,
            "garmin_workout_id": session.garmin_workout_id, "detail": detail}


def send_one(client, session: StrengthSession, today) -> dict:
    from garminconnect.workout import StrengthWorkout

    if session.status != StrengthSession.Status.PLANNED:
        return _result(session, "skipped", f"Session is {session.status}.")
    if session.date < today:
        return _result(session, "skipped", "Session is in the past.")
    payload = build_payload({"title": session.title, "duration_s": session.duration_s,
                             "exercises": session.exercises or []})
    digest = payload_hash(payload, session.date.isoformat())
    athlete = session.athlete
    registry.sweep(client, athlete,
                   {session.date, registry.date_of(athlete, session.garmin_workout_id)})
    if session.garmin_workout_id and session.garmin_payload_hash == digest:
        return _result(session, "unchanged")
    replacing = bool(session.garmin_workout_id)
    if replacing:
        remove_copy(client, session)
    uploaded = client.upload_strength_workout(StrengthWorkout.model_validate(payload))
    garmin_id = (uploaded or {}).get("workoutId") if isinstance(uploaded, dict) else None
    if not garmin_id:
        return _result(session, "error", "Garmin did not return a workout id.")
    registry.record(athlete, garmin_id, None, session.date, strength=session)
    scheduled = _schedule_or_discard(client, athlete, garmin_id, session.date)
    session.garmin_workout_id = int(garmin_id)
    session.garmin_schedule_id = _schedule_id(scheduled)
    session.garmin_synced_at = timezone.now()
    session.garmin_payload_hash = digest
    session.save(update_fields=["garmin_workout_id", "garmin_schedule_id",
                                "garmin_synced_at", "garmin_payload_hash"])
    registry.record(athlete, garmin_id, session.garmin_schedule_id, session.date,
                    strength=session)
    return _result(session, "updated" if replacing else "uploaded")


def run_job(athlete_id: int, session_ids: list[int], action: str) -> dict:
    from apps.ingest.garmin import GarminAuthError, GarminRateLimited
    from apps.ingest.tasks import garmin_blocked, trip_breaker

    athlete = Athlete.objects.filter(pk=athlete_id).first()
    if athlete is None:
        return {"ok": False, "code": "gone", "results": []}
    if garmin_blocked():
        return {"ok": False, "code": "rate_limited", "results": []}
    sessions = list(StrengthSession.objects.filter(athlete=athlete, pk__in=session_ids)
                    .order_by("date", "id"))
    try:
        client = _client(athlete)
    except GarminRateLimited as exc:
        trip_breaker(str(exc))
        return {"ok": False, "code": "rate_limited", "results": []}
    except GarminAuthError:
        return {"ok": False, "code": "auth", "results": []}
    today = athlete.local_today
    results = []
    for index, session in enumerate(sessions):
        try:
            if action == "delete":
                if session.garmin_workout_id:
                    remove_copy(client, session)
                    results.append(_result(session, "removed"))
                else:
                    results.append(_result(session, "skipped", "Not on the watch."))
            else:
                results.append(send_one(client, session, today))
        except Exception as exc:  # noqa: BLE001
            if _rate_limited(exc):
                trip_breaker(f"strength push: {exc}")
                results.append(_result(session, "error", "Garmin rate-limited the upload."))
                results += [_result(s, "error", "Not attempted: Garmin rate limit.")
                            for s in sessions[index + 1:]]
                break
            logger.warning("garmin strength push failed for %s: %s", session.pk, exc)
            results.append(_result(session, "error", str(exc)[:300]))
    ok = all(r["status"] != "error" for r in results)
    return {"ok": ok, "code": None if ok else "partial", "results": results}
