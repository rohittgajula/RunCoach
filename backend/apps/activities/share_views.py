"""R15 §D: GET /activities/{id}/share-data/ — everything the client needs to draw a
customisable share image. Own activities only; the route is endpoint-trimmed exactly as
/activities/{id}/route/ (map_hide_endpoints)."""

from __future__ import annotations

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import share as maths

from .models import Activity
from .views import route_body


def _weather(activity) -> dict | None:
    from apps.health.models import ActivityWeather

    try:
        w = activity.weather
    except ActivityWeather.DoesNotExist:
        return None
    if w is None or w.source == "none" or w.temp_c is None:
        return None
    return {"temp_c": w.temp_c, "feels_like_c": w.feels_like_c, "humidity": w.humidity,
            "dew_point_c": w.dew_point_c}


def share_payload(activity: Activity, hide: bool) -> dict:
    from apps.planning.models import PlannedWorkout

    athlete = activity.athlete
    metrics = getattr(activity, "metrics", None)
    km = (activity.total_distance_m or 0) / 1000
    moving = int(round(activity.total_timer_s or activity.total_elapsed_s or 0))
    local_start = activity.started_at.astimezone(athlete.local_now.tzinfo)
    samples = list(activity.records.order_by("offset_s").values_list(
        "offset_s", "distance_m", "heart_rate"))
    splits = maths.km_splits(samples)
    route = route_body(activity, hide)
    gain = activity.total_ascent_m
    if gain is None and route.get("elevation"):
        gain = route["elevation"]["gain_m"]
    cadence = activity.avg_cadence_spm or (metrics.avg_run_cadence_spm if metrics else None)
    workout = (PlannedWorkout.objects.filter(athlete=athlete, completed_activity=activity)
               .values_list("title", flat=True).first())
    return {
        "activity_id": activity.pk, "sport": activity.sport,
        "title": maths.title_for(local_start.hour), "workout_title": workout,
        "date": activity.local_date, "started_at": activity.started_at,
        "start_local": local_start.strftime("%Y-%m-%dT%H:%M"),
        "distance_m": round(activity.total_distance_m or 0, 1), "distance_km": round(km, 2),
        "moving_s": moving, "elapsed_s": int(round(activity.total_elapsed_s or moving)),
        "avg_pace_s_per_km": int(round(moving / km)) if km >= 0.05 and moving else None,
        "run_pace_s_per_km": (int(round(metrics.run_pace_s_per_km))
                              if metrics and metrics.run_pace_s_per_km else None),
        "avg_hr": activity.avg_hr, "max_hr": activity.max_hr,
        "cadence_spm": int(round(cadence)) if cadence else None,
        "elevation_gain_m": round(gain, 1) if gain is not None else None,
        "calories": activity.calories,
        "splits": splits, "best_km": maths.best_km(splits),
        "weather": _weather(activity),
        "route": {"available": route["available"], "reason": route["reason"],
                  "hidden_endpoints": route["hidden_endpoints"],
                  "trimmed_m": route["trimmed_m"], "bounds": route["bounds"],
                  "points": [[p["lat"], p["lon"]] for p in route["points"]],
                  "km_markers": [{"km": m["km"], "lat": m["lat"], "lon": m["lon"]}
                                 for m in route["km_markers"]]},
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def share_data(request, pk: int):
    athlete = request.user.athlete
    activity = (Activity.objects.filter(athlete=athlete, pk=pk).select_related("metrics")
                .first())
    if activity is None:
        return Response({"detail": "Not found."}, status=404)
    return Response(share_payload(activity, athlete.map_hide_endpoints))
