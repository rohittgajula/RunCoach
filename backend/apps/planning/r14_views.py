"""R14 endpoints in the planning app: weather-smart reschedule suggestions (§3)."""

from __future__ import annotations

import datetime as dt

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import weather_swap
from .models import WeatherSuggestion


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def weather_suggestions(request):
    athlete = request.user.athlete
    which = request.query_params.get("status") or "pending"
    if which not in ("pending", "all"):
        return Response({"detail": "status must be pending or all."}, status=400)
    weather_swap.expire_stale(athlete, athlete.local_today)
    rows = WeatherSuggestion.objects.filter(athlete=athlete).select_related("swap_workout")
    if which == "pending":
        rows = rows.filter(status=WeatherSuggestion.Status.PENDING)
    else:
        since = athlete.local_today - dt.timedelta(days=30)
        rows = rows.filter(from_date__gte=since)
    return Response({"auto_apply": athlete.weather_auto_apply,
                     "suggestions": [weather_swap.suggestion_json(s) for s in rows]})


def _suggestion(request, pk):
    return (WeatherSuggestion.objects.filter(athlete=request.user.athlete, pk=pk)
            .select_related("workout", "swap_workout").first())


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def weather_suggestion_apply(request, pk: int):
    s = _suggestion(request, pk)
    if s is None:
        return Response({"detail": "Not found."}, status=404)
    try:
        s = weather_swap.apply(request.user.athlete, s)
    except weather_swap.NotApplicable as exc:
        return Response({"detail": str(exc)}, status=409)
    return Response(weather_swap.suggestion_json(_suggestion(request, s.pk)))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def weather_suggestion_dismiss(request, pk: int):
    s = _suggestion(request, pk)
    if s is None:
        return Response({"detail": "Not found."}, status=404)
    try:
        s = weather_swap.dismiss(request.user.athlete, s)
    except weather_swap.NotApplicable as exc:
        return Response({"detail": str(exc)}, status=409)
    return Response(weather_swap.suggestion_json(s))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def weather_suggestion_check(request):
    athlete = request.user.athlete
    created = weather_swap.check(athlete)
    return Response({"created": len(created),
                     "suggestions": [weather_swap.suggestion_json(s)
                                     for s in weather_swap.pending(athlete)]})
