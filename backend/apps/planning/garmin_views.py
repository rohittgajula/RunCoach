"""R7 §3: POST/DELETE /workouts/{id}/garmin/, POST /plans/active/garmin/."""

from __future__ import annotations

import datetime as dt

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import PlannedWorkout, TrainingPlan
from .presenters import workout_json
from .tasks import run_garmin_push

MAX_DAYS = 28


def _job_failure(job: dict) -> Response | None:
    """503 when the job could not run at all; 502 when Garmin refused a workout."""
    if job.get("code") in ("rate_limited", "auth", "queue", "gone"):
        return Response({"detail": job.get("detail") or "Garmin is unavailable."}, status=503)
    return None


@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
def workout_garmin(request, pk: int):
    athlete = request.user.athlete
    workout = PlannedWorkout.objects.filter(athlete=athlete, pk=pk).first()
    if workout is None:
        return Response({"detail": "Not found."}, status=404)
    action = "delete" if request.method == "DELETE" else "send"
    job = run_garmin_push(athlete.pk, [workout.pk], action)
    failed = _job_failure(job)
    if failed:
        return failed
    result = (job.get("results") or [None])[0]
    if result is None or result["status"] == "error":
        return Response({"detail": (result or {}).get("detail") or "Garmin refused the workout.",
                         "result": result}, status=502)
    if result["status"] == "skipped" and action == "send":
        return Response({"detail": result["detail"], "result": result}, status=409)
    workout.refresh_from_db()
    return Response({**workout_json(workout), "garmin_result": result})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def plan_garmin(request):
    """Send the next N days (default 7, today included) of the active plan."""
    athlete = request.user.athlete
    try:
        days = int(request.data.get("days", 7))
    except (TypeError, ValueError):
        return Response({"detail": "days must be a number."}, status=400)
    if not 1 <= days <= MAX_DAYS:
        return Response({"detail": f"days must be 1–{MAX_DAYS}."}, status=400)
    plan = TrainingPlan.objects.filter(athlete=athlete, status=TrainingPlan.Status.ACTIVE).first()
    if plan is None:
        return Response({"detail": "No active plan."}, status=404)
    today = athlete.local_today
    ids = list(PlannedWorkout.objects.filter(
        athlete=athlete, plan=plan, date__gte=today, date__lt=today + dt.timedelta(days=days),
        status=PlannedWorkout.Status.PLANNED,
    ).order_by("date", "id").values_list("pk", flat=True))
    if not ids:
        return Response({"results": [], "detail": ""})
    job = run_garmin_push(athlete.pk, ids, "send")
    failed = _job_failure(job)
    if failed:
        return failed
    body = {"results": job["results"], "detail": job.get("detail", "")}
    return Response(body, status=200 if job["ok"] else 502)
