"""Progress endpoints (R8 §C)."""

from __future__ import annotations

from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis.progress import WINDOWS
from apps.coaching.client import AIUnavailable
from apps.coaching.throttles import ChatThrottle

from .progress import progress_payload


def _window(request):
    try:
        value = int(request.query_params.get("window") or 5)
    except ValueError:
        return None
    return value if value in WINDOWS else None


def _sport(request):
    sport = (request.query_params.get("sport") or "running").lower()
    return sport if sport in ("running", "walking") else None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def progress(request):
    window, sport = _window(request), _sport(request)
    if window is None or sport is None:
        return Response({"detail": "window must be 1, 5, 10 or 20; sport running or "
                                   "walking."}, status=400)
    return Response(progress_payload(request.user.athlete, window, sport))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatThrottle])
def progress_review(request):
    from .progress_ai import generate_review

    window = _window(request)
    if window is None:
        return Response({"detail": "window must be 1, 5, 10 or 20."}, status=400)
    athlete = request.user.athlete
    body = progress_payload(athlete, window)
    if not body["current_n"]:
        return Response({"detail": "No runs to review yet."}, status=409)
    try:
        review = generate_review(athlete, body,
                                 refresh=request.query_params.get("refresh") == "1")
    except AIUnavailable as exc:
        return Response({"detail": str(exc) or "The coach is unavailable right now."},
                        status=503)
    return Response(review)
