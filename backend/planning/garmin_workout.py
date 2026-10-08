"""A PlannedWorkout's steps as a Garmin Connect workout (R7 §3). Pure — no Django.

The JSON matches what garminconnect 0.3.10 sends for a typed workout:
`RunningWorkout(...).to_dict()` (pydantic, `exclude_none=True`) posted by
`Garmin.upload_workout` to /workout-service/workout. Shapes and ids come from the
library's own `garminconnect.workout` module (StepType, ConditionType, TargetType),
copied here so this module needs neither Django nor the library.

* warmup -> warmup, cooldown -> cooldown, run / interval / stride -> interval,
  walk / recovery -> recovery. Every step ends on time.
* EVERY step gets a custom heart-rate range — targetType heart.rate.zone (id 4) with
  targetValueOne/Two = the band in bpm — so the watch shows its target screen (gauge
  against the band) for the whole workout, walks included, not just the run blocks.
  The band for a step:
    - non-walk step that carries an HR band (run, easy jog warm-up/cool-down, tempo,
      reps when zones are known): that band, unchanged.
    - walk-intensity step (walk, walk warm-up / cool-down, walk recovery, any kind):
      the GENTLE band. low = max(resting HR + 20, 90); high = the athlete's easy-run
      top (hr_easy_max, else hr_ceiling), lowered to the lowest top of any banded run
      step in the same workout, so a walk band is never higher than a run band and
      never asks for harder effort. If that leaves no room, low = high - 10.
    - non-walk step without a band (strides, reps or a race when no HR zones are
      known): easy -> (hr_easy_min, hr_easy_max), moderate/hard -> (hr_easy_max,
      hr_ceiling) — capped at the athlete's ceiling, never above it.
  The athlete numbers come in `workout["hr"]` ({resting_hr, hr_easy_min, hr_easy_max,
  hr_ceiling}); without them the walk band is derived from the run steps alone (low
  90) and a step with nothing to derive from gets no target.
* R16: a step the athlete edited carries `target`: "hr" -> its own band (walk steps
  too), "pace" -> a pace.zone target (id 6) in m/s, slow edge first, "none" -> no
  target, "auto" -> the rules above. Generated steps have no `target` and are unchanged.
* Consecutive identical blocks (e.g. run 4:00 + walk 2:00, five times) become one
  RepeatGroupDTO with numberOfIterations; labels are ignored when comparing.
"""

from __future__ import annotations

import hashlib
import json

RUNNING = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}

STEP_TYPES = {
    "warmup": {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2},
    "interval": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4},
    "repeat": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
}
KIND_TO_STEP = {"warmup": "warmup", "cooldown": "cooldown", "run": "interval",
                "interval": "interval", "stride": "interval", "walk": "recovery",
                "recovery": "recovery"}

TIME = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2,
        "displayable": True}
ITERATIONS = {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7,
              "displayable": False}
NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target",
             "displayOrder": 1}
HEART_RATE = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone",
              "displayOrder": 4}
PACE = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6}

MAX_NAME = 60
GENTLE_FLOOR = 90          # bpm: a walk band never starts below this
GENTLE_ABOVE_RESTING = 20  # bpm above resting HR where the walk band starts
GENTLE_MIN_WIDTH = 10
MAX_PATTERN = 4


def _key(step: dict) -> tuple:
    """What makes two steps the same block on the watch (label excluded). Steps edited
    by the athlete (R16, they carry `target`) also compare target and pace — generated
    steps keep their old key, so their payloads (and hashes) do not change."""
    key = (step.get("kind"), step.get("duration_s"), step.get("intensity"),
           step.get("hr_min"), step.get("hr_max"))
    if "target" in step:
        key += (step.get("target"), step.get("pace_min_s"), step.get("pace_max_s"))
    return key


def group_repeats(steps: list[dict]) -> list[tuple[int, list[dict]]]:
    """[(iterations, block_steps)]: consecutive identical blocks folded together.

    Greedy from the left: at each position take the pattern length (1..4) that
    covers the most steps with at least two repetitions; ties go to the shorter one.
    """
    out: list[tuple[int, list[dict]]] = []
    i = 0
    while i < len(steps):
        best_k, best_n = 1, 1
        for k in range(1, MAX_PATTERN + 1):
            pattern = [_key(s) for s in steps[i:i + k]]
            if len(pattern) < k:
                break
            n = 1
            while [_key(s) for s in steps[i + n * k:i + (n + 1) * k]] == pattern:
                n += 1
            if n >= 2 and n * k > best_n * best_k:
                best_k, best_n = k, n
        out.append((best_n, steps[i:i + best_k]))
        i += best_k * best_n
    return out


def _banded(step: dict) -> bool:
    return step.get("intensity") != "walk" and bool(step.get("hr_min")) \
        and bool(step.get("hr_max")) and step.get("target") not in ("none", "pace")


def gentle_band(hr: dict | None, steps: list[dict]) -> tuple[int, int] | None:
    """The walk / warm-up / cool-down HR band (see module docstring)."""
    hr = hr or {}
    tops = [int(s["hr_max"]) for s in steps if _banded(s)]
    candidates = [v for v in (hr.get("hr_easy_max") or hr.get("hr_ceiling"),) if v] + tops
    if not candidates:
        return None
    high = int(min(candidates))
    resting = hr.get("resting_hr")
    low = max(int(resting) + GENTLE_ABOVE_RESTING if resting else 0, GENTLE_FLOOR)
    if low > high - GENTLE_MIN_WIDTH:
        low = high - GENTLE_MIN_WIDTH
    return low, high


def _fallback_band(step: dict, hr: dict | None) -> tuple[int, int] | None:
    """A non-walk step with no band of its own: the athlete's easy or ceiling range."""
    hr = hr or {}
    easy_min, easy_max, ceiling = hr.get("hr_easy_min"), hr.get("hr_easy_max"), \
        hr.get("hr_ceiling")
    if step.get("intensity") == "easy" and easy_min and easy_max and easy_min < easy_max:
        return int(easy_min), int(easy_max)
    if easy_max and ceiling and easy_max < ceiling:
        return int(easy_max), int(ceiling)
    return None


def step_band(step: dict, gentle: tuple[int, int] | None,
              hr: dict | None) -> tuple[int, int] | None:
    """The (low, high) bpm target the watch shows for one step."""
    target = step.get("target")
    if target in ("none", "pace"):
        return None
    if target == "hr" and step.get("hr_min") and step.get("hr_max"):
        return int(step["hr_min"]), int(step["hr_max"])
    if step.get("intensity") == "walk":
        return gentle
    if _banded(step):
        return int(step["hr_min"]), int(step["hr_max"])
    return _fallback_band(step, hr)


def pace_speeds(step: dict) -> tuple[float, float] | None:
    """R16: an edited step with a pace target -> (slow, fast) in m/s, as Garmin wants
    (targetValueOne = the slow edge). Pace is s/km, pace_min_s the fast edge."""
    if step.get("target") != "pace" or not step.get("pace_min_s") or not step.get("pace_max_s"):
        return None
    fast, slow = int(step["pace_min_s"]), int(step["pace_max_s"])
    return round(1000 / slow, 4), round(1000 / fast, 4)


def _executable(step: dict, order: int, child_id: int | None,
                band: tuple[int, int] | None = None) -> dict:
    out = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": dict(STEP_TYPES[KIND_TO_STEP.get(step.get("kind"), "interval")]),
        "endCondition": dict(TIME),
        "endConditionValue": float(step["duration_s"]),
        "targetType": dict(NO_TARGET),
    }
    if child_id is not None:
        out["childStepId"] = child_id
    speeds = pace_speeds(step)
    if speeds:
        out["targetType"] = dict(PACE)
        out["targetValueOne"] = speeds[0]
        out["targetValueTwo"] = speeds[1]
    elif band:
        out["targetType"] = dict(HEART_RATE)
        out["targetValueOne"] = float(band[0])
        out["targetValueTwo"] = float(band[1])
    if step.get("label"):
        out["description"] = str(step["label"])[:100]
    return out


def build_payload(workout: dict) -> dict:
    """workout = {title, duration_s, steps, description?, hr?} -> Garmin workout JSON."""
    steps = [s for s in workout.get("steps") or [] if (s.get("duration_s") or 0) > 0]
    hr = workout.get("hr")
    gentle = gentle_band(hr, steps)

    def executable(step, order, child):
        return _executable(step, order, child, step_band(step, gentle, hr))

    order = 0
    child = 0
    out_steps: list[dict] = []
    for iterations, block in group_repeats(steps):
        if iterations == 1:
            order += 1
            out_steps.append(executable(block[0], order, None))
            continue
        order += 1
        child += 1
        group = {
            "type": "RepeatGroupDTO",
            "stepOrder": order,
            "stepType": dict(STEP_TYPES["repeat"]),
            "childStepId": child,
            "numberOfIterations": iterations,
            "workoutSteps": [],
            "endCondition": dict(ITERATIONS),
            "endConditionValue": float(iterations),
            "smartRepeat": False,
        }
        for step in block:
            order += 1
            group["workoutSteps"].append(executable(step, order, child))
        out_steps.append(group)

    payload = {
        "workoutName": (workout.get("title") or "RunCoach workout")[:MAX_NAME],
        "sportType": dict(RUNNING),
        "estimatedDurationInSecs": int(sum(s["duration_s"] for s in steps)),
        "workoutSegments": [{
            "segmentOrder": 1,
            "sportType": dict(RUNNING),
            "workoutSteps": out_steps,
        }],
        "author": {},
    }
    description = (workout.get("description") or "").strip()
    if description:
        payload["description"] = description[:500]
    return payload


def payload_hash(payload: dict, date: str) -> str:
    """Idempotency key: the exact JSON that would be uploaded, plus its date."""
    blob = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(f"{blob}|{date}".encode()).hexdigest()
