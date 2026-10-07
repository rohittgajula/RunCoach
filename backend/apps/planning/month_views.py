"""GET /calendar/month/?month=YYYY-MM — the month grid (R6 §4).

One status per day, decided here so the client only draws dots:

    done     past planned workout with a linked activity (compliance score >= 60)
    partial  ... linked, but compliance score < 60
    missed   past planned workout with nothing linked
    planned  future planned workout
    today    today, planned or not, unless already done/partial
    extra    a run on a day with nothing planned
    rest     a day inside the active plan with nothing planned and no run
    null     outside any plan, nothing done
"""

from __future__ import annotations

import datetime as dt

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.activities.models import Activity

from .actuals import compliance_json
from .models import PlannedWorkout, TrainingPlan
from .plan_views import HIDDEN_PLAN_STATUSES
from .presenters import is_run

PARTIAL_BELOW = 60


def _month(raw: str | None, today: dt.date) -> dt.date | None:
    if not raw:
        return today.replace(day=1)
    try:
        return dt.datetime.strptime(raw, "%Y-%m").date().replace(day=1)
    except ValueError:
        return None


def _workout_status(workout: PlannedWorkout, day_activities: list, today: dt.date) -> str:
    activity = workout.completed_activity
    if activity is not None:
        score = compliance_json(workout, activity).get("score")
        return "partial" if score is not None and score < PARTIAL_BELOW else "done"
    if workout.status == PlannedWorkout.Status.COMPLETED:
        return "done"           # marked complete by hand, nothing to score
    if workout.kind == "WALK" and day_activities and workout.date <= today:
        return "done"           # walks never auto-link; any activity that day counts
    if workout.date < today:
        return "missed"
    return "today" if workout.date == today else "planned"


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def calendar_month(request):
    athlete = request.user.athlete
    today = athlete.local_today
    first = _month(request.query_params.get("month"), today)
    if first is None:
        return Response({"detail": "month must be YYYY-MM."}, status=400)
    last = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)

    workouts = list(
        PlannedWorkout.objects.filter(athlete=athlete, date__gte=first, date__lte=last)
        .exclude(plan__status__in=HIDDEN_PLAN_STATUSES)
        .exclude(status=PlannedWorkout.Status.SKIPPED)
        .select_related("completed_activity__metrics", "athlete")
        .prefetch_related("completed_activity__segments")
        .order_by("date", "id")
    )
    activities = list(
        Activity.objects.filter(athlete=athlete, local_date__gte=first, local_date__lte=last)
        .order_by("started_at")
    )
    plan = TrainingPlan.objects.filter(athlete=athlete, status=TrainingPlan.Status.ACTIVE).first()
    span = None
    if plan is not None:
        phases = list(plan.phases.all())
        if phases:
            span = (phases[0].start, phases[-1].end)

    from .strength_service import sessions_between

    strength = {}
    for session in sessions_between(athlete, first, last):
        strength.setdefault(session.date, {"id": session.pk, "title": session.title,
                                           "status": session.status})
    by_day_workout: dict[dt.date, PlannedWorkout] = {}
    for workout in workouts:
        by_day_workout.setdefault(workout.date, workout)
    by_day_activities: dict[dt.date, list] = {}
    for activity in activities:
        by_day_activities.setdefault(activity.local_date, []).append(activity)

    days = []
    counts = {"done": 0, "missed": 0}
    cursor = first
    while cursor <= last:
        workout = by_day_workout.get(cursor)
        day_activities = by_day_activities.get(cursor, [])
        runs = [a for a in day_activities if is_run(a)]
        if workout is not None:
            status = _workout_status(workout, day_activities, today)
            if status in ("done", "partial"):
                counts["done"] += 1
            elif status == "missed":
                counts["missed"] += 1
        elif runs:
            status = "extra"
        elif cursor == today:
            status = "today"
        elif span and span[0] <= cursor <= span[1]:
            status = "rest"
        else:
            status = None
        days.append({
            "date": cursor,
            "planned": {"kind": workout.kind, "title": workout.title,
                        "duration_s": workout.duration_s} if workout else None,
            "status": status,
            # R13 §4
            "strength": strength.get(cursor),
            "activities": [
                {"id": a.pk, "sport": a.sport,
                 "duration_s": round(a.total_timer_s or a.total_elapsed_s or 0),
                 "distance_m": round(a.total_distance_m or 0)}
                for a in day_activities
            ],
        })
        cursor += dt.timedelta(days=1)

    run_activities = [a for a in activities if is_run(a)]
    return Response({
        "month": first.strftime("%Y-%m"),
        "today": today,
        "days": days,
        "totals": {
            "planned_s": sum(w.duration_s for w in by_day_workout.values()),
            # Running time, so "9 of 12 runs · 6h 40m" reads as one statement.
            "actual_s": round(sum(a.total_timer_s or a.total_elapsed_s or 0
                                  for a in run_activities)),
            "runs_done": counts["done"],
            "runs_planned": len(by_day_workout),
            "runs_missed": counts["missed"],
            "runs_extra": sum(1 for d in days if d["status"] == "extra"),
        },
    })
