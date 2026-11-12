"""Clearing planning data, so a plan can be started over.

Plans here are **rows**, not a projection regenerated on every read, which is what
makes them editable — and also what makes a wrong one stick. Changing your mind
about the whole shape of your training had no answer short of editing workouts one
at a time, and that is not a thing anybody does for sixteen weeks of them.

Three rules shape this module.

**Nothing is one button.** Clearing an unaccepted proposal is something you might do
weekly; deleting every run you have ever recorded is not, and the two must not sit
one click apart. Each target is opted into separately, and the destructive ones ask
for more than a tick.

**What happened is not planning data.** Activities, journal entries, check-ins and
wellness are the record of your life, not of a plan, and no amount of replanning is
a reason to forget them. Clearing activities is possible because the athlete may
genuinely want it, but it is the only target that warns it cannot be undone from
inside this app — Garmin can re-sync them, and nothing else here can.

**A watch is not a database.** Workouts pushed to Garmin exist on Garmin too, so
deleting the rows silently leaves them on the watch, scheduled, for weeks. Their
Garmin ids are captured before the rows go and the removal is queued to run after
this transaction commits — the other order either loses the ids or, on a rollback,
strips a watch of workouts the app still believes it has.
"""

from __future__ import annotations

import logging

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.activities.models import Activity

from .models import (
    PlanAdjustment, PlannedWorkout, Race, StrengthSession, TrainingPlan,
    WorkoutAdjustment,
)

logger = logging.getLogger(__name__)


class ResetSerializer(serializers.Serializer):
    """Every target is opt-in. Defaults clear nothing."""

    # The active plan's future: what you reset to re-plan from today.
    upcoming = serializers.BooleanField(default=False)
    # Every plan, including completed ones and unaccepted proposals.
    plans = serializers.BooleanField(default=False)
    # One specific plan, by id. Takes precedence over `plans`.
    plan_id = serializers.IntegerField(required=False, allow_null=True)
    strength = serializers.BooleanField(default=False)
    adjustments = serializers.BooleanField(default=False)
    races = serializers.BooleanField(default=False)
    # The only target that destroys a record of something that actually happened.
    activities = serializers.BooleanField(default=False)

    confirm = serializers.CharField()

    def validate_confirm(self, value):
        if value.strip().upper() != "CLEAR":
            raise serializers.ValidationError("Type CLEAR to confirm.")
        return value

    def validate(self, attrs):
        if not any(
            attrs.get(key)
            for key in ("upcoming", "plans", "strength", "adjustments", "races", "activities")
        ) and not attrs.get("plan_id"):
            raise serializers.ValidationError("Nothing selected to clear.")
        return attrs


def _forget_on_watch(athlete, workouts, sessions) -> int:
    """Take anything already on the watch off it. Returns how many were queued.

    Reuses `garmin_sync.forget_on_garmin`, which captures the Garmin ids *before*
    the rows are deleted and runs the removal after this transaction commits. That
    ordering is the whole difficulty: delete the rows first and the ids are gone,
    call Garmin first and a rolled-back transaction leaves a watch stripped of
    workouts the app still thinks it has.
    """
    from .garmin_sync import forget_on_garmin

    return forget_on_garmin(athlete, [*workouts, *sessions])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def reset(request):
    """Clear the selected planning data. See the module docstring for the rules."""
    form = ResetSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    data = form.validated_data
    athlete = request.user.athlete
    today = athlete.local_today
    cleared: dict[str, int] = {}

    workouts = PlannedWorkout.objects.filter(athlete=athlete)
    sessions = StrengthSession.objects.filter(athlete=athlete)

    if data.get("plan_id"):
        plan = TrainingPlan.objects.filter(athlete=athlete, pk=data["plan_id"]).first()
        if plan is None:
            return Response({"detail": "No such plan."}, status=status.HTTP_404_NOT_FOUND)
        doomed_w = list(workouts.filter(plan=plan))
        doomed_s = list(sessions.filter(plan=plan))
        cleared["removed_from_watch"] = _forget_on_watch(athlete, doomed_w, doomed_s)
        cleared["workouts"] = workouts.filter(plan=plan).delete()[0]
        cleared["strength"] = sessions.filter(plan=plan).delete()[0]
        cleared["plans"] = TrainingPlan.objects.filter(pk=plan.pk).delete()[0]

    elif data["plans"]:
        doomed_w = list(workouts)
        doomed_s = list(sessions)
        cleared["removed_from_watch"] = _forget_on_watch(athlete, doomed_w, doomed_s)
        cleared["workouts"] = workouts.delete()[0]
        cleared["strength"] = sessions.delete()[0]
        cleared["plans"] = TrainingPlan.objects.filter(athlete=athlete).delete()[0]

    elif data["upcoming"]:
        # Today included: a session not yet done is still ahead of you. Yesterday's
        # is history, and deleting history would quietly change the baseline every
        # future plan is built from.
        future_w = workouts.filter(date__gte=today)
        future_s = sessions.filter(date__gte=today)
        cleared["removed_from_watch"] = _forget_on_watch(
            athlete, list(future_w), list(future_s)
        )
        cleared["workouts"] = future_w.delete()[0]
        cleared["strength"] = future_s.delete()[0]

    if data["strength"] and "strength" not in cleared:
        future_s = sessions.filter(date__gte=today)
        cleared["removed_from_watch"] = cleared.get("removed_from_watch", 0) + _forget_on_watch(
            athlete, [], list(future_s)
        )
        cleared["strength"] = future_s.delete()[0]

    if data["adjustments"]:
        cleared["adjustments"] = (
            PlanAdjustment.objects.filter(athlete=athlete).delete()[0]
            + WorkoutAdjustment.objects.filter(athlete=athlete).delete()[0]
        )

    if data["races"]:
        cleared["races"] = Race.objects.filter(athlete=athlete).delete()[0]

    if data["activities"]:
        # The one irreversible target. Garmin can re-sync what it still holds;
        # nothing in this app can bring back what Garmin has forgotten.
        cleared["activities"] = Activity.objects.filter(athlete=athlete).delete()[0]

    logger.info("athlete %s cleared planning data: %s", athlete.pk, cleared)
    return Response({"cleared": cleared})
