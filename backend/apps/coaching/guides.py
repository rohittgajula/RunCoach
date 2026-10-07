"""GET /guides/ (R9 §E): which visual guides to suggest. Deterministic — no AI.

Rows in, analysis/guides.py decides. Weather is read from this hour's cache only (never
fetched here): no location, an empty cache or an outage just means no heat reason.
"""

from __future__ import annotations

import datetime as dt
import logging

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import guides as maths

logger = logging.getLogger(__name__)
NON_RUN_KINDS = ("REST", "WALK")


def _cached_weather(athlete) -> dict:
    """{feels_like_max, hydration} from the cached forecast, or {} without one."""
    try:
        from analysis.weather_advice import advise
        from apps.ingest import weather
        from apps.ingest.weather_services import _hourly, _now, _series, refresh_location

        refresh_location(athlete)
        lat, lon = athlete.location_lat, athlete.location_lon
        if lat is None or lon is None:
            return {}
        tz = athlete.timezone or "UTC"
        fc = weather.cached_only("fc", lat, lon, tz)
        if not fc:
            return {}
        aq = weather.cached_only("aq", lat, lon, tz)
        local_now = athlete.local_now
        hourly = _hourly(fc, aq, local_now)
        max_feels = _series(fc.get("daily"), "apparent_temperature_max").get(
            local_now.date().isoformat())
        advice = advise(_now(fc, aq, hourly), hourly, local_now, max_feels_like=max_feels)
        if max_feels is None:
            values = [h["feels_like"] for h in hourly if h.get("feels_like") is not None]
            max_feels = max(values) if values else None
        return {"feels_like_max": max_feels, "hydration": advice.get("hydration")}
    except Exception:  # noqa: BLE001 — weather must never break the guides
        logger.info("guides: cached weather unreadable", exc_info=True)
        return {}


def _longest_upcoming_min(athlete) -> float | None:
    from apps.planning.models import PlannedWorkout, TrainingPlan

    today = athlete.local_today
    sunday = today + dt.timedelta(days=6 - today.weekday())
    longest = (PlannedWorkout.objects
               .filter(athlete=athlete, date__gte=today, date__lte=sunday,
                       plan__status=TrainingPlan.Status.ACTIVE,
                       status=PlannedWorkout.Status.PLANNED)
               .exclude(kind__in=NON_RUN_KINDS)
               .order_by("-duration_s").values_list("duration_s", flat=True).first())
    return round(longest / 60) if longest else None


def guide_inputs(athlete) -> tuple[maths.GuideInputs, dict]:
    from apps.activities.models import Activity
    from apps.habits.models import HabitLog

    since = athlete.local_today - dt.timedelta(days=maths.WINDOW_DAYS - 1)
    metrics = [getattr(a, "metrics", None) for a in Activity.objects.filter(
        athlete=athlete, sport__icontains="run", local_date__gte=since)
        .select_related("metrics")]
    metrics = [m for m in metrics if m is not None and m.run_block_count > 0]
    smoked = HabitLog.objects.filter(athlete=athlete, kind="smoke", local_date__gte=since,
                                     quantity__gt=0).exists()
    wx = _cached_weather(athlete)
    inputs = maths.GuideInputs(
        cadences=[m.avg_run_cadence_spm for m in metrics],
        hr_drifts=[m.hr_drift_percent for m in metrics],
        run_fractions=[m.run_fraction for m in metrics],
        runs=len(metrics), smoke_goal=athlete.smoke_goal, smoked_recently=smoked,
        feels_like_max=wx.get("feels_like_max"),
        longest_upcoming_run_min=_longest_upcoming_min(athlete),
    )
    return inputs, wx


def guides_payload(athlete) -> dict:
    inputs, wx = guide_inputs(athlete)
    body = maths.guides(inputs)
    body["context"]["weather_available"] = bool(wx)
    body["context"]["hydration"] = wx.get("hydration")
    return body


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def guides(request):
    return Response(guides_payload(request.user.athlete))
