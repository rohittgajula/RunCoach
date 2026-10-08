"""JSON shapes for §5 of the spec: Workout, ActivityCard, PlanSummary, Plan.

Plain functions rather than nested DRF serializers because these shapes are a contract
with a frontend built in parallel: every key is written out here, once, where a
reviewer can check it against the spec line by line. Each takes objects already
scoped to one athlete — none of them queries across tenants.
"""

from __future__ import annotations

import datetime as dt

from apps.activities.models import Activity

from planning.workouts import GUARD_KINDS

from .models import PlannedWorkout, TrainingPlan
from .plan_store import current_phase, plan_weeks
from .serializers import RaceSerializer


def guard_base(athlete) -> dict:
    """The athlete-level inputs of the easy-day guard (R7 §3). One zones() lookup;
    pass the result to workout_json when presenting many workouts."""
    zones = athlete.zones()
    return {"z2_high": zones.band("Z2").high if zones else None,
            "hr_ceiling": athlete.hr_ceiling,
            "easy_pace": (athlete.easy_pace_min, athlete.easy_pace_max)}


def garmin_status(workout: PlannedWorkout) -> str:
    """none | synced | changed — whether the watch copy matches the workout now."""
    if not workout.garmin_workout_id:
        return "none"
    from planning.garmin_workout import build_payload, payload_hash

    current = payload_hash(build_payload(_garmin_source(workout)), workout.date.isoformat())
    return "synced" if current == workout.garmin_payload_hash else "changed"


def _garmin_source(workout: PlannedWorkout) -> dict:
    """What planning.garmin_workout.build_payload is given — by the push AND by the
    status check, so both hash the same payload. `hr` carries the athlete numbers the
    walk / warm-up / cool-down bands come from (profile fields only: no query whose
    answer drifts day to day, so a synced workout does not flip to "changed")."""
    athlete = workout.athlete
    description = workout.description
    if (workout.notes or "").strip():
        # R16: the athlete's own notes ride along (only when there are some, so a
        # generated workout's payload — and hash — is unchanged).
        description = f"{description}\n\nNotes: {workout.notes.strip()}".strip()
    return {"title": workout.title, "duration_s": workout.duration_s,
            "steps": workout.steps or [], "description": description,
            "hr": {"resting_hr": athlete.resting_hr, "hr_easy_min": athlete.hr_easy_min,
                   "hr_easy_max": athlete.hr_easy_max, "hr_ceiling": athlete.hr_ceiling}}


def workout_json(workout: PlannedWorkout, guard_inputs: dict | None = None) -> dict:
    from planning.workouts import easy_guard

    phase = workout.phase
    return {
        "id": workout.pk,
        "date": workout.date,
        "title": workout.title,
        "kind": workout.kind,
        "phase": {"id": phase.pk, "name": phase.name, "kind": phase.kind} if phase else None,
        "duration_s": workout.duration_s,
        "load": workout.load,
        "steps": workout.steps or [],
        "description": workout.description,
        "purpose": workout.purpose,
        "target_zone": workout.target_zone,
        "fueling": workout.fueling or {
            "before": "", "during": "", "after": "", "carbs_g_during_per_h": None,
        },
        "status": workout.status,
        "completed_activity_id": workout.completed_activity_id,
        **_done_blocks(workout),
        # R7 §3: easy-day guard (null for kinds it does not apply to).
        "guard": easy_guard(workout.kind, **(guard_inputs or guard_base(workout.athlete)))
        if workout.kind in GUARD_KINDS else None,
        # R7 §1: morning check-in applied.
        "adjusted_by": workout.adjusted_by or None,
        "original_steps": workout.original_steps,
        "original": workout.original,
        # R13 §1: the automatic change on this workout, if any.
        "auto_adjustment": _auto_adjustment(workout),
        # R7 §3: on the watch.
        "garmin_workout_id": workout.garmin_workout_id,
        "garmin_synced_at": workout.garmin_synced_at,
        "garmin_status": garmin_status(workout),
        # R16 §A: the athlete's edits.
        **edit_fields(workout),
        # R17 §10: illness mode.
        "paused_by_illness": workout.paused_by_illness,
        "illness_return": workout.illness_return,
    }


def edit_fields(workout: PlannedWorkout, today: dt.date | None = None) -> dict:
    from .edit_service import editable_reason

    reason = editable_reason(workout, today)
    edited = workout.edited_by == "user"
    pre = workout.pre_edit if edited else None
    return {
        "edited_by": workout.edited_by or None,
        "edited_at": workout.edited_at,
        "edited_via": workout.edited_via or None,
        "notes": workout.notes or "",
        "can_edit": reason is None or reason == "notes_only",
        "can_undo_edit": edited and pre is not None and reason in (None, "notes_only"),
        "planned": _planned_brief(pre) if pre else None,
    }


def _planned_brief(pre: dict) -> dict:
    from planning.edit import run_s

    return {"title": pre.get("title"), "kind": pre.get("kind"),
            "duration_s": pre.get("duration_s"), "run_s": run_s(pre.get("steps"))}


def _auto_adjustment(workout: PlannedWorkout) -> dict | None:
    if workout.adjusted_by != "auto":
        return None
    from .auto_adjust import current_for

    return current_for(workout)


def _done_blocks(workout: PlannedWorkout) -> dict:
    """R6 §3: actual / compliance / review — null until an activity is linked."""
    from .actuals import actual_json, compliance_json, review_json

    activity = workout.completed_activity if workout.completed_activity_id else None
    if activity is None:
        return {"actual": None, "compliance": None, "review": None}
    return {
        "actual": actual_json(activity),
        "compliance": compliance_json(workout, activity),
        "review": review_json(activity),
    }


def _activity_name(activity: Activity, timezone_name: str) -> str:
    """Activity has no stored name; build one the way Garmin does ("Morning Run")."""
    from zoneinfo import ZoneInfo

    try:
        hour = activity.started_at.astimezone(ZoneInfo(timezone_name or "UTC")).hour
    except Exception:  # noqa: BLE001
        hour = activity.started_at.hour
    part = "Morning" if 4 <= hour < 12 else "Afternoon" if hour < 17 else "Evening" \
        if hour < 21 else "Night"
    sport = (activity.sport or "activity").replace("_", " ").title()
    sport = {"Running": "Run", "Walking": "Walk", "Cycling": "Ride"}.get(sport, sport)
    return f"{part} {sport}"


def is_run(activity: Activity) -> bool:
    return "run" in (activity.sport or "").lower()


def _clock(seconds: float) -> str:
    """210 -> "3:30". What was done is shown to the second, as the watch shows it."""
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _activity_steps(activity: Activity) -> list[dict] | None:
    """Run and walk segments as Steps, so the same workout bar draws what was done.
    Stops are left out: on the bar a stop is a gap, not a block."""
    segments = [s for s in activity.segments.all() if s.kind in ("run", "walk")]
    if not segments:
        return None
    steps = []
    for segment in segments:
        is_run = segment.kind == "run"
        pace = round(segment.avg_pace_s_per_km) if segment.avg_pace_s_per_km else None
        steps.append({
            "kind": "run" if is_run else "walk",
            "duration_s": round(segment.duration_s),
            "intensity": "easy" if is_run else "walk",
            "label": f"{'Run' if is_run else 'Walk'} {_clock(segment.duration_s)}",
            "pace_min_s": pace, "pace_max_s": pace,
            "hr_min": segment.hr_avg, "hr_max": segment.hr_max,
        })
    return steps


def activity_cards(athlete, activities: list[Activity]) -> list[dict]:
    """ActivityCards for several activities with a fixed number of queries."""
    from apps.coaching.models import ChatMessage
    from apps.journal.models import JournalEntry

    if not activities:
        return []
    ids = [a.pk for a in activities]
    dates = {a.local_date for a in activities}
    journalled_dates = set(
        # R7: a date is covered only by entries not tied to another activity.
        JournalEntry.objects.filter(athlete=athlete, applies_to_date__in=dates,
                                    activity__isnull=True)
        .values_list("applies_to_date", flat=True)
    )
    journalled_ids = set(
        JournalEntry.objects.filter(athlete=athlete, activity_id__in=ids)
        .values_list("activity_id", flat=True)
    )

    # The thread an activity was reviewed in: the newest user message that attached it.
    reviewed: dict[int, int] = {}
    for message in ChatMessage.objects.filter(
        thread__athlete=athlete, role=ChatMessage.Role.USER,
        attachments__contains=[{"type": "activity"}],
    ).order_by("created_at").only("thread_id", "attachments"):
        for attachment in message.attachments or []:
            if attachment.get("type") == "activity" and attachment.get("id") in ids:
                reviewed[attachment["id"]] = message.thread_id

    linked = set(
        PlannedWorkout.objects.filter(athlete=athlete, completed_activity_id__in=ids)
        .values_list("completed_activity_id", flat=True)
    )

    cards = []
    for activity in activities:
        metrics = getattr(activity, "metrics", None)
        cards.append({
            "id": activity.pk,
            "name": _activity_name(activity, athlete.timezone),
            "sport": activity.sport,
            "device": "Garmin" if activity.source == Activity.Source.GARMIN_SYNC else "FIT upload",
            "start": activity.started_at,
            "duration_s": round(activity.total_timer_s or activity.total_elapsed_s or 0),
            "distance_m": round(activity.total_distance_m or 0),
            "load": metrics.custom_load if metrics else None,
            "run_distance_m": round(metrics.run_distance_m) if metrics else None,
            "walk_distance_m": round(metrics.walk_distance_m) if metrics else None,
            "run_fraction": round(metrics.run_fraction, 2) if metrics else None,
            "longest_run_s": round(metrics.longest_run_s) if metrics else None,
            "steps": _activity_steps(activity),
            "journalled": activity.pk in journalled_ids or activity.local_date in journalled_dates,
            "reviewed_thread_id": reviewed.get(activity.pk),
            # R6 §2: a run that completed no planned workout — the "Extra" tag.
            "unplanned": is_run(activity) and activity.pk not in linked,
        })
    return cards


def activity_card(athlete, activity: Activity) -> dict:
    return activity_cards(athlete, [activity])[0]


def phase_json(phase) -> dict:
    return {
        "id": phase.pk, "order": phase.order, "name": phase.name, "kind": phase.kind,
        "start": phase.start, "end": phase.end, "description": phase.description,
    }


def plan_summary(plan: TrainingPlan, today: dt.date) -> dict:
    phases = list(plan.phases.all())
    current = current_phase(plan, today)
    return {
        "id": plan.pk,
        "name": plan.name,
        "goal": plan.goal,
        "status": plan.status,
        "race": RaceSerializer(plan.race).data if plan.race else None,
        "phase_count": len(phases),
        "start": phases[0].start if phases else None,
        "end": phases[-1].end if phases else None,
        "current_phase_id": current.pk if current else None,
        "phases": [phase_json(p) for p in phases],
    }


def plan_detail(plan: TrainingPlan, today: dt.date) -> dict:
    return {
        **plan_summary(plan, today),
        "summary": plan.summary or {},
        "weeks": plan_weeks(plan),
        "adjustments": [
            {"week_start": a.week_start, "reason": a.reason, "factor": a.factor,
             "created_at": a.created_at}
            for a in plan.adjustments.all()
        ],
    }
