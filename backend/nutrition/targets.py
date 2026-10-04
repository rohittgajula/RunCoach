"""Daily energy, macro and water targets, sized to the day's training.

The safety rule is the one that shapes this module: **no deficit on a long or hard day,
or on the day after a long run.** Under-fuelling the sessions that matter most is how a
weight-loss goal turns into a stalled base and an injury. The rule only ever *removes* a
deficit; it never adds one and never touches a surplus.

All inputs are plain values, so every rule here is testable without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Sex = Literal["male", "female"]
Goal = Literal["maintain", "lose", "gain"]

KCAL_PER_KG_FAT = 7700
MAX_DEFICIT = 500
MAX_SURPLUS = 400
MAX_RATE_KG_PER_WEEK = 0.75

NON_EXERCISE_FACTOR = 1.35
# When height or age is missing Mifflin-St Jeor cannot run. 22 kcal/kg is a common,
# deliberately middle-of-the-road resting estimate — flagged to the athlete via
# `missing` rather than presented as measured.
FALLBACK_BMR_PER_KG = 22.0
# Only used when weight itself is missing, so the screen still renders. Always reported
# in `missing` so the UI nudges the athlete to Settings.
FALLBACK_WEIGHT_KG = 70.0

RUN_KCAL_PER_KG_KM = 1.0
WALK_KCAL_PER_KG_KM = 0.5

PROTEIN_G_PER_KG = 1.6
PROTEIN_G_PER_KG_LOSING = 1.8
FAT_FLOOR_G_PER_KG = 0.8

WATER_ML_PER_KG = 35
WATER_ML_PER_RUN_HOUR = 600

# Sessions that must never be under-fuelled.
HARD_KINDS = {"LONG", "INTERVALS", "TEMPO", "RACE"}
EASY_KINDS = {"EASY", "RUN_WALK", "WALK"}


@dataclass(frozen=True)
class Profile:
    weight_kg: float | None
    height_cm: float | None = None
    age: int | None = None
    sex: Sex | None = None
    goal: Goal = "maintain"
    rate_kg_per_week: float = 0.25


@dataclass(frozen=True)
class DayWorkout:
    """One session on the day, planned or done. Durations in seconds."""

    kind: str                       # generator SessionKind
    duration_s: float
    run_s: float = 0.0
    walk_s: float = 0.0
    run_pace_s_per_km: float = 480.0
    walk_pace_s_per_km: float = 700.0


@dataclass(frozen=True)
class Targets:
    kcal: int
    carbs_g: int
    protein_g: int
    fat_g: int
    water_ml: int
    rationale: str
    bmr: int
    non_exercise: int
    exercise: int
    exercise_source: Literal["garmin", "planned", "none"]
    goal_adjustment: int
    carbs_g_per_kg: float
    missing: list[str] = field(default_factory=list)


def bmr(weight_kg: float, height_cm: float | None, age: int | None, sex: Sex | None) -> float:
    """Mifflin-St Jeor. Sex unknown -> the average of the two formulas. Height or age
    unknown -> 22 kcal/kg."""
    if not height_cm or age is None:
        return FALLBACK_BMR_PER_KG * weight_kg
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    if sex == "male":
        return base + 5
    if sex == "female":
        return base - 161
    return base + (5 - 161) / 2


def exercise_kcal(
    weight_kg: float, workouts: list[DayWorkout], completed_kcal: float | None
) -> tuple[float, str]:
    """Garmin's measured calories when the session is done; else an estimate from the
    plan. Running costs roughly 1 kcal per kg per km and walking about half that,
    largely independent of pace — which is why distance, not time, drives it."""
    if completed_kcal:
        return float(completed_kcal), "garmin"
    if not workouts:
        return 0.0, "none"
    total = 0.0
    for workout in workouts:
        run_km = workout.run_s / workout.run_pace_s_per_km if workout.run_pace_s_per_km else 0
        walk_km = workout.walk_s / workout.walk_pace_s_per_km if workout.walk_pace_s_per_km else 0
        total += RUN_KCAL_PER_KG_KM * weight_kg * run_km + WALK_KCAL_PER_KG_KM * weight_kg * walk_km
    return total, "planned"


def carbs_per_kg(workouts: list[DayWorkout]) -> tuple[float, str]:
    """g/kg of carbohydrate and the label for the day type that set it."""
    if not workouts:
        return 3.0, "Rest day"
    kinds = {w.kind for w in workouts}
    if "RACE" in kinds:
        return 8.0, "Race day"
    long_minutes = max((w.duration_s / 60 for w in workouts if w.kind == "LONG"), default=0)
    if long_minutes >= 90:
        return 7.0, "Long run day (90 min+)"
    if "LONG" in kinds:
        return 6.0, "Long run day"
    if kinds & {"TEMPO", "INTERVALS"}:
        return 6.0, "Hard session day"
    easy_minutes = sum(w.duration_s for w in workouts) / 60
    if easy_minutes > 45:
        return 5.0, "Easy run day"
    return 4.0, "Short easy day"


def goal_adjustment(goal: Goal, rate_kg_per_week: float) -> float:
    rate = min(max(rate_kg_per_week or 0.0, 0.0), MAX_RATE_KG_PER_WEEK)
    daily = rate * KCAL_PER_KG_FAT / 7
    if goal == "lose":
        return -min(daily, MAX_DEFICIT)
    if goal == "gain":
        return min(daily, MAX_SURPLUS)
    return 0.0


def day_targets(
    profile: Profile,
    workouts: list[DayWorkout],
    completed_kcal: float | None = None,
    day_after_long: bool = False,
) -> Targets:
    missing: list[str] = []
    if not profile.weight_kg:
        missing.append("weight_kg")
    if not profile.height_cm:
        missing.append("height_cm")
    if not profile.sex:
        missing.append("sex")
    if profile.age is None:
        missing.append("date_of_birth")

    kg = profile.weight_kg or FALLBACK_WEIGHT_KG
    base = bmr(kg, profile.height_cm, profile.age, profile.sex)
    non_exercise = base * NON_EXERCISE_FACTOR
    exercise, source = exercise_kcal(kg, workouts, completed_kcal)

    reasons: list[str] = []
    g_per_kg, day_label = carbs_per_kg(workouts)
    reasons.append(f"{day_label} — carbs {g_per_kg:g} g/kg")

    adjustment = goal_adjustment(profile.goal, profile.rate_kg_per_week)
    hard_day = any(w.kind in HARD_KINDS for w in workouts)
    if adjustment < 0 and (hard_day or day_after_long):
        # The rule only ever removes a deficit. A surplus is left alone.
        adjustment = 0.0
        reasons.append(
            "no deficit today (fuel the long/hard session)" if hard_day
            else "no deficit today (recovering from the long run)"
        )
    elif adjustment < 0:
        reasons.append(f"{round(adjustment)} kcal for weight loss")
    elif adjustment > 0:
        reasons.append(f"+{round(adjustment)} kcal for weight gain")

    protein_per_kg = PROTEIN_G_PER_KG_LOSING if profile.goal == "lose" else PROTEIN_G_PER_KG
    total = non_exercise + exercise + adjustment
    carbs_g = g_per_kg * kg
    protein_g = protein_per_kg * kg
    fat_g = (total - 4 * carbs_g - 4 * protein_g) / 9

    floor = FAT_FLOOR_G_PER_KG * kg
    if fat_g < floor:
        # Never cut fat below the floor to make the sum work: the total rises instead.
        fat_g = floor
        total = 4 * carbs_g + 4 * protein_g + 9 * fat_g
        reasons.append("fat held at its 0.8 g/kg floor")

    run_hours = sum(w.duration_s for w in workouts if w.kind != "WALK") / 3600
    water = WATER_ML_PER_KG * kg + WATER_ML_PER_RUN_HOUR * run_hours

    return Targets(
        kcal=round(total),
        carbs_g=round(carbs_g),
        protein_g=round(protein_g),
        fat_g=round(fat_g),
        water_ml=int(round(water / 50) * 50),
        rationale="; ".join(reasons) + ".",
        bmr=round(base),
        non_exercise=round(non_exercise),
        exercise=round(exercise),
        exercise_source=source,  # type: ignore[arg-type]
        goal_adjustment=round(adjustment),
        carbs_g_per_kg=g_per_kg,
        missing=missing,
    )
