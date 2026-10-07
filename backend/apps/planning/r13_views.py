"""R13 endpoints: auto-adjustments (§1), the race-day plan (§2) and strength sessions (§4).

Every lookup filters on the requesting athlete; another athlete's id is a 404.
"""

from __future__ import annotations

import datetime as dt

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Race, StrengthSession, WorkoutAdjustment

MAX_STRENGTH_DAYS = 62


def _bad(message: str, code=status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"detail": message}, status=code)


def _int(raw, default, low, high):
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if low <= value <= high else None


# --- §1 -----------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def adjustments(request):
    from .auto_adjust import adjustment_json

    athlete = request.user.athlete
    limit = _int(request.query_params.get("limit"), 20, 1, 100)
    if limit is None:
        return _bad("limit must be a whole number 1–100.")
    today = athlete.local_today
    rows = (WorkoutAdjustment.objects.filter(athlete=athlete)
            .select_related("workout", "athlete")[:limit])
    return Response({"enabled": athlete.auto_adjust_plan,
                     "adjustments": [adjustment_json(r, today) for r in rows]})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def adjustment_undo(request, pk: int):
    from .auto_adjust import NotUndoable, adjustment_json, undo

    athlete = request.user.athlete
    try:
        adj = undo(athlete, pk)
    except WorkoutAdjustment.DoesNotExist:
        return _bad("Not found.", status.HTTP_404_NOT_FOUND)
    except NotUndoable as exc:
        return _bad(str(exc), status.HTTP_409_CONFLICT)
    return Response(adjustment_json(adj))


# --- §2 -----------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def race_plan_view(request, pk: int):
    from .race_plan import race_plan

    athlete = request.user.athlete
    race = Race.objects.filter(athlete=athlete, pk=pk).first()
    if race is None:
        return _bad("Not found.", status.HTTP_404_NOT_FOUND)
    strategy = request.query_params.get("strategy", "even")
    if strategy not in ("even", "negative"):
        return _bad("strategy must be even or negative.")
    return Response(race_plan(athlete, race, strategy))


# --- §4 -----------------------------------------------------------------------------

def _date(raw):
    try:
        return dt.date.fromisoformat(raw) if raw else None
    except ValueError:
        return False


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def strength_list(request):
    from planning.strength import SUGGESTED_PER_WEEK

    from .strength_service import can_send, sessions_between, strength_json

    athlete = request.user.athlete
    today = athlete.local_today
    start, end = _date(request.query_params.get("start")), _date(request.query_params.get("end"))
    if start is False or end is False:
        return _bad("Dates must be YYYY-MM-DD.")
    start = start or today - dt.timedelta(days=7)
    end = end or start + dt.timedelta(days=35)
    if end < start:
        return _bad("end must not be before start.")
    if (end - start).days + 1 > MAX_STRENGTH_DAYS:
        return _bad(f"At most {MAX_STRENGTH_DAYS} days per request.")
    send = can_send(athlete)
    return Response({"per_week": athlete.strength_per_week, "suggested": SUGGESTED_PER_WEEK,
                     "can_send_to_watch": send,
                     "sessions": [strength_json(s, send)
                                  for s in sessions_between(athlete, start, end)]})


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def strength_detail(request, pk: int):
    from .garmin_sync import _queue
    from .strength_service import strength_json
    from .tasks import garmin_strength_push_task

    athlete = request.user.athlete
    session = StrengthSession.objects.filter(athlete=athlete, pk=pk).first()
    if session is None:
        return _bad("Not found.", status.HTTP_404_NOT_FOUND)
    data = request.data if isinstance(request.data, dict) else {}
    unknown = set(data) - {"status", "date"}
    if unknown:
        return _bad(f"Unknown field(s): {', '.join(sorted(unknown))}.")
    fields = []
    if "status" in data:
        if data["status"] not in StrengthSession.Status.values:
            return _bad("status must be planned, completed or skipped.")
        session.status = data["status"]
        if session.status != StrengthSession.Status.COMPLETED:
            session.completed_activity = None
            session.auto_completed = False
            fields += ["completed_activity", "auto_completed"]
        fields.append("status")
    if "date" in data:
        day = _date(data.get("date"))
        if not day:
            return _bad("date must be YYYY-MM-DD.")
        if day < athlete.local_today:
            return _bad("A session cannot be moved into the past.")
        session.date = day
        fields.append("date")
    if fields:
        from django.db import transaction

        with transaction.atomic():
            session.save(update_fields=fields)
            if session.garmin_workout_id:
                action = "send" if session.status == StrengthSession.Status.PLANNED else "delete"
                _queue(garmin_strength_push_task, athlete.pk, [session.pk], action)
    return Response(strength_json(session))


@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
def strength_garmin(request, pk: int):
    from django.db import transaction

    from .garmin_sync import _queue
    from .strength_service import can_send
    from .tasks import garmin_strength_push_task

    athlete = request.user.athlete
    session = StrengthSession.objects.filter(athlete=athlete, pk=pk).first()
    if session is None:
        return _bad("Not found.", status.HTTP_404_NOT_FOUND)
    if request.method == "POST":
        if not can_send(athlete):
            return _bad("Connect Garmin first to send sessions to your watch.",
                        status.HTTP_409_CONFLICT)
        if session.status != StrengthSession.Status.PLANNED or session.date < athlete.local_today:
            return _bad("Only planned sessions from today on can go to the watch.",
                        status.HTTP_409_CONFLICT)
        action = "send"
    else:
        action = "delete"
    with transaction.atomic():
        _queue(garmin_strength_push_task, athlete.pk, [session.pk], action)
    return Response({"queued": True}, status=status.HTTP_202_ACCEPTED)
