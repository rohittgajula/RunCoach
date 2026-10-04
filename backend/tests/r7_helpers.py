"""Shared builders for the R7 tests."""

import datetime as dt

from apps.ingest.models import DailyMetrics
from apps.planning.models import PlannedWorkout, TrainingPlan


def run_walk_steps(blocks=3, hr=(130, 145)):
    steps = [{"kind": "warmup", "duration_s": 300, "intensity": "walk", "label": "Walk warm-up",
              "pace_min_s": None, "pace_max_s": None, "hr_min": None, "hr_max": None}]
    for _ in range(blocks):
        steps += [{"kind": "run", "duration_s": 240, "intensity": "easy", "label": "Run 4:00",
                   "pace_min_s": 600, "pace_max_s": 645, "hr_min": hr[0], "hr_max": hr[1]},
                  {"kind": "walk", "duration_s": 120, "intensity": "walk", "label": "Walk 2:00",
                   "pace_min_s": None, "pace_max_s": None, "hr_min": None, "hr_max": None}]
    return steps


def active_plan(athlete):
    plan = TrainingPlan.objects.filter(athlete=athlete, status="active").first()
    return plan or TrainingPlan.objects.create(athlete=athlete, name="Test plan",
                                               status="active", generator_version="g1")


def make_workout(athlete, day=None, *, kind="RUN_WALK", steps=None, status="planned"):
    steps = steps if steps is not None else run_walk_steps()
    return PlannedWorkout.objects.create(
        athlete=athlete, plan=active_plan(athlete), date=day or athlete.local_today,
        title="23m run/walk", kind=kind, duration_s=sum(s["duration_s"] for s in steps),
        load=30.0, steps=steps, description="Run/walk.", target_zone="Z2", status=status,
    )


def wellness(athlete, day=None, **fields):
    day = day or athlete.local_today
    row, _ = DailyMetrics.objects.update_or_create(athlete=athlete, metric_date=day,
                                                   defaults=fields)
    return row


def tomorrow(athlete, days=1):
    return athlete.local_today + dt.timedelta(days=days)
