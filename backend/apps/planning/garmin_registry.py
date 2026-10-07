"""Which Garmin workouts RunCoach created, and the same-day cleanup that relies on it.

"Send to watch" must leave exactly one RunCoach copy per workout on the athlete's
Garmin calendar. Re-sending a row already replaces that row's own copy (garmin_push /
garmin_strength_push delete the old id first). What this module adds is the sweep of
everything else RunCoach left on that date: a copy whose row was deleted by a plan
rebuild, re-layout or swap while the forget job was rate-limited, a copy whose id a
reused row overwrote, and so on.

Identification is by stored id only, never by name: every upload is recorded in
GarminUpload (athlete, garmin id, date). The sweep deletes a registered id when no
current PlannedWorkout / StrengthSession of the athlete still holds it. A workout the
athlete made in Garmin Connect was never registered, so it is never touched.

Runs inside the existing garmin-queue jobs, with their client and breaker: a 429 from
a delete is re-raised so the job trips the breaker; any other failure is logged and
the registry row kept, so the next send retries it.
"""

from __future__ import annotations

import datetime as dt
import logging
from types import SimpleNamespace

from .models import GarminUpload, PlannedWorkout, StrengthSession

logger = logging.getLogger(__name__)


def record(athlete, garmin_id: int, schedule_id: int | None, date: dt.date, *,
           workout: PlannedWorkout | None = None,
           strength: StrengthSession | None = None) -> None:
    GarminUpload.objects.update_or_create(
        athlete=athlete, garmin_workout_id=int(garmin_id),
        defaults={"garmin_schedule_id": schedule_id, "date": date,
                  "source": GarminUpload.Source.STRENGTH if strength is not None
                  else GarminUpload.Source.RUN,
                  "workout": workout, "strength": strength})


def forget(athlete_or_id, garmin_ids) -> None:
    """The Garmin copies are gone: drop them from the registry."""
    ids = [int(g) for g in garmin_ids if g]
    if ids:
        athlete_id = getattr(athlete_or_id, "pk", athlete_or_id)
        GarminUpload.objects.filter(athlete_id=athlete_id, garmin_workout_id__in=ids).delete()


def _held_ids(athlete) -> set[int]:
    """Garmin ids a current row still owns (it will replace or remove them itself)."""
    held = set(PlannedWorkout.objects.filter(athlete=athlete, garmin_workout_id__isnull=False)
               .values_list("garmin_workout_id", flat=True))
    held |= set(StrengthSession.objects.filter(athlete=athlete, garmin_workout_id__isnull=False)
                .values_list("garmin_workout_id", flat=True))
    return held


def stale(athlete, dates) -> list[GarminUpload]:
    dates = {d for d in dates if d}
    if not dates:
        return []
    held = _held_ids(athlete)
    return [u for u in GarminUpload.objects.filter(athlete=athlete, date__in=dates)
            if u.garmin_workout_id not in held]


def sweep(client, athlete, dates) -> list[int]:
    """Delete RunCoach's leftover Garmin workouts on `dates`. Returns the removed ids."""
    from .garmin_push import _delete_remote, _rate_limited

    removed = []
    for upload in stale(athlete, dates):
        try:
            _delete_remote(client, SimpleNamespace(garmin_workout_id=upload.garmin_workout_id,
                                                   garmin_schedule_id=upload.garmin_schedule_id))
        except Exception as exc:  # noqa: BLE001
            if _rate_limited(exc):
                raise
            logger.warning("could not remove stale garmin workout %s: %s",
                           upload.garmin_workout_id, exc)
            continue
        upload.delete()
        removed.append(upload.garmin_workout_id)
    if removed:
        logger.info("athlete %s: removed %d stale garmin workouts", athlete.pk, len(removed))
    return removed


def date_of(athlete, garmin_id) -> dt.date | None:
    """The date RunCoach scheduled a copy on (the OLD date when a row has moved)."""
    if not garmin_id:
        return None
    return GarminUpload.objects.filter(athlete=athlete, garmin_workout_id=garmin_id) \
        .values_list("date", flat=True).first()
