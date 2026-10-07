"""R13 §7 endpoints: the AI paragraph on a run review, and the Today card."""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.coaching.throttles import ChatThrottle

from .models import Activity
from .reviews import generate_ai, recent


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatThrottle])
def review_ai(request, pk: int):
    from apps.coaching.client import AIUnavailable

    activity = Activity.objects.filter(athlete=request.user.athlete, pk=pk) \
        .select_related("metrics").first()
    if activity is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    try:
        return Response(generate_ai(activity, refresh=request.query_params.get("refresh") == "1"))
    except AIUnavailable as exc:
        return Response({"detail": str(exc) or "The coach is unavailable right now."},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reviews_recent(request):
    return Response({"review": recent(request.user.athlete)})
