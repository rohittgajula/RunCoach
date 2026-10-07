"""The Django side of the Diet tab: gather the day, call the pure calculators.

Everything numerical is in `nutrition/`. This module loads the athlete's profile, the
day's workouts and activities and meals, and shapes the result for §5 of the spec.
"""

from __future__ import annotations

import datetime as dt

from apps.activities.models import Activity
from apps.athletes.models import Athlete, MetricEntry
from apps.planning.models import PlannedWorkout, TrainingPlan
from nutrition.balance import summarise
from nutrition.fueling import fueling_for
from nutrition.targets import (
    FALLBACK_WEIGHT_KG, DayWorkout, Profile, Targets, day_targets,
)

from .models import Meal

RANGE_DAYS = {"3m": 91, "6m": 182, "1y": 365}
LONG_ACTIVITY_S = 75 * 60
HIDDEN_PLAN_STATUSES = [TrainingPlan.Status.PROPOSED, TrainingPlan.Status.DECLINED]


def profile_for(athlete: Athlete) -> Profile:
    return Profile(
        weight_kg=athlete.weight_kg,
        height_cm=athlete.height_cm,
        age=athlete.age,
        sex=athlete.sex or None,
        goal=athlete.diet_goal or "maintain",
        rate_kg_per_week=athlete.diet_rate_kg_per_week or 0.0,
    )


def _workout_inputs(workout: PlannedWorkout, athlete: Athlete) -> DayWorkout:
    steps = workout.steps or []
    walk_s = sum(s.get("duration_s", 0) for s in steps if s.get("intensity") == "walk")
    run_s = sum(s.get("duration_s", 0) for s in steps if s.get("intensity") != "walk")
    return DayWorkout(
        kind=workout.kind, duration_s=workout.duration_s, run_s=run_s, walk_s=walk_s,
        run_pace_s_per_km=(athlete.easy_pace_min + athlete.easy_pace_max) / 2,
    )


def _activity_inputs(activity: Activity) -> DayWorkout:
    """An unplanned run still sets the day's carbs. Long-ish runs count as long."""
    seconds = activity.total_timer_s or 0
    return DayWorkout(kind="LONG" if seconds >= LONG_ACTIVITY_S else "EASY", duration_s=seconds)


class _DayData:
    """Workouts and activities for a date range, loaded once."""

    def __init__(self, athlete: Athlete, start: dt.date, end: dt.date):
        self.athlete = athlete
        self.workouts: dict[dt.date, list[PlannedWorkout]] = {}
        for workout in PlannedWorkout.objects.filter(
            athlete=athlete, date__gte=start - dt.timedelta(days=1), date__lte=end,
        ).exclude(plan__status__in=HIDDEN_PLAN_STATUSES).exclude(
            status=PlannedWorkout.Status.SKIPPED
        ):
            self.workouts.setdefault(workout.date, []).append(workout)
        self.activities: dict[dt.date, list[Activity]] = {}
        for activity in Activity.objects.filter(
            athlete=athlete, local_date__gte=start - dt.timedelta(days=1), local_date__lte=end
        ):
            self.activities.setdefault(activity.local_date, []).append(activity)

    def targets(self, day: dt.date, profile: Profile) -> Targets:
        workouts = [_workout_inputs(w, self.athlete) for w in self.workouts.get(day, [])]
        activities = self.activities.get(day, [])
        if not workouts and activities:
            workouts = [_activity_inputs(a) for a in activities if "run" in a.sport]
        calories = [a.calories for a in activities if a.calories]
        completed_kcal = float(sum(calories)) if calories else None

        yesterday = day - dt.timedelta(days=1)
        day_after_long = any(
            w.kind == "LONG" for w in self.workouts.get(yesterday, [])
        ) or any(
            "run" in a.sport and (a.total_timer_s or 0) >= LONG_ACTIVITY_S
            for a in self.activities.get(yesterday, [])
        )
        return day_targets(profile, workouts, completed_kcal, day_after_long)


def targets_for(athlete: Athlete, day: dt.date) -> Targets:
    return _DayData(athlete, day, day).targets(day, profile_for(athlete))


def meal_json(meal: Meal) -> dict:
    from .media import signed_url

    return {
        "id": meal.pk,
        "eaten_at": meal.eaten_at,
        "local_date": meal.local_date,
        "meal_type": meal.meal_type,
        "description": meal.description,
        # Signed and expiring: works in <img src> without an auth header (media.py).
        "photo_url": signed_url(meal.photo.name) if meal.photo else None,
        "items": meal.items or [],
        "kcal": meal.kcal,
        "carbs_g": meal.carbs_g,
        "protein_g": meal.protein_g,
        "fat_g": meal.fat_g,
        "source": meal.source,
        "ai_confidence": meal.ai_confidence,
    }


def _weather_note(athlete: Athlete, workout: PlannedWorkout) -> str | None:
    """R8 §D: forecast-aware drinking line for today's workouts (None otherwise)."""
    from apps.ingest.weather_services import fueling_note, workout_weather

    block = workout_weather(athlete, workout)
    return block.get("fueling_note") if block and block.get("available") else None


def diet_day(athlete: Athlete, day: dt.date) -> dict:
    data = _DayData(athlete, day, day)
    targets = data.targets(day, profile_for(athlete))
    meals = list(Meal.objects.filter(athlete=athlete, local_date=day))
    weight = athlete.weight_kg or FALLBACK_WEIGHT_KG

    fueling = []
    for workout in data.workouts.get(day, []):
        fuel = workout.fueling or fueling_for(workout.kind, workout.duration_s, weight).as_dict()
        fueling.append({"workout_id": workout.pk, "title": workout.title, **fuel,
                        "weather_note": _weather_note(athlete, workout)})

    from apps.ingest.weather_services import water_bonus_ml

    bonus, food_tips = water_bonus_ml(athlete, day)
    rationale = targets.rationale
    if bonus:
        rationale = f"{rationale} +{bonus} ml water for the heat today.".strip()
    return {
        "date": day,
        "targets": {
            "kcal": targets.kcal, "carbs_g": targets.carbs_g, "protein_g": targets.protein_g,
            "fat_g": targets.fat_g, "water_ml": targets.water_ml + bonus,
            "water_bonus_ml": bonus, "rationale": rationale,
        },
        "weather_tips": food_tips,
        "eaten": {
            "kcal": round(sum(m.kcal for m in meals)),
            "carbs_g": round(sum(m.carbs_g for m in meals)),
            "protein_g": round(sum(m.protein_g for m in meals)),
            "fat_g": round(sum(m.fat_g for m in meals)),
        },
        "burn": {
            "bmr": targets.bmr, "non_exercise": targets.non_exercise,
            "exercise": targets.exercise, "exercise_source": targets.exercise_source,
        },
        "meals": [meal_json(m) for m in meals],
        "fueling": fueling,
        "missing_profile": targets.missing,
    }


def trend(athlete: Athlete, range_key: str) -> dict:
    today = athlete.local_today
    days = RANGE_DAYS.get(range_key, RANGE_DAYS["3m"])
    start = today - dt.timedelta(days=days - 1)

    data = _DayData(athlete, start, today)
    profile = profile_for(athlete)

    intake: dict[dt.date, float] = {}
    for meal in Meal.objects.filter(athlete=athlete, local_date__gte=start, local_date__lte=today):
        intake[meal.local_date] = intake.get(meal.local_date, 0.0) + meal.kcal

    weights_by_day: dict[dt.date, float] = {}
    weight_points: list[tuple[dt.date, float]] = []
    entries = MetricEntry.objects.filter(
        athlete=athlete, kind=MetricEntry.Kind.WEIGHT,
    ).order_by("recorded_at")
    for entry in entries:
        local = athlete_local_date(athlete, entry.recorded_at)
        if start <= local <= today:
            weights_by_day[local] = entry.value      # latest of the day wins
            weight_points.append((local, entry.value))

    targets: dict[dt.date, float] = {}
    series = []
    cursor = start
    while cursor <= today:
        target = data.targets(cursor, profile).kcal
        targets[cursor] = target
        series.append({
            "date": cursor,
            "intake_kcal": round(intake[cursor]) if intake.get(cursor) else None,
            "target_kcal": target,
            "weight_kg": weights_by_day.get(cursor),
        })
        cursor += dt.timedelta(days=1)

    balance = summarise(intake, targets, weight_points, today)
    return {
        "series": series,
        "summary": {
            "avg_balance_kcal": balance.avg_balance_kcal,
            "predicted_kg_per_week": balance.predicted_kg_per_week,
            "actual_kg_per_week": balance.actual_kg_per_week,
            "logged_days_last_7": balance.logged_days_last_7,
        },
    }


def athlete_local_date(athlete: Athlete, moment: dt.datetime) -> dt.date:
    from zoneinfo import ZoneInfo

    try:
        zone = ZoneInfo(athlete.timezone or "UTC")
    except Exception:  # noqa: BLE001
        zone = ZoneInfo("UTC")
    return moment.astimezone(zone).date()
