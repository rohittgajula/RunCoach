"""R7 §1 endpoints: GET /today/, POST /today/apply/, POST /today/explain/."""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.coaching.throttles import ChatThrottle

from .checkin_services import NothingToApply, apply_today, explain_today, today_payload


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def today(request):
    return Response(today_payload(request.user.athlete))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def today_apply(request):
    athlete = request.user.athlete
    try:
        apply_today(athlete)
    except NothingToApply as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response(today_payload(athlete))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def comeback(request):
    """GET /today/comeback/ -> the gap, the first run back, and this week.

    Separate from the check-in rather than folded into it. The check-in answers
    "train or rest today" from last night's signals; this answers "are you
    still running at all", which is a different question on a different clock
    and should not disappear because last night's sleep was fine.
    """
    from .comeback_service import card_for

    return Response(card_for(request.user.athlete))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def comeback_answer(request):
    """POST /today/comeback/ {"key": "hurt"|"much"|"life"|"restart"}."""
    from .comeback_service import answer

    try:
        return Response(answer(request.user.athlete, str(request.data.get("key") or "")))
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatThrottle])
def today_explain(request):
    from apps.coaching.client import AIUnavailable

    try:
        return Response(explain_today(request.user.athlete))
    except AIUnavailable as exc:
        return Response({"detail": str(exc) or "The coach is unavailable right now."},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)
