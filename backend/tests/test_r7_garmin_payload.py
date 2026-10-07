"""R7 §3: the pure Garmin payload builder and the easy-day guard."""

from planning.garmin_workout import build_payload, group_repeats, payload_hash
from planning.workouts import easy_guard


def step(kind, seconds, intensity, hr=None, label=""):
    return {"kind": kind, "duration_s": seconds, "intensity": intensity, "label": label,
            "pace_min_s": None, "pace_max_s": None,
            "hr_min": hr[0] if hr else None, "hr_max": hr[1] if hr else None}


RUN_WALK = {
    "title": "16m run/walk", "duration_s": 960, "description": "Two blocks.",
    "steps": [step("warmup", 180, "walk", label="Walk warm-up"),
              step("run", 240, "easy", (130, 145), "Run 4:00"),
              step("walk", 120, "walk", label="Walk 2:00"),
              step("run", 240, "easy", (130, 145), "Run 4:00"),
              step("walk", 120, "walk", label="Walk 2:00"),
              step("cooldown", 60, "walk", label="Walk cool-down")],
}

TIME = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2,
        "displayable": True}
NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
HR = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4}
RUNNING = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}

# Hand-written: what garminconnect 0.3.10's RunningWorkout(...).to_dict() produces for
# this workout, with the run band on the run steps and the gentle band on every walk
# (no athlete numbers here: low 90, high = the run band's top).
EXPECTED = {
    "workoutName": "16m run/walk",
    "description": "Two blocks.",
    "sportType": RUNNING,
    "estimatedDurationInSecs": 960,
    "author": {},
    "workoutSegments": [{
        "segmentOrder": 1,
        "sportType": RUNNING,
        "workoutSteps": [
            {"type": "ExecutableStepDTO", "stepOrder": 1,
             "stepType": {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1},
             "endCondition": TIME, "endConditionValue": 180.0, "targetType": HR,
             "targetValueOne": 90.0, "targetValueTwo": 145.0, "description": "Walk warm-up"},
            {"type": "RepeatGroupDTO", "stepOrder": 2,
             "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
             "childStepId": 1, "numberOfIterations": 2, "smartRepeat": False,
             "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations",
                              "displayOrder": 7, "displayable": False},
             "endConditionValue": 2.0,
             "workoutSteps": [
                 {"type": "ExecutableStepDTO", "stepOrder": 3, "childStepId": 1,
                  "stepType": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
                  "endCondition": TIME, "endConditionValue": 240.0, "targetType": HR,
                  "targetValueOne": 130.0, "targetValueTwo": 145.0, "description": "Run 4:00"},
                 {"type": "ExecutableStepDTO", "stepOrder": 4, "childStepId": 1,
                  "stepType": {"stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4},
                  "endCondition": TIME, "endConditionValue": 120.0, "targetType": HR,
                  "targetValueOne": 90.0, "targetValueTwo": 145.0, "description": "Walk 2:00"},
             ]},
            {"type": "ExecutableStepDTO", "stepOrder": 5,
             "stepType": {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2},
             "endCondition": TIME, "endConditionValue": 60.0, "targetType": HR,
             "targetValueOne": 90.0, "targetValueTwo": 145.0, "description": "Walk cool-down"},
        ],
    }],
}


def test_payload_matches_the_expected_fixture():
    assert build_payload(RUN_WALK) == EXPECTED


def test_walk_only_with_nothing_to_derive_a_band_from_gets_no_target():
    payload = build_payload({"title": "w", "steps": [step("walk", 600, "walk", (100, 120))]})
    only = payload["workoutSegments"][0]["workoutSteps"][0]
    assert only["targetType"] == NO_TARGET and "targetValueOne" not in only


def test_repeats_fold_intervals_and_leave_the_odd_one_out():
    steps = [step("warmup", 300, "walk")]
    for i in range(4):
        steps += [step("interval", 120, "hard", (160, 175), f"Rep {i + 1}/4"),
                  step("recovery", 90, "walk")]
    steps = steps[:-1] + [step("cooldown", 300, "walk")]
    groups = group_repeats(steps)
    assert [(n, len(block)) for n, block in groups] == [(1, 1), (3, 2), (1, 1), (1, 1)]
    payload = build_payload({"title": "Intervals", "steps": steps})
    top = payload["workoutSegments"][0]["workoutSteps"]
    assert [s["type"] for s in top] == ["ExecutableStepDTO", "RepeatGroupDTO",
                                        "ExecutableStepDTO", "ExecutableStepDTO"]
    assert top[1]["numberOfIterations"] == 3
    orders = [top[0]["stepOrder"], top[1]["stepOrder"]] + \
        [s["stepOrder"] for s in top[1]["workoutSteps"]] + [top[2]["stepOrder"], top[3]["stepOrder"]]
    assert orders == [1, 2, 3, 4, 5, 6]
    assert payload["estimatedDurationInSecs"] == sum(s["duration_s"] for s in steps)


def test_zero_length_steps_are_dropped_and_hash_tracks_content_and_date():
    payload = build_payload({"title": "x", "steps": [step("run", 0, "easy"),
                                                      step("run", 600, "easy", (120, 140))]})
    assert len(payload["workoutSegments"][0]["workoutSteps"]) == 1
    h = payload_hash(payload, "2026-10-05")
    assert h == payload_hash(build_payload({"title": "x", "steps": [
        step("run", 600, "easy", (120, 140))]}), "2026-10-05")
    assert h != payload_hash(payload, "2026-10-06")


def test_easy_guard_values():
    assert easy_guard("RUN_WALK", z2_high=146, hr_ceiling=155, easy_pace=(600, 645)) == {
        "hr_max": 146, "pace_min_s": 600, "pace_max_s": 645, "cadence_target": 160}
    assert easy_guard("LONG", z2_high=None, hr_ceiling=155, easy_pace=(600, 645))["hr_max"] == 155
    assert easy_guard("EASY", z2_high=None, hr_ceiling=150, easy_pace=None)["pace_min_s"] is None
    assert easy_guard("INTERVALS", z2_high=146, hr_ceiling=155, easy_pace=(600, 645)) is None
