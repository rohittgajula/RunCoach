"""GET /api/planning/arc/ — the past and the future on one axis.

The five tabs each answer "what now". This answers "is this going anywhere",
which is a different question and needs a different shape: weeks, side by side,
with what you did and what the plan asks for drawn at the same scale.

Everything here is arithmetic. The numbers are counted in Python and handed over
finished, so the client draws and nothing interprets.
"""

from __future__ import annotations

import datetime as dt

from django.db.models import Max
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.activities.models import Activity, ActivityMetrics
from planning import arc, practice

from .models import PlannedWorkout, StrengthSession, TrainingPlan
from .plan_views import HIDDEN_PLAN_STATUSES
from .presenters import is_run
from .strength_service import sessions_between

#: Run sessions in the generator's vocabulary. Everything else a plan can hold
#: (strength, and the odd cross-training day) is counted as a gym day instead.
NON_RUN_KINDS = {"STRENGTH", "CROSS", "REST"}


def _block_s(steps) -> int:
    """The longest unbroken run step in a planned session.

    Not the session's duration: the walking breaks are what make a 24-minute
    session hold a 6-minute block. Falls back to 0 rather than to the duration,
    because a session with no steps has made no claim about a block and
    guessing one would put a target on the chart that nobody set.
    """
    return max(
        (int(step.get("duration_s") or 0)
         for step in (steps or []) if step.get("intensity") != "walk"),
        default=0,
    )


def _runs(athlete, first: dt.date, last: dt.date) -> list[arc.RunRow]:
    """Segmented runs only, so every figure is distance run rather than logged."""
    activities = (
        Activity.objects.filter(athlete=athlete, local_date__gte=first, local_date__lte=last)
        .select_related("metrics")
        .order_by("local_date")
    )
    rows = []
    for activity in activities:
        if not is_run(activity):
            continue
        metrics: ActivityMetrics | None = getattr(activity, "metrics", None)
        if metrics is None:
            # Unsegmented, so there is no honest run figure for it. Counting the
            # logged distance here is exactly the lie the segmenter exists to stop.
            continue
        rows.append(arc.RunRow(
            day=activity.local_date,
            run_s=float(metrics.run_duration_s or 0),
            run_m=float(metrics.run_distance_m or 0),
            longest_run_s=float(metrics.longest_run_s or 0),
        ))
    return rows


def _plans(athlete, first: dt.date, last: dt.date) -> list[arc.PlanRow]:
    workouts = (
        PlannedWorkout.objects.filter(athlete=athlete, date__gte=first, date__lte=last)
        .exclude(plan__status__in=HIDDEN_PLAN_STATUSES)
        .exclude(status=PlannedWorkout.Status.SKIPPED)
        .only("date", "kind", "duration_s", "steps", "status", "completed_activity")
        .order_by("date")
    )
    rows = [
        arc.PlanRow(
            day=workout.date,
            duration_s=workout.duration_s,
            block_s=_block_s(workout.steps),
            is_run=workout.kind not in NON_RUN_KINDS,
            done=(workout.completed_activity_id is not None
                  or workout.status == PlannedWorkout.Status.COMPLETED),
        )
        for workout in workouts
    ]
    rows += [
        arc.PlanRow(
            day=session.date,
            duration_s=session.duration_s,
            block_s=0,
            is_run=False,
            done=session.status == StrengthSession.Status.COMPLETED,
        )
        for session in sessions_between(athlete, first, last)
    ]
    return rows


def _goal(athlete, weeks: list[arc.Week]) -> dict:
    """What the arc is pointing at, in the athlete's own plan mode."""
    plan = (
        TrainingPlan.objects.filter(athlete=athlete, status=TrainingPlan.Status.ACTIVE)
        .select_related("race")
        .first()
    )
    best = ActivityMetrics.objects.filter(activity__athlete=athlete).aggregate(
        best=Max("longest_run_s")
    )["best"] or 0.0
    pace = ActivityMetrics.objects.filter(
        activity__athlete=athlete, run_pace_s_per_km__isnull=False
    ).order_by("-activity__local_date").values_list("run_pace_s_per_km", flat=True).first()

    if plan is not None and plan.race_id is not None:
        return {
            "kind": "race",
            "label": plan.race.name,
            "date": plan.race.date,
            "distance_km": plan.race.distance_km,
            "target_s": None,
        }
    milestone = practice.milestone_for(best, float(pace or 0))
    ends = weeks[-1].end if weeks else None
    return {
        "kind": "practice",
        "label": milestone.label,
        "date": ends,
        "distance_km": round(milestone.distance_m / 1000, 2) if milestone.distance_m else None,
        "target_s": milestone.seconds,
        "reached": milestone.reached,
        "rung": milestone.index + 1,
        "rungs": milestone.total,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def training_arc(request):
    athlete = request.user.athlete
    today = athlete.local_today

    try:
        back = int(request.query_params.get("past_weeks") or arc.PAST_WEEKS_MAX)
        ahead = int(request.query_params.get("future_weeks") or arc.FUTURE_WEEKS_MAX)
    except ValueError:
        return Response({"detail": "past_weeks and future_weeks must be whole numbers."},
                        status=400)
    back = max(1, min(back, 52))
    ahead = max(1, min(ahead, 52))

    here = arc.monday(today)
    first = here - dt.timedelta(weeks=back)
    last = here + dt.timedelta(weeks=ahead, days=6)

    weeks = arc.build(today, _runs(athlete, first, last), _plans(athlete, first, last),
                      past_weeks=back, future_weeks=ahead)

    return Response({
        "today": today,
        "week_start": here,
        "goal": _goal(athlete, weeks),
        "peak": arc.peak(weeks) if weeks else {"run_s": 1, "block_s": 1},
        "notes": arc.describe(weeks, today),
        "weeks": [
            {
                "start": w.start,
                "end": w.end,
                "past": w.past,
                "current": w.current,
                "done": {
                    "runs": w.runs_done,
                    "run_s": round(w.run_s),
                    "run_m": round(w.run_m),
                    "longest_run_s": round(w.longest_run_s),
                    "gym": w.gym_done,
                },
                "planned": {
                    "runs": w.runs_planned,
                    "run_s": w.planned_run_s,
                    "block_s": w.planned_block_s,
                    "gym": w.gym_planned,
                },
                "missed": w.missed,
                "best_run_s": round(w.best_run_s),
            }
            for w in weeks
        ],
    })
