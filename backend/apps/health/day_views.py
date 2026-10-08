"""R11 §B/§F: the Day section — one day's timeline and cards, Today's compact row and
the daytime trends. Deterministic; never sent to the AI."""

from __future__ import annotations

import datetime as dt

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .common import BadRequest
from .day_service import day_json, summary_json, trends_json
from .period import parse_period

MAX_DAYS_BACK = 365


def parse_day(request, athlete) -> dt.date:
    raw = request.query_params.get("date")
    today = athlete.local_today
    if not raw:
        return today
    try:
        day = dt.date.fromisoformat(raw)
    except ValueError as exc:
        raise BadRequest("date must be a date (YYYY-MM-DD).") from exc
    if day > today:
        raise BadRequest("date can't be in the future.")
    if (today - day).days > MAX_DAYS_BACK:
        raise BadRequest("date must be within the last 365 days.")
    return day


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def day(request):
    athlete = request.user.athlete
    return Response(day_json(athlete, parse_day(request, athlete)))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def day_summary(request):
    from .freshness import freshness_json

    athlete = request.user.athlete
    fresh = freshness_json(athlete)
    from apps.athletes.versioning import cached

    body = cached(athlete, "day_summary", lambda: summary_json(athlete))   # R18
    return Response({**body, "as_of": fresh["as_of"], "freshness": fresh})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def day_trends(request):
    athlete = request.user.athlete
    return Response(trends_json(athlete, parse_period(request, athlete, "4w")))
