"""R16 §A: GET/PATCH /workouts/{id}/edit/, POST /workouts/{id}/edit/undo/,
POST /plan/week-edit/. The service is apps/planning/edit_service.py."""

from __future__ import annotations

import datetime as dt

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from planning import edit as rules

from . import edit_service as service
from .models import PlannedWorkout
from .presenters import workout_json


def _bool(value) -> bool:
    return value is True or str(value).lower() in ("1", "true", "yes")


def edit_response(outcome: service.Outcome) -> dict:
    return {**workout_json(outcome.workout), "warnings": outcome.warnings,
            "edit": {"dry_run": outcome.dry_run, "changed": outcome.changed,
                     "before": outcome.before, "after": outcome.after,
                     "summary": outcome.summary},
            "watch": outcome.watch}


def editor_json(athlete, workout: PlannedWorkout) -> dict:
    reason = service.editable_reason(workout)
    limits = service.limits_for(athlete)
    steps = workout.steps or []
    pre = workout.pre_edit if workout.edited_by == service.USER else None
    return {
        "workout_id": workout.pk, "date": workout.date, "title": workout.title,
        "kind": workout.kind,
        "editable": reason in (None, "notes_only"), "notes_only": reason == "notes_only",
        "reason": None if reason in (None, "notes_only") else service.NOT_EDITABLE_TEXT[reason],
        "notes": workout.notes or "",
        "total_s": rules.total_s(steps), "run_s": rules.run_s(steps),
        "walk_s": rules.walk_s(steps),
        "steps": rules.edit_items(steps),
        "planned": ({"title": pre.get("title"), "kind": pre.get("kind"),
                     "duration_s": pre.get("duration_s"), "run_s": rules.run_s(pre.get("steps"))}
                    if pre else None),
        "edited_by": workout.edited_by or None,
        "limits": limits.as_dict(),
        "hr": {"resting": athlete.resting_hr, "max": athlete.max_hr,
               "ceiling": athlete.hr_ceiling, "easy_low": athlete.hr_easy_min,
               "easy_high": athlete.hr_easy_max},
        "pace": {"easy_low": athlete.easy_pace_min, "easy_high": athlete.easy_pace_max},
    }


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def workout_edit(request, pk: int):
    athlete = request.user.athlete
    workout = PlannedWorkout.objects.filter(athlete=athlete, pk=pk).first()
    if workout is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "GET":
        return Response(editor_json(athlete, workout))
    data = request.data if isinstance(request.data, dict) else {}
    try:
        outcome = service.edit_workout(athlete, pk, dict(data), via="app",
                                       dry_run=_bool(data.get("dry_run")))
    except PlannedWorkout.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    except service.NotEditable as exc:
        return Response({"detail": str(exc)}, status=409)
    except rules.EditError as exc:
        return Response({"detail": str(exc)}, status=400)
    return Response(edit_response(outcome))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def workout_edit_undo(request, pk: int):
    try:
        outcome = service.undo_edit(request.user.athlete, pk)
    except PlannedWorkout.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    except service.NotEditable as exc:
        return Response({"detail": str(exc)}, status=409)
    return Response(edit_response(outcome))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def week_edit(request):
    data = request.data if isinstance(request.data, dict) else {}
    try:
        week_start = dt.date.fromisoformat(str(data.get("week_start") or "")[:10])
    except ValueError:
        return Response({"detail": "week_start must be a date (YYYY-MM-DD)."}, status=400)
    try:
        result = service.edit_week(
            request.user.athlete, week_start, data.get("action"), data.get("value"),
            kinds=data.get("kinds"), apply_to=data.get("apply_to"), via="app",
            dry_run=_bool(data.get("dry_run")))
    except service.NoActivePlan as exc:
        return Response({"detail": str(exc)}, status=404)
    except rules.EditError as exc:
        return Response({"detail": str(exc)}, status=400)
    return Response(result.as_json())
