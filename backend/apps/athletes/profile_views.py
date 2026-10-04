"""Profile tab: the summary card, Fitness/Fatigue/Form, and metric histories (spec §5).

Fitness maths is in `analysis/fitness.py`; this module only gathers daily loads.
"""

from __future__ import annotations

import datetime as dt

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import fitness as fitness_maths
from analysis.load import session_load

from .models import Athlete, MetricEntry

RANGE_DAYS = {"3m": 91, "6m": 182, "1y": 365}
SPARK_DAYS = 42

# Plausibility bounds per kind. A typo of 720 for 72 kg would otherwise become the
# "current" weight and silently move every calorie target.
BOUNDS = {
    "weight": (25.0, 300.0),
    "threshold_pace": (150.0, 1200.0),
    "resting_hr": (25.0, 120.0),
    "max_hr": (120.0, 230.0),
}


def daily_loads(athlete: Athlete) -> dict[dt.date, float]:
    """Custom load per local day.

    Segmented activities use their stored `custom_load`. Activities that could not be
    segmented (cycling, strength) count their timer minutes at walking effort: they
    are real training stress, and leaving them at zero would make a week of cross-
    training read as detraining.
    """
    from apps.activities.models import Activity

    sessions = []
    for activity in Activity.objects.filter(athlete=athlete).select_related("metrics"):
        metrics = getattr(activity, "metrics", None)
        if metrics is not None and metrics.custom_load is not None:
            load = metrics.custom_load
        else:
            load = session_load(0, (activity.total_timer_s or 0) / 60)
        sessions.append((activity.local_date, load))
    return fitness_maths.daily_loads(sessions)


def fitness_for(athlete: Athlete, start: dt.date, end: dt.date):
    """(points from start..end, status of the last point)."""
    loads = daily_loads(athlete)
    points = fitness_maths.series(loads, start, end)
    history = fitness_maths.history_days(loads, end)
    last = points[-1] if points else None
    label = fitness_maths.status(last.form if last else 0.0, history)
    return points, label


def _wellness(athlete: Athlete) -> dict | None:
    from apps.ingest.models import DailyMetrics

    row = (
        DailyMetrics.objects.filter(athlete=athlete, metric_date__lte=athlete.local_today)
        .order_by("-metric_date").first()
    )
    if row is None:
        return None
    return {
        "hrv_ms": row.hrv_overnight_avg,
        "resting_hr": row.resting_hr,
        "sleep_s": row.sleep_seconds,
        "date": row.metric_date,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def profile_summary(request):
    from apps.coaching.models import MemoryFact
    from apps.planning.models import TrainingPlan
    from apps.planning.presenters import plan_summary

    athlete = request.user.athlete
    today = athlete.local_today
    points, label = fitness_for(athlete, today - dt.timedelta(days=SPARK_DAYS - 1), today)
    last = points[-1]
    plan = (
        TrainingPlan.objects.filter(athlete=athlete, status=TrainingPlan.Status.ACTIVE)
        .select_related("race").first()
    )
    return Response({
        "athlete": {
            "display_name": athlete.display_name,
            "threshold_pace_s": athlete.threshold_pace_s,
            "weight_kg": athlete.weight_kg,
            "easy_pace_min": athlete.easy_pace_min,
            "easy_pace_max": athlete.easy_pace_max,
        },
        "wellness": _wellness(athlete),
        "fitness": {
            "value": last.fitness,
            "fatigue": last.fatigue,
            "form": last.form,
            "status": label,
            "spark": [p.fitness for p in points],
        },
        "status_spark": [p.form for p in points],
        "active_plan": plan_summary(plan, today) if plan else None,
        "memory_count": MemoryFact.objects.filter(athlete=athlete).count(),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def fitness_view(request):
    athlete = request.user.athlete
    today = athlete.local_today
    days = RANGE_DAYS.get(request.query_params.get("range", "3m"), RANGE_DAYS["3m"])
    points, label = fitness_for(athlete, today - dt.timedelta(days=days - 1), today)
    last = points[-1]
    return Response({
        "series": [
            {"date": p.date, "fitness": p.fitness, "fatigue": p.fatigue, "form": p.form}
            for p in points
        ],
        "current": {
            "fitness": last.fitness, "fatigue": last.fatigue, "form": last.form,
            "status": label,
        },
    })


def entry_json(entry: MetricEntry) -> dict:
    return {
        "id": entry.pk, "value": entry.value,
        "recorded_at": entry.recorded_at, "source": entry.source,
    }


def _garmin_resting_hr(athlete: Athlete, since: dt.date) -> list[dict]:
    """Garmin's nightly resting HR, shown in the same history as manual entries.

    Not copied into MetricEntry: it is already stored once in DailyMetrics, and a
    second copy is a second thing to keep in sync. These rows have no id and so
    cannot be deleted from the history sheet.
    """
    from apps.ingest.models import DailyMetrics

    return [
        {
            "id": None,
            "value": float(row.resting_hr),
            "recorded_at": dt.datetime.combine(row.metric_date, dt.time(7, 0), tzinfo=dt.timezone.utc),
            "source": "garmin",
        }
        for row in DailyMetrics.objects.filter(
            athlete=athlete, metric_date__gte=since, resting_hr__isnull=False
        ).order_by("-metric_date")
    ]


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def entries_view(request):
    athlete = request.user.athlete

    if request.method == "POST":
        kind = request.data.get("kind")
        if kind not in MetricEntry.Kind.values:
            return Response(
                {"detail": f"kind must be one of {', '.join(MetricEntry.Kind.values)}."},
                status=400,
            )
        try:
            value = float(request.data.get("value"))
        except (TypeError, ValueError):
            return Response({"detail": "value must be a number."}, status=400)
        low, high = BOUNDS[kind]
        if not low <= value <= high:
            return Response({"detail": f"value must be between {low:g} and {high:g}."}, status=400)
        recorded_at = timezone.now()
        if raw := request.data.get("recorded_at"):
            from django.utils.dateparse import parse_date, parse_datetime

            parsed = parse_datetime(str(raw))
            if parsed is None and (day := parse_date(str(raw))):
                parsed = dt.datetime.combine(day, dt.time(12, 0))
            if parsed is None:
                return Response({"detail": "recorded_at must be ISO 8601."}, status=400)
            if timezone.is_naive(parsed):
                from zoneinfo import ZoneInfo

                parsed = parsed.replace(tzinfo=ZoneInfo(athlete.timezone or "UTC"))
            recorded_at = parsed
        entry = MetricEntry.objects.create(
            athlete=athlete, kind=kind, value=value, recorded_at=recorded_at,
            source=MetricEntry.Source.MANUAL,
        )
        return Response(entry_json(entry), status=status.HTTP_201_CREATED)

    kind = request.query_params.get("kind")
    if kind not in MetricEntry.Kind.values:
        return Response(
            {"detail": f"kind must be one of {', '.join(MetricEntry.Kind.values)}."}, status=400
        )
    days = RANGE_DAYS.get(request.query_params.get("range", "3m"), RANGE_DAYS["3m"])
    since = athlete.local_today - dt.timedelta(days=days - 1)
    rows = MetricEntry.objects.filter(athlete=athlete, kind=kind)
    current = rows.order_by("-recorded_at", "-id").first()
    entries = [entry_json(e) for e in rows.filter(recorded_at__date__gte=since)]

    current_json = entry_json(current) if current else None
    if kind == "resting_hr":
        garmin = _garmin_resting_hr(athlete, since)
        entries = sorted(entries + garmin, key=lambda e: e["recorded_at"], reverse=True)
        if garmin and (current_json is None or garmin[0]["recorded_at"] > current_json["recorded_at"]):
            current_json = garmin[0]
    return Response({"kind": kind, "current": current_json, "entries": entries})


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def entry_delete(request, pk: int):
    entry = MetricEntry.objects.filter(athlete=request.user.athlete, pk=pk).first()
    if entry is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    entry.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
