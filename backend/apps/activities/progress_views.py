"""Progress endpoints (R8 §C; R9 §D custom dates)."""

from __future__ import annotations

import datetime as dt

from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis.progress import WINDOWS
from apps.coaching.client import AIUnavailable
from apps.coaching.throttles import ChatThrottle

from .progress import MAX_RANGE_DAYS, DateRange, progress_payload, review_key

DATE_PARAMS = ("start", "end", "compare_start", "compare_end")


class BadParams(Exception):
    pass


def _window(request):
    try:
        value = int(request.query_params.get("window") or 5)
    except ValueError:
        return None
    return value if value in WINDOWS else None


def _sport(request):
    sport = (request.query_params.get("sport") or "running").lower()
    return sport if sport in ("running", "walking") else None


def _day(request, name: str) -> dt.date | None:
    value = request.query_params.get(name)
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise BadParams(f"{name} must be a date (YYYY-MM-DD).") from exc


def _range_days(first: dt.date, last: dt.date) -> int:
    return (last - first).days + 1


def _dates(request) -> DateRange | None:
    """None in window mode. Raises BadParams with a readable message."""
    given = [p for p in DATE_PARAMS if request.query_params.get(p)]
    if not given:
        return None
    if request.query_params.get("window"):
        raise BadParams("Use either window or start/end dates, not both.")
    start, end = _day(request, "start"), _day(request, "end")
    if start is None or end is None:
        raise BadParams("start and end are both required for a date range.")
    if start > end:
        raise BadParams("start must be on or before end.")
    if _range_days(start, end) > MAX_RANGE_DAYS:
        raise BadParams(f"A date range can be at most {MAX_RANGE_DAYS} days.")
    cs, ce = _day(request, "compare_start"), _day(request, "compare_end")
    if (cs is None) != (ce is None):
        raise BadParams("compare_start and compare_end go together.")
    if cs is not None:
        if cs > ce:
            raise BadParams("compare_start must be on or before compare_end.")
        if _range_days(cs, ce) > MAX_RANGE_DAYS:
            raise BadParams(f"A compare range can be at most {MAX_RANGE_DAYS} days.")
    return DateRange.build(start, end, cs, ce)


def _params(request, need_sport: bool = True):
    """(window, dates, sport) or a 400 Response."""
    try:
        dates = _dates(request)
    except BadParams as exc:
        return Response({"detail": str(exc)}, status=400)
    sport = _sport(request)
    window = None if dates is not None else _window(request)
    if dates is None and window is None:
        return Response({"detail": "window must be 1, 5, 10 or 20 (or give start and end "
                                   "dates)."}, status=400)
    if need_sport and sport is None:
        return Response({"detail": "sport must be running or walking."}, status=400)
    return window, dates, sport


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def progress(request):
    parsed = _params(request)
    if isinstance(parsed, Response):
        return parsed
    window, dates, sport = parsed
    return Response(progress_payload(request.user.athlete, window, sport, dates=dates))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatThrottle])
def progress_review(request):
    from .progress_ai import generate_review

    parsed = _params(request, need_sport=False)
    if isinstance(parsed, Response):
        return parsed
    window, dates, _ = parsed
    athlete = request.user.athlete
    body = progress_payload(athlete, window, dates=dates)
    if not body["current_n"]:
        return Response({"detail": "No runs to review yet."}, status=409)
    try:
        review = generate_review(athlete, body, key=review_key(window, dates),
                                 refresh=request.query_params.get("refresh") == "1")
    except AIUnavailable as exc:
        return Response({"detail": str(exc) or "The coach is unavailable right now."},
                        status=503)
    return Response(review)
