"""Habit endpoints (R8 §B). Every query is scoped to the requesting athlete."""

from __future__ import annotations

import datetime as dt

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.coaching.client import AIUnavailable
from apps.coaching.throttles import ChatThrottle

from . import services
from .models import HabitLog

MAX_QUANTITY = 100


class LogSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=HabitLog.Kind.choices)
    quantity = serializers.FloatField(default=1.0, min_value=0.1, max_value=MAX_QUANTITY)
    at = serializers.DateTimeField(required=False)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_kind(self, value):
        athlete = self.context.get("athlete")
        if value == services.PRIVATE and not (athlete and athlete.private_habit_enabled):
            raise serializers.ValidationError("Turn on the Private habit in Settings first.")
        return value

    def validate_at(self, value):
        if value > timezone.now() + dt.timedelta(minutes=5):
            raise serializers.ValidationError("Can't log a habit in the future.")
        return value


def _date(value):
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise serializers.ValidationError({"detail": "Dates must be YYYY-MM-DD."}) from exc


@api_view(["GET", "POST", "DELETE"])
@permission_classes([IsAuthenticated])
def logs(request):
    athlete = request.user.athlete
    if request.method == "POST":
        data = LogSerializer(data=request.data, context={"athlete": athlete})
        data.is_valid(raise_exception=True)
        v = data.validated_data
        log = HabitLog.objects.create(athlete=athlete, kind=v["kind"], quantity=v["quantity"],
                                      at=v.get("at") or timezone.now(), note=v.get("note", ""))
        return Response(services.log_json(log), status=201)
    kind = request.query_params.get("kind")
    if kind and kind not in services.ALL_KINDS:
        return Response({"detail": "kind must be smoke, alcohol, sugar or private."},
                        status=400)
    if request.method == "DELETE":
        # Bulk delete (R9 §B "Delete private logs"): only with an explicit kind, and only
        # the requesting athlete's own logs. Works whether or not the habit is enabled.
        if not kind:
            return Response({"detail": "kind is required to delete logs in bulk."},
                            status=400)
        deleted, _ = HabitLog.objects.filter(athlete=athlete, kind=kind).delete()
        return Response({"deleted": deleted})
    qs = HabitLog.objects.filter(athlete=athlete)
    if kind:
        qs = qs.filter(kind=kind)
    elif not athlete.private_habit_enabled:
        qs = qs.exclude(kind=services.PRIVATE)
    start, end = (_date(request.query_params.get("start")),
                  _date(request.query_params.get("end")))
    if start:
        qs = qs.filter(local_date__gte=start)
    if end:
        qs = qs.filter(local_date__lte=end)
    if not (start or end):
        qs = qs.filter(local_date__gte=athlete.local_today - dt.timedelta(days=90))
    return Response([services.log_json(log) for log in qs.order_by("-at", "-id")[:1000]])


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def log_detail(request, pk: int):
    log = get_object_or_404(HabitLog, pk=pk, athlete=request.user.athlete)
    if request.method == "DELETE":
        log.delete()
        return Response(status=204)
    data = LogSerializer(log, data={"kind": log.kind, **request.data}, partial=True,
                         context={"athlete": request.user.athlete})
    data.is_valid(raise_exception=True)
    for key, value in data.validated_data.items():
        setattr(log, key, value)
    log.save()
    return Response(services.log_json(log))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def today(request):
    return Response(services.today_payload(request.user.athlete))


def _range(request):
    value = request.query_params.get("range") or services.DEFAULT_RANGE
    return value if value in services.RANGES else None


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def summary(request):
    range_key = _range(request)
    if range_key is None:
        return Response({"detail": "range must be one of 4w, 12w, 6m."}, status=400)
    athlete = request.user.athlete
    payload = services.summary_payload(athlete, range_key)
    if request.method == "GET":
        return Response(payload)
    return _generate(request, athlete, payload)


def _generate(request, athlete, payload):
    from .ai import generate_summary

    throttle = ChatThrottle()
    if not throttle.allow_request(request, None):
        return Response({"detail": "Too many requests."}, status=429)
    try:
        result = generate_summary(athlete, payload,
                                  refresh=request.query_params.get("refresh") == "1")
    except AIUnavailable as exc:
        return Response({"detail": str(exc) or "The coach is unavailable right now."},
                        status=503)
    return Response(result)
