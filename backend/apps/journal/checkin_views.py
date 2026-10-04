"""R7 §2 endpoints: pending check-ins, post-run check-in, skip."""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.activities.models import Activity

from . import checkin
from .serializers import JournalEntrySerializer


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pending_checkins(request):
    from apps.planning.models import PlannedWorkout
    from apps.planning.presenters import activity_cards

    athlete = request.user.athlete
    activities = checkin.pending(athlete)
    cards = activity_cards(athlete, activities)
    linked = dict(PlannedWorkout.objects.filter(
        athlete=athlete, completed_activity_id__in=[a.pk for a in activities],
    ).values_list("completed_activity_id", "pk"))
    return Response([{"activity": card, "workout_id": linked.get(card["id"])}
                     for card in cards])


def _activity(request, pk: int) -> Activity | None:
    return Activity.objects.filter(athlete=request.user.athlete, pk=pk).first()


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def activity_checkin(request, pk: int):
    activity = _activity(request, pk)
    if activity is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    try:
        fields = checkin.validate(request.data if isinstance(request.data, dict) else {})
    except checkin.CheckinInvalid as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    entry, created = checkin.record(request.user.athlete, activity, fields)
    return Response(JournalEntrySerializer(entry).data,
                    status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def activity_checkin_skip(request, pk: int):
    activity = _activity(request, pk)
    if activity is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    reason = request.data.get("reason") if isinstance(request.data, dict) else ""
    entry, created = checkin.skip(request.user.athlete, activity, str(reason or ""))
    return Response(JournalEntrySerializer(entry).data,
                    status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
