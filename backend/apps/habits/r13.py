"""R13 §8 cravings + savings goal, §9 caffeine report. Own rows only; never to the AI."""

from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import caffeine as caffeine_maths
from analysis import cravings as maths

from .models import CravingLog, HabitLog
from .services import CAFFEINE

MAX_DAYS = 730


def craving_json(c: CravingLog) -> dict:
    return {"id": c.pk, "at": c.at, "local_date": c.local_date, "intensity": c.intensity,
            "trigger": c.trigger, "place": c.place, "mood": c.mood, "smoked": c.smoked,
            "cigarette_log_id": c.cigarette_log_id, "note": c.note, "created_at": c.created_at}


class CravingInput(serializers.Serializer):
    at = serializers.DateTimeField(required=False)
    intensity = serializers.IntegerField(min_value=1, max_value=5)
    trigger = serializers.ChoiceField(choices=CravingLog.Trigger.choices)
    place = serializers.CharField(max_length=60, required=False, allow_blank=True)
    mood = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)
    smoked = serializers.BooleanField(required=False)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_at(self, value):
        if value > timezone.now() + dt.timedelta(minutes=5):
            raise serializers.ValidationError("Can't log a craving in the future.")
        return value


def _link_cigarette(craving: CravingLog) -> None:
    """smoked -> one cigarette logged at the craving's time (once); not smoked -> the
    linked cigarette removed."""
    if craving.smoked and craving.cigarette_log_id is None:
        craving.cigarette_log = HabitLog.objects.create(
            athlete=craving.athlete, kind="smoke", quantity=1.0, at=craving.at,
            note="from a craving")
    elif not craving.smoked and craving.cigarette_log_id is not None:
        HabitLog.objects.filter(pk=craving.cigarette_log_id, athlete=craving.athlete).delete()
        craving.cigarette_log = None


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def cravings(request):
    athlete = request.user.athlete
    if request.method == "GET":
        try:
            days = int(request.query_params.get("days", "90"))
        except ValueError:
            days = 0
        if not 1 <= days <= MAX_DAYS:
            return Response({"detail": "days must be a whole number 1–730."}, status=400)
        since = athlete.local_today - dt.timedelta(days=days - 1)
        rows = CravingLog.objects.filter(athlete=athlete, local_date__gte=since)
        return Response([craving_json(c) for c in rows])
    data = CravingInput(data=request.data)
    data.is_valid(raise_exception=True)
    v = data.validated_data
    with transaction.atomic():
        craving = CravingLog(athlete=athlete, at=v.get("at") or timezone.now(),
                             intensity=v["intensity"], trigger=v["trigger"],
                             place=(v.get("place") or "").strip(), mood=v.get("mood"),
                             smoked=v.get("smoked", False), note=(v.get("note") or "").strip())
        _link_cigarette(craving)
        craving.save()
    return Response(craving_json(craving), status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def craving_detail(request, pk: int):
    craving = get_object_or_404(CravingLog, pk=pk, athlete=request.user.athlete)
    if request.method == "DELETE":
        craving.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    current = {"intensity": craving.intensity, "trigger": craving.trigger}
    data = CravingInput(data={**current, **request.data}, partial=True)
    data.is_valid(raise_exception=True)
    with transaction.atomic():
        for key, value in data.validated_data.items():
            if key in ("place", "note"):
                value = (value or "").strip()
            setattr(craving, key, value)
        _link_cigarette(craving)
        if craving.cigarette_log_id and "at" in data.validated_data:
            HabitLog.objects.filter(pk=craving.cigarette_log_id).update(at=craving.at)
        craving.save()
    return Response(craving_json(craving))


def savings_for(athlete) -> dict | None:
    from analysis import habits as habit_maths

    from .services import _totals

    smoked_since = 0.0
    if athlete.smoke_quit_date:
        totals = _totals(athlete, "smoke", athlete.smoke_quit_date)
        smoked_since = sum(totals.values())
    since = habit_maths.since_quit(athlete.smoke_quit_date, athlete.local_today,
                                   athlete.smoke_baseline_per_day, athlete.cigarette_price,
                                   smoked_since)
    return maths.savings(athlete.savings_goal_name, athlete.savings_goal_amount,
                         since["money_saved"] if since else None,
                         since["days"] if since else None, athlete.local_today)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def craving_summary(request):
    from apps.health.period import parse_period

    athlete = request.user.athlete
    period = parse_period(request, athlete, "4w")
    rows = CravingLog.objects.filter(athlete=athlete, local_date__gte=period.compare_start,
                                     local_date__lte=period.end)
    data = [maths.Craving(r.local_date, r.local_hour, r.intensity, r.trigger, r.place, r.smoked)
            for r in rows]
    body = maths.summary(data, period.start, period.end, period.compare_start,
                         period.compare_end)
    return Response({**period.ranged(), **body, "savings": savings_for(athlete)})


def caffeine_payload(athlete, period) -> dict:
    from apps.ingest.models import DailyMetrics

    zone = athlete.local_now.tzinfo
    logs = [(log.local_date, log.at.astimezone(zone).hour, log.quantity, log.subtype or None)
            for log in HabitLog.objects.filter(athlete=athlete, kind=CAFFEINE,
                                               local_date__lte=period.end)]
    amounts = caffeine_maths.amounts(logs, period.start, period.end)
    nights = {
        r.metric_date: {"sleep_score": r.sleep_score,
                        "deep_sleep_min": round(r.deep_sleep_seconds / 60)
                        if r.deep_sleep_seconds is not None else None,
                        "awake_min": round(r.awake_seconds / 60)
                        if r.awake_seconds is not None else None}
        for r in DailyMetrics.objects.filter(athlete=athlete,
                                             metric_date__gte=period.start,
                                             metric_date__lte=period.end + dt.timedelta(days=1))}
    return {**period.ranged(), "total": amounts["total"], "per_day_avg": amounts["per_day_avg"],
            "by_type": amounts["by_type"], "late_cutoff": f"{caffeine_maths.LATE_HOUR:02d}:00",
            "late_days": amounts["late_days"], "series": amounts["series"],
            "impact": caffeine_maths.impact(amounts["series"], nights),
            "caveat": caffeine_maths.CAVEAT}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def caffeine(request):
    from apps.health.period import parse_period

    athlete = request.user.athlete
    return Response(caffeine_payload(athlete, parse_period(request, athlete, "4w")))
