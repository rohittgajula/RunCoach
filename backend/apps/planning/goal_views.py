"""A distance by a date, in either of the two senses people mean by it.

This mode existed before this module and could only be reached by talking to
the coach, which is where it went wrong for Rohit. He asked for "5k between
march and april with breaks"; the chat path would have planned for running
5 km *without stopping*, told him his date was impossible, and been right about
a question he had not asked. Covering a distance with walk breaks and running
it unbroken are different goals whose honest dates can be a year apart.

Two endpoints, and the first one is the point:

**Preview before you commit.** The whole value of this mode is its refusal — it
is the only planner here that will tell you a date does not work. A refusal you
only discover after a plan has been written, named and proposed is a refusal
delivered too late to be useful. `preview` answers the question without
creating anything, so the two styles can be compared side by side and the date
chosen against a real answer rather than a hope.

**Then build it.** `create` writes the proposal. It is still a proposal: as
everywhere else here, nothing enters the calendar until it is accepted.
"""

from __future__ import annotations

import datetime as dt

from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .plan_store import PlanError, propose_goal_plan
from .presenters import plan_summary

#: Both readings, offered together. The UI shows them as a pair because the
#: choice is the whole decision — naming one without the other beside it is how
#: somebody ends up training for the wrong goal without ever being asked.
STYLES = ("run_walk", "nonstop")


class GoalSerializer(serializers.Serializer):
    target_distance_km = serializers.FloatField(min_value=0.4, max_value=100)
    target_date = serializers.DateField()
    style = serializers.ChoiceField(choices=STYLES)
    available_days = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6),
        required=False, allow_null=True,
    )
    long_run_day = serializers.IntegerField(min_value=0, max_value=6, required=False,
                                            allow_null=True)


def _verdict_json(verdict) -> dict:
    """The answer, with each style's numbers under its own names.

    The unused style's fields are omitted rather than sent as zero. They are
    measured in different units — seconds of unbroken running against metres
    covered in a session — and a zero in the wrong unit is exactly the kind of
    plausible-looking number that gets read by mistake.
    """
    common = {
        "style": verdict.style,
        "governs": verdict.governs,
        "label": verdict.label,
        "target_distance_km": verdict.target_distance_km,
        "target_date": verdict.target_date.isoformat(),
        "achievable": verdict.achievable,
        "weeks_available": verdict.weeks_available,
        "weeks_needed": verdict.weeks_needed,
        "earliest_date": (
            verdict.earliest_date.isoformat() if verdict.earliest_date else None
        ),
    }
    if verdict.style == "run_walk":
        return {
            **common,
            "needs_covered_m": round(verdict.needs_m),
            "reaches_covered_m": round(verdict.reaches_m),
            "session_s": verdict.session_s,
            "blended_pace_s_per_km": round(verdict.blended_pace_s_per_km),
        }
    return {
        **common,
        "needs_continuous_s": verdict.needs_s,
        "reaches_continuous_s": verdict.reaches_s,
    }


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def goal_preview(request):
    """POST /plans/goal/preview/ -> the verdict for BOTH styles, nothing saved.

    Both, always, whichever one was asked about. The useful thing to know about
    "5 km by March" is that one reading of it is comfortable and the other is
    two years away, and you cannot learn that from the reading you happened to
    pick first.
    """
    from planning.practice import assess_goal

    from .plan_services import config_from_settings
    from .plan_store import practice_baseline

    form = GoalSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    data = form.validated_data

    athlete = request.user.athlete
    start = athlete.local_today + dt.timedelta(days=1)
    if data["target_date"] <= start:
        return Response({"detail": "Pick a date at least two days away."}, status=400)

    baseline = practice_baseline(
        athlete, data.get("available_days"), data.get("long_run_day"),
    )
    config = config_from_settings()
    verdicts = {
        style: assess_goal(
            start, data["target_date"], float(data["target_distance_km"]),
            baseline, config, style=style,
        )
        for style in STYLES
    }
    return Response({
        "asked": data["style"],
        "plan_start": start.isoformat(),
        "styles": {style: _verdict_json(v) for style, v in verdicts.items()},
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def goal_create(request):
    """POST /plans/goal/ -> a PROPOSED plan toward that distance by that date."""
    form = GoalSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    data = form.validated_data
    athlete = request.user.athlete

    try:
        plan = propose_goal_plan(
            athlete,
            target_distance_km=float(data["target_distance_km"]),
            target_date=data["target_date"],
            style=data["style"],
            available_days=data.get("available_days"),
            long_run_day=data.get("long_run_day"),
        )
    except PlanError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

    # A summary rather than the full detail: the screen that asked for this
    # hands it straight to the same proposal card the coach uses, so there is
    # one accept/decline control in the app instead of two that can drift.
    return Response(plan_summary(plan, athlete.local_today),
                    status=status.HTTP_201_CREATED)
