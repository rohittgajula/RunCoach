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

# Guides key -> (category, exerciseName) from garminconnect.exercises.
CATALOGUE = {
    "calf": ("CALF_RAISE", "STANDING_CALF_RAISE"),
    "bridge": ("HIP_RAISE", "HIP_RAISE"),
    "split": ("LUNGE", "LUNGE"),
    "plank": ("PLANK", "PLANK"),
    "side": ("PLANK", "SIDE_PLANK"),
    "clam": ("HIP_STABILITY", "HIP_STABILITY"),
    "askip": ("WARM_UP", "WALKING_HIGH_KNEES"),
    "hipflexor": ("WARM_UP", "STRETCH_LUNGING_HIP_FLEXOR"),
}
MAX_NAME = 60


def _exercise_step(exercise: dict, order: int, child: int) -> dict:
    category, name = CATALOGUE[exercise["key"]]
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
        if exercise.get("key") not in CATALOGUE:
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
