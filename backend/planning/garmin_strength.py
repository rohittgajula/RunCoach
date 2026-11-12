"""A strength session as a Garmin Connect strength workout (R13 §4). Pure — no Django.

garminconnect 0.3.10 has `Garmin.upload_strength_workout(StrengthWorkout)` (a typed
wrapper around `upload_workout`, POST /workout-service/workout) and the exercise catalogue
`garminconnect.exercises` (category / exerciseName pairs). The JSON below is what
`StrengthWorkout(...).to_dict()` produces with `create_strength_set`-style blocks: per
exercise a RepeatGroupDTO of `sets` iterations around one exercise step (ends on reps,
or on time for holds) and one rest step. Ids come from `garminconnect.workout`
(StepType, ConditionType, TargetType), copied here so this module needs no library.

The (category, exerciseName) pairs are checked against the installed catalogue in
tests/test_r13_strength.py.
"""

from __future__ import annotations

import hashlib
import json

STRENGTH = {"sportTypeId": 5, "sportTypeKey": "strength_training", "displayOrder": 5}
INTERVAL = {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3}
REST = {"stepTypeId": 5, "stepTypeKey": "rest", "displayOrder": 5}
REPEAT = {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6}
REPS = {"conditionTypeId": 10, "conditionTypeKey": "reps", "displayOrder": 10,
        "displayable": True}
TIME = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2,
        "displayable": True}
ITERATIONS = {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7,
              "displayable": False}
NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target",
             "displayOrder": 1}

# Pattern + rung -> (category, exerciseName), taken from garminconnect.exercises
# rather than guessed. The rung matters: a wall push-up and a full push-up are the
# same pattern and completely different sessions, and sending the watch one name
# for both makes the history on it meaningless.
#
# Three rungs have no exact match in Garmin's catalogue — wall and knee push-ups,
# and the Pallof press. They fall back to the nearest real movement, and the step's
# own description carries the actual name, so the watch still shows "Wall push-up"
# while the logged exercise is the closest thing Garmin knows about.
CATALOGUE: dict[tuple[str, int], tuple[str, str]] = {
    ("calf", 1): ("CALF_RAISE", "CALF_RAISE"),
    ("calf", 2): ("CALF_RAISE", "CALF_RAISE"),
    ("calf", 3): ("CALF_RAISE", "SINGLE_LEG_STANDING_CALF_RAISE"),
    ("calf", 4): ("CALF_RAISE", "SINGLE_LEG_STANDING_CALF_RAISE"),
    ("calf", 5): ("CALF_RAISE", "SINGLE_LEG_STANDING_DUMBBELL_CALF_RAISE"),

    ("squat", 1): ("SQUAT", "AIR_SQUAT"),
    ("squat", 2): ("SQUAT", "AIR_SQUAT"),
    ("squat", 3): ("SQUAT", "GOBLET_SQUAT"),
    ("squat", 4): ("LUNGE", "BARBELL_SPLIT_SQUAT"),
    ("squat", 5): ("LUNGE", "DUMBBELL_BULGARIAN_SPLIT_SQUAT"),

    ("hinge", 1): ("HIP_RAISE", "HIP_RAISE"),
    ("hinge", 2): ("HIP_RAISE", "HIP_RAISE"),
    ("hinge", 3): ("DEADLIFT", "ROMANIAN_DEADLIFT"),
    ("hinge", 4): ("DEADLIFT", "SINGLE_LEG_ROMANIAN_DEADLIFT_WITH_DUMBBELL"),
    ("hinge", 5): ("DEADLIFT", "DEADLIFT"),

    ("push", 1): ("PUSH_UP", "INCLINE_PUSH_UP"),   # no wall push-up in the catalogue
    ("push", 2): ("PUSH_UP", "INCLINE_PUSH_UP"),
    ("push", 3): ("PUSH_UP", "INCLINE_PUSH_UP"),
    ("push", 4): ("PUSH_UP", "INCLINE_PUSH_UP"),   # no knee push-up either
    ("push", 5): ("PUSH_UP", "PUSH_UP"),

    ("pull", 1): ("ROW", "INVERTED_ROW"),
    ("pull", 2): ("ROW", "SEATED_CABLE_ROW"),
    ("pull", 3): ("ROW", "DUMBBELL_ROW"),
    ("pull", 4): ("PULL_UP", "CLOSE_GRIP_LAT_PULLDOWN"),
    ("pull", 5): ("PULL_UP", "BAND_ASSISTED_PULL_UP"),

    ("core", 1): ("HIP_STABILITY", "DEAD_BUG"),
    ("core", 2): ("PLANK", "PLANK"),
    ("core", 3): ("PLANK", "SIDE_PLANK"),
    ("core", 4): ("PLANK", "PLANK"),               # no Pallof press in the catalogue
    ("core", 5): ("LEG_RAISE", "HANGING_KNEE_RAISE"),
}


def catalogue_entry(exercise: dict) -> tuple[str, str] | None:
    """The Garmin category and name for one prescribed exercise, or None.

    Falls back to the pattern's rung 1 rather than dropping the exercise: a
    session that silently arrives on the watch missing half its movements is
    worse than one whose fifth rung is logged under a slightly easier name.
    """
    key = exercise.get("key")
    level = int(exercise.get("level") or 1)
    return CATALOGUE.get((key, level)) or CATALOGUE.get((key, 1))


MAX_NAME = 60


def _exercise_step(exercise: dict, order: int, child: int) -> dict:
    category, name = catalogue_entry(exercise)
    reps = exercise.get("reps")
    seconds = exercise.get("seconds")
    per_side = 2 if exercise.get("per_side") else 1
    step = {
        "type": "ExecutableStepDTO", "stepOrder": order, "stepType": dict(INTERVAL),
        "childStepId": child, "targetType": dict(NO_TARGET),
        "category": category, "exerciseName": name,
        "description": exercise["name"] + (" (each side)" if per_side == 2 else ""),
    }
    if reps:
        step["endCondition"] = dict(REPS)
        step["endConditionValue"] = float(reps * per_side)
    else:
        step["endCondition"] = dict(TIME)
        step["endConditionValue"] = float((seconds or 30) * per_side)
    return step


def build_payload(session: dict) -> dict:
    """session = {title, duration_s, exercises: [...]} -> StrengthWorkout JSON."""
    order = 0
    child = 0
    steps = []
    for exercise in session.get("exercises") or []:
        # The warm-up stays off the watch. Being prompted through leg swings by
        # a wrist timer is noise; the lifting is the part that benefits from
        # one. This used to happen by accident — the warm-up keys are simply
        # absent from CATALOGUE — which would have silently started sending them
        # the first time somebody added a mapping.
        if exercise.get("is_warmup"):
            continue
        if catalogue_entry(exercise) is None:
            continue
        sets = max(1, int(exercise.get("sets") or 1))
        order += 1
        child += 1
        group = {
            "type": "RepeatGroupDTO", "stepOrder": order, "stepType": dict(REPEAT),
            "childStepId": child, "numberOfIterations": sets, "workoutSteps": [],
            "endCondition": dict(ITERATIONS), "endConditionValue": float(sets),
            "smartRepeat": False,
        }
        order += 1
        group["workoutSteps"].append(_exercise_step(exercise, order, child))
        order += 1
        group["workoutSteps"].append({
            "type": "ExecutableStepDTO", "stepOrder": order, "stepType": dict(REST),
            "childStepId": child, "endCondition": dict(TIME),
            "endConditionValue": float(exercise.get("rest_s") or 30),
            "targetType": dict(NO_TARGET),
        })
        steps.append(group)
    return {
        "workoutName": (session.get("title") or "RunCoach strength")[:MAX_NAME],
        "sportType": dict(STRENGTH),
        "estimatedDurationInSecs": int(session.get("duration_s") or 0),
        "workoutSegments": [{"segmentOrder": 1, "sportType": dict(STRENGTH),
                             "workoutSteps": steps}],
        "author": {},
        "description": "RunCoach strength & drills — stop a set when form slips.",
    }


def payload_hash(payload: dict, date: str) -> str:
    blob = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(f"{blob}|{date}".encode()).hexdigest()
