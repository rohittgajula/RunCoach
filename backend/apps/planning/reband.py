"""Re-apply heart-rate bands to future workouts after the athlete changes their HR
settings (zones method, max / resting HR, or their own easy-run range).

Workouts store their HR targets in `steps` when they are created, so without this a
settings change would only reach sessions generated afterwards — and the watch would
keep showing the old numbers. Rules:

* only future PLANNED workouts (today onwards);
* a step the athlete edited with its own HR target (`target` set) is left alone;
* walk steps carry no band of their own (the Garmin payload derives the walk band);
* on a workout the check-in eased (`adjusted_by` set) a band never gets harder:
  each edge is the lower of the old and new value.

Changed workouts are re-sent to Garmin (apps.planning.garmin_sync.resync_on_garmin).
"""

from __future__ import annotations

from django.db import transaction

from .garmin_sync import resync_on_garmin
from .models import PlannedWorkout


def _band_for(intensity: str | None, bands) -> tuple[int, int] | None:
    return {"easy": bands.hr_easy, "moderate": bands.hr_moderate,
            "hard": bands.hr_hard}.get(intensity or "")


def reband_steps(steps: list[dict], bands, *, eased: bool = False) -> tuple[list[dict], bool]:
    """(new steps, whether anything changed). Pure; easy to test."""
    out, changed = [], False
    for step in steps or []:
        step = dict(step)
        if step.get("target") or step.get("intensity") == "walk" or not step.get("hr_max"):
            out.append(step)
            continue
        band = _band_for(step.get("intensity"), bands)
        if band and band[0] and band[1]:
            low, high = band
            if eased:
                low, high = min(low, step["hr_min"] or low), min(high, step["hr_max"])
            if (low, high) != (step.get("hr_min"), step.get("hr_max")):
                step["hr_min"], step["hr_max"] = int(low), int(high)
                changed = True
        out.append(step)
    return out, changed


@transaction.atomic
def reband_future_workouts(athlete) -> dict:
    """{updated, watch_updated}: how many future workouts got new HR targets, and how
    many of those were queued to be re-sent to the watch."""
    from .plan_store import bands_for

    bands = bands_for(athlete)
    rows = PlannedWorkout.objects.select_for_update().filter(
        athlete=athlete, status=PlannedWorkout.Status.PLANNED, date__gte=athlete.local_today)
    changed_ids = []
    for row in rows:
        steps, changed = reband_steps(row.steps, bands, eased=bool(row.adjusted_by))
        if changed:
            row.steps = steps
            row.save(update_fields=["steps"])
            changed_ids.append(row.pk)
    watch = resync_on_garmin(athlete, changed_ids) if changed_ids else 0
    return {"updated": len(changed_ids), "watch_updated": watch}
