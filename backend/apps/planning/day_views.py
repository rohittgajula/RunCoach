"""R20: adding your own session to a day.

The calendar could be read in both directions and written in only one: the
coach placed days, and the athlete could move, edit or skip what it placed —
but not add. A rest day was a day with nothing to tap, which is the wrong shape
for somebody whose training is their own.

Three endpoints, and the first two are a pair:

**`GET  /days/{date}/`** — what this day could take. The presets, whether a run
or a gym session is already there, and whether the day is even writable. The
screen asks before it offers, rather than offering and then failing.

**`POST /days/{date}/preview/`** — build the session and return it WITHOUT
saving. A described session ("easy run in zone 2 for 30 min, run/walk") is a
guess at what the athlete meant, and they should read it before it is on their
watch. The preview carries the model's own line about what it understood.

**`POST /days/{date}/`** — save it.

The service is apps/planning/day_session.py; the step validation is
planning/edit.py, the same one the manual editor uses.
"""

from __future__ import annotations

import datetime as dt

from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.coaching.client import AIUnavailable
from apps.coaching.throttles import ChatWriteThrottle

from . import day_session as service
from .models import PlannedWorkout, StrengthSession
from .presenters import workout_json

DESCRIPTION_MAX = 500


def _day(raw: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


class ChangeSerializer(serializers.Serializer):
    """One approved change to one other day.

    The client sends back the proposal it was shown rather than a free-form
    instruction, and the service re-checks every field against the athlete's
    own rows before acting. A change is only ever as trustworthy as the
    workout it names still being there.
    """

    workout_id = serializers.IntegerField()
    action = serializers.ChoiceField(choices=service.CHANGE_ACTIONS)
    minutes = serializers.IntegerField(required=False, allow_null=True)
    move_to = serializers.DateField(required=False, allow_null=True)


class SessionSerializer(serializers.Serializer):
    """Either a preset run, a described run, or a gym session."""

    type = serializers.ChoiceField(choices=("run", "gym"))
    # Preset path.
    preset = serializers.ChoiceField(choices=tuple(service.PRESETS), required=False)
    minutes = serializers.IntegerField(
        min_value=service.MIN_MINUTES, max_value=service.MAX_MINUTES, required=False,
    )
    # Described path.
    description = serializers.CharField(max_length=DESCRIPTION_MAX, required=False,
                                        allow_blank=False, trim_whitespace=True)
    # The changes to OTHER days that the athlete said yes to, each one ticked
    # on its own. Absent means none, which is the safe reading: a request that
    # forgot to send them must not silently rewrite the week.
    approved_changes = ChangeSerializer(many=True, required=False)

    def validate(self, attrs):
        if attrs["type"] == "gym":
            return attrs
        if attrs.get("description"):
            return attrs
        if not attrs.get("preset") or not attrs.get("minutes"):
            raise serializers.ValidationError(
                "Give a description, or a preset and a length."
            )
        return attrs


def _build(athlete, day: dt.date, data: dict) -> tuple[dict, str, str, list[dict]]:
    """(session, kind, note, proposed changes). Raises DayError / AIUnavailable."""
    if data["type"] == "gym":
        return service.build_gym(athlete, day), "gym", "", []
    if data.get("description"):
        session, note, changes = service.build_described(athlete, data["description"], day)
        return session, "run", note, changes
    # A preset is the athlete's own explicit choice of shape and length, so it
    # is built as asked. Only the described path reads the week, because only
    # it is being asked to decide anything.
    return service.build_preset(athlete, data["preset"], data["minutes"]), "run", "", []


def _preview_json(session: dict, kind: str, note: str, changes: list[dict]) -> dict:
    return {"type": kind, "understood": note, "session": session, "changes": changes}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def day_options(request, date: str):
    """GET /days/{date}/ -> what this day can take."""
    athlete = request.user.athlete
    day = _day(date)
    if day is None:
        return Response({"detail": "Date must be YYYY-MM-DD."}, status=400)

    writable = day >= athlete.local_today
    return Response({
        "date": day.isoformat(),
        # A past day is the record of what happened. Writing a plan onto it
        # would put a session the athlete never did into the history every
        # future plan is built from.
        "writable": writable,
        "reason": None if writable else "That day has already been.",
        "has_run": PlannedWorkout.objects.filter(
            athlete=athlete, date=day,
        ).exclude(status=PlannedWorkout.Status.SKIPPED).exists(),
        "has_gym": StrengthSession.objects.filter(
            athlete=athlete, date=day,
        ).exclude(status=StrengthSession.Status.SKIPPED).exists(),
        "presets": [{"key": key, "label": spec["label"]}
                    for key, spec in service.PRESETS.items()],
        "min_minutes": service.MIN_MINUTES,
        "max_minutes": service.MAX_MINUTES,
        "description_max": DESCRIPTION_MAX,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatWriteThrottle])
def day_preview(request, date: str):
    """POST /days/{date}/preview/ -> the session, unsaved.

    Throttled like any other write that can call a model: the described path
    costs money per press, and a preview button is pressed far more often than
    a save button.
    """
    athlete = request.user.athlete
    day = _day(date)
    if day is None:
        return Response({"detail": "Date must be YYYY-MM-DD."}, status=400)

    form = SessionSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    try:
        session, kind, note, changes = _build(athlete, day, form.validated_data)
    except service.DayError as exc:
        return Response({"detail": str(exc)}, status=400)
    except AIUnavailable as exc:
        # The preset path still works, and saying so is more use than "the
        # coach is unavailable" on its own.
        return Response(
            {"detail": f"{exc} You can still pick a shape and a length."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response(_preview_json(session, kind, note, changes))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatWriteThrottle])
def day_create(request, date: str):
    """POST /days/{date}/ -> save the session on that day."""
    athlete = request.user.athlete
    day = _day(date)
    if day is None:
        return Response({"detail": "Date must be YYYY-MM-DD."}, status=400)

    form = SessionSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    try:
        session, kind, note, changes = _build(athlete, day, form.validated_data)
        if kind == "gym":
            row = service.save_gym(athlete, day, session)
        else:
            row = service.save_run(athlete, day, session)
        # Only the changes the athlete ticked. An unanswered proposal changes
        # nothing, which is the whole point of showing them one per day: a list
        # accepted wholesale is not consent to the item in the middle of it.
        applied = [
            service.apply_change(athlete, {
                **c,
                # The serializer parses it to a date; the service re-parses
                # from ISO so that it validates the same way whichever path
                # reached it.
                "move_to": c["move_to"].isoformat() if c.get("move_to") else None,
            })
            for c in form.validated_data.get("approved_changes") or []
        ]
    except service.DayError as exc:
        return Response({"detail": str(exc)}, status=400)
    except AIUnavailable as exc:
        return Response({"detail": str(exc)},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)

    if kind == "gym":
        from .strength_service import can_send, strength_json

        body = strength_json(row, can_send(athlete))
    else:
        body = workout_json(row)
    return Response({"type": kind, "understood": note, "created": body,
                     "applied_changes": applied},
                    status=status.HTTP_201_CREATED)
