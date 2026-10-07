"""R11 §D: the hydration log. The target is Diet's existing daily water target
including the hot-weather bonus (diet.services)."""

from __future__ import annotations

import datetime as dt

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import WaterLog

QUICK_ADD = [250, 500]
MIN_ML, MAX_ML = 50, 2000
MAX_FUTURE = dt.timedelta(minutes=5)
MAX_PAST = dt.timedelta(days=7)


def log_json(log: WaterLog) -> dict:
    return {"id": log.pk, "at": log.at, "local_date": log.local_date, "ml": log.ml}


def water_target(athlete, day: dt.date) -> tuple[int, int]:
    """(target incl. bonus, bonus) — the same numbers /diet/day/ shows."""
    from apps.ingest.weather_services import water_bonus_ml

    from .services import _DayData, profile_for

    targets = _DayData(athlete, day, day).targets(day, profile_for(athlete))
    bonus, _ = water_bonus_ml(athlete, day)
    return int(targets.water_ml + bonus), int(bonus)


def water_day(athlete, day: dt.date, target: tuple[int, int] | None = None) -> dict:
    target_ml, bonus = target if target is not None else water_target(athlete, day)
    logs = list(WaterLog.objects.filter(athlete=athlete, local_date=day))
    drunk = sum(log.ml for log in logs)
    return {"date": day, "target_ml": target_ml, "bonus_ml": bonus, "drunk_ml": drunk,
            "remaining_ml": max(0, target_ml - drunk),
            "pct": min(100, round(drunk / target_ml * 100)) if target_ml else 0,
            "quick_add": QUICK_ADD, "logs": [log_json(log) for log in logs]}


def local_date_of(athlete, moment: dt.datetime) -> dt.date:
    from apps.health.common import zone_of

    return moment.astimezone(zone_of(athlete)).date()


def _bad(message: str) -> Response:
    return Response({"detail": message}, status=400)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def water(request):
    athlete = request.user.athlete
    if request.method == "GET":
        raw = request.query_params.get("date")
        try:
            day = dt.date.fromisoformat(raw) if raw else athlete.local_today
        except ValueError:
            return _bad("date must be YYYY-MM-DD.")
        return Response(water_day(athlete, day))

    ml = request.data.get("ml")
    if isinstance(ml, bool) or not isinstance(ml, (int, float, str)):
        return _bad(f"ml must be a whole number from {MIN_ML} to {MAX_ML}.")
    try:
        ml_value = float(ml)
    except ValueError:
        return _bad(f"ml must be a whole number from {MIN_ML} to {MAX_ML}.")
    if ml_value != int(ml_value) or not MIN_ML <= ml_value <= MAX_ML:
        return _bad(f"ml must be a whole number from {MIN_ML} to {MAX_ML}.")
    now = timezone.now()
    at = now
    if request.data.get("at"):
        from django.utils.dateparse import parse_datetime

        at = parse_datetime(str(request.data["at"]))
        if at is None:
            return _bad("at must be an ISO 8601 datetime.")
        if timezone.is_naive(at):
            from apps.health.common import zone_of

            at = at.replace(tzinfo=zone_of(athlete))
        if at > now + MAX_FUTURE:
            return _bad("at can't be in the future.")
        if at < now - MAX_PAST:
            return _bad("at must be within the last 7 days.")
    log = WaterLog.objects.create(athlete=athlete, at=at, local_date=local_date_of(athlete, at),
                                  ml=int(ml_value))
    return Response({"log": log_json(log), "day": water_day(athlete, log.local_date)}, status=201)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def water_delete(request, pk: int):
    athlete = request.user.athlete
    log = WaterLog.objects.filter(athlete=athlete, pk=pk).first()
    if log is None:
        return Response({"detail": "Not found."}, status=404)
    day = log.local_date
    log.delete()
    return Response(water_day(athlete, day))
