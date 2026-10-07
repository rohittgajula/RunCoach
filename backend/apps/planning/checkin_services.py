"""R7 §1: the morning check-in for one athlete (GET /today/, apply, explain).

The verdict comes from the pure planning/checkin.py; this module only gathers the
inputs (snapshot_for, today's persisted PlannedWorkout, the athlete's bands) and
writes an accepted adjustment back. Nothing here ever applies a change on its own —
the athlete taps "Use this".
"""

from __future__ import annotations

from django.db import transaction

from apps.athletes.models import Athlete
from planning.checkin import Verdict, WorkoutSummary, decide

from .models import PlannedWorkout, TrainingPlan
from .plan_services import snapshot_for

CHECKIN = "checkin"


def today_workout(athlete: Athlete) -> PlannedWorkout | None:
    """Today's workout in the active plan (skipped ones do not count)."""
    return (
        PlannedWorkout.objects.filter(
            athlete=athlete, date=athlete.local_today,
            plan__status=TrainingPlan.Status.ACTIVE,
        ).exclude(status=PlannedWorkout.Status.SKIPPED)
        .select_related("phase").order_by("id").first()
    )


def _as_planned(workout: PlannedWorkout) -> dict:
    """The prescription before any check-in: the stored original when applied."""
    if workout.adjusted_by == CHECKIN and workout.original_steps is not None:
        original = workout.original or {}
        return {
            "title": original.get("title", workout.title),
            "kind": original.get("kind", workout.kind),
            "duration_s": original.get("duration_s", workout.duration_s),
            "load": original.get("load", workout.load),
            "target_zone": original.get("target_zone", workout.target_zone),
            "description": original.get("description", workout.description),
            "steps": workout.original_steps,
        }
    return {"title": workout.title, "kind": workout.kind, "duration_s": workout.duration_s,
            "load": workout.load, "target_zone": workout.target_zone,
            "description": workout.description, "steps": workout.steps or []}


def _summary(athlete: Athlete, workout: PlannedWorkout | None) -> WorkoutSummary | None:
    if workout is None:
        return None
    from .plan_store import bands_for

    bands = bands_for(athlete)
    planned = _as_planned(workout)
    return WorkoutSummary(
        title=planned["title"], kind=planned["kind"], duration_s=planned["duration_s"],
        steps=list(planned["steps"]), target_zone=planned["target_zone"],
        easy_pace=bands.easy_pace, hr_easy=bands.hr_easy,
    )


def compute(athlete: Athlete) -> tuple[Verdict, PlannedWorkout | None]:
    workout = today_workout(athlete)
    return decide(snapshot_for(athlete), _summary(athlete, workout)), workout


def today_payload(athlete: Athlete) -> dict:
    from apps.coaching.services import cached_checkin_explanation, checkin_explain_payload

    from .presenters import workout_json

    verdict, workout = compute(athlete)
    payload = {
        "date": athlete.local_today,
        "verdict": verdict.verdict,
        "headline": verdict.headline,
        "reasons": verdict.reasons,
        "signals_missing": verdict.signals_missing,
        "note": verdict.note,
        "workout": workout_json(workout) if workout else None,
        "adjusted": verdict.adjusted,
        "applied": bool(workout and workout.adjusted_by == CHECKIN),
        "explanation": {"status": "none", "text": ""},
    }
    text = cached_checkin_explanation(athlete, checkin_explain_payload(payload))
    if text:
        payload["explanation"] = {"status": "ready", "text": text}
    return payload


class NothingToApply(Exception):
    pass


def apply_today(athlete: Athlete) -> None:
    """Write today's `adjusted` onto the PlannedWorkout. Idempotent.

    The first apply stores the prescription as planned in `original_steps` /
    `original`; a later apply (new data, a different verdict) starts again from that
    original, never from an already-adjusted workout.
    """
    with transaction.atomic():
        verdict, workout = compute(athlete)
        if workout is None or verdict.adjusted is None:
            raise NothingToApply("Nothing to change today — go as planned.")
        if workout.status != PlannedWorkout.Status.PLANNED:
            raise NothingToApply("Today's workout is already done.")
        workout = PlannedWorkout.objects.select_for_update().get(pk=workout.pk)
        adjusted = verdict.adjusted
        if (workout.adjusted_by == CHECKIN and workout.steps == adjusted["steps"]
                and workout.title == adjusted["title"]):
            return
        if workout.adjusted_by != CHECKIN or workout.original_steps is None:
            workout.original_steps = workout.steps or []
            workout.original = {
                "title": workout.title, "kind": workout.kind,
                "duration_s": workout.duration_s, "load": workout.load,
                "target_zone": workout.target_zone, "description": workout.description,
            }
        workout.title = adjusted["title"][:120]
        workout.kind = adjusted["kind"]
        workout.duration_s = adjusted["duration_s"]
        workout.load = adjusted["load"]
        workout.steps = adjusted["steps"]
        workout.target_zone = adjusted["target_zone"]
        workout.description = adjusted["description"]
        workout.adjusted_by = CHECKIN
        workout.save()
        # Already on the watch? Replace it with the eased version (or remove it for a
        # rest day — the push job removes a workout with no steps).
        from .garmin_sync import resync_on_garmin

        resync_on_garmin(athlete, [workout.pk])


def explain_today(athlete: Athlete) -> dict:
    """Generate (or fetch) today's one-line explanation. Raises AIUnavailable."""
    from apps.coaching.services import checkin_explain_payload, checkin_explanation

    payload = today_payload(athlete)
    if payload["explanation"]["status"] != "ready":
        text = checkin_explanation(athlete, checkin_explain_payload(payload))
        payload["explanation"] = {"status": "ready", "text": text}
    return payload
