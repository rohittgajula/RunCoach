"""R13 §10: mood & energy, one entry per day. Never to the AI except as averages."""

from __future__ import annotations

import datetime as dt

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import MoodLog

DEFAULT_DAYS = 30
MAX_DAYS = 366
BACKDATE_DAYS = 7


def mood_json(row: MoodLog) -> dict:
    return {"date": row.date, "mood": row.mood, "energy": row.energy, "note": row.note,
            "updated_at": row.updated_at}


def block(athlete, start: dt.date, end: dt.date, prev_start: dt.date, prev_end: dt.date) -> dict:
    """{mood_avg, energy_avg, days, previous_mood_avg, previous_energy_avg}."""
    from analysis.monthly_report import mood_block

    this = list(MoodLog.objects.filter(athlete=athlete, date__gte=start, date__lte=end)
                .values_list("mood", "energy"))
    before = list(MoodLog.objects.filter(athlete=athlete, date__gte=prev_start,
                                         date__lte=prev_end).values_list("mood", "energy"))
    return mood_block(this, before)


def _bad(message: str) -> Response:
    return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)


def _score(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{name} must be a whole number 1–5.")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a whole number 1–5.") from None
    if str(number) != str(value).strip() or not 1 <= number <= 5:
        raise ValueError(f"{name} must be a whole number 1–5.")
    return number


def _parse_date(raw):
    try:
        return dt.date.fromisoformat(str(raw))
    except ValueError:
        return None


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def moods(request):
    athlete = request.user.athlete
    today = athlete.local_today
    if request.method == "GET":
        start_raw, end_raw = request.query_params.get("start"), request.query_params.get("end")
        end = _parse_date(end_raw) if end_raw else today
        start = _parse_date(start_raw) if start_raw else (end or today) - dt.timedelta(
            days=DEFAULT_DAYS - 1)
        if start is None or end is None:
            return _bad("Dates must be YYYY-MM-DD.")
        if start > end:
            return _bad("start must not be after end.")
        if (end - start).days + 1 > MAX_DAYS:
            return _bad(f"At most {MAX_DAYS} days per request.")
        rows = MoodLog.objects.filter(athlete=athlete, date__gte=start, date__lte=end)
        return Response([mood_json(r) for r in rows])
    data = request.data if isinstance(request.data, dict) else {}
    try:
        mood = _score(data.get("mood"), "mood")
        energy = _score(data.get("energy"), "energy")
    except ValueError as exc:
        return _bad(str(exc))
    day = today
    if data.get("date"):
        day = _parse_date(data["date"])
        if day is None:
            return _bad("date must be YYYY-MM-DD.")
        if day > today or day < today - dt.timedelta(days=BACKDATE_DAYS):
            return _bad("date must be within the last 7 days.")
    note = str(data.get("note") or "").strip()
    if len(note) > 200:
        return _bad("note must be under 200 characters.")
    row, created = MoodLog.objects.update_or_create(
        athlete=athlete, date=day, defaults={"mood": mood, "energy": energy, "note": note})
    return Response(mood_json(row), status=status.HTTP_201_CREATED if created else 200)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mood_today(request):
    athlete = request.user.athlete
    row = MoodLog.objects.filter(athlete=athlete, date=athlete.local_today).first()
    return Response({"date": athlete.local_today, "entry": mood_json(row) if row else None})


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def mood_delete(request, day: str):
    parsed = _parse_date(day)
    if parsed is None:
        return _bad("date must be YYYY-MM-DD.")
    deleted, _ = MoodLog.objects.filter(athlete=request.user.athlete, date=parsed).delete()
    if not deleted:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(status=status.HTTP_204_NO_CONTENT)
