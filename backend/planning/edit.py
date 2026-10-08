"""R16 §A: editing a planned workout's steps — validation and transforms. Pure (no Django).

The athlete (or the coach, through a chat tool) may change a session freely: a whole new
step list, a new total, ± minutes on the run or walk parts, walk breaks, an HR range,
notes. Edits are never refused for being "too much" — they are refused only when they
are invalid (a 3-second step, an HR target above max HR). How much harder the session got
is reported as plain-words `warnings`, which the UI shows before saving.

Steps are stored flat, in the generator's shape ({kind, duration_s, intensity, label,
pace_min_s, pace_max_s, hr_min, hr_max}) plus two keys only edited steps carry:
`target` ("hr" | "pace" | "none" | "auto" — what the watch shows) and `note`. The editor
works on `EditItem`s instead: a step, or `{repeat: n, steps: [...]}`; consecutive identical
stored blocks are folded back into repeats for it (garmin_workout.group_repeats).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from analysis.load import session_load

from .garmin_workout import group_repeats

TOTAL_MIN_S = 5 * 60
TOTAL_MAX_S = 240 * 60
STEP_MIN_S = 10
STEP_MAX_S = 90 * 60
REPEAT_MIN = 2
REPEAT_MAX = 30
BLOCK_MAX_STEPS = 10
MAX_STEPS = 100
PACE_MIN_S = 150          # 2:30 /km
PACE_MAX_S = 1200         # 20:00 /km
HR_FLOOR_DEFAULT = 40
HR_MAX_DEFAULT = 210
NOTE_MAX = 80
NOTES_MAX = 1000
GRID_S = 30
WALK_BREAK_S = 60
SHORTEST_PART_S = 30      # ± minutes never shrinks a part below this

EDIT_KINDS = ("warmup", "run", "walk", "recovery", "cooldown", "strides", "other")
INTENSITIES = ("walk", "easy", "moderate", "hard")
TARGETS = ("hr", "pace", "none", "auto")
APPLY_TO = ("run", "walk", "both")
HARD_KINDS = frozenset({"INTERVALS", "TEMPO", "LONG", "RACE"})

DEFAULT_INTENSITY = {"warmup": "walk", "run": "easy", "walk": "walk", "recovery": "walk",
                     "cooldown": "walk", "strides": "hard", "other": "easy"}
TO_STORED = {"strides": "stride"}
FROM_STORED = {"stride": "strides", "interval": "run"}
STORED_KINDS = {"warmup", "run", "walk", "recovery", "cooldown", "stride", "interval", "other"}

# Warning thresholds (spec R16 §A).
RUN_INCREASE = 0.25
HARD_MINUTES_S = 5 * 60
LONG_SHARE = 0.40


class EditError(ValueError):
    """Invalid edit: the message is shown to the athlete as-is."""


@dataclass(frozen=True)
class Limits:
    hr_min: int = HR_FLOOR_DEFAULT
    hr_max: int = HR_MAX_DEFAULT

    def as_dict(self) -> dict:
        return {"total_min_s": TOTAL_MIN_S, "total_max_s": TOTAL_MAX_S,
                "step_min_s": STEP_MIN_S, "step_max_s": STEP_MAX_S,
                "repeat_min": REPEAT_MIN, "repeat_max": REPEAT_MAX, "max_steps": MAX_STEPS,
                "hr_min": self.hr_min, "hr_max": self.hr_max,
                "pace_min_s": PACE_MIN_S, "pace_max_s": PACE_MAX_S}


def limits_for(resting_hr: int | None, max_hr: int | None, age: int | None) -> Limits:
    """HR bounds: resting .. max (max HR known, else 220 − age, else 210)."""
    low = int(resting_hr) if resting_hr else HR_FLOOR_DEFAULT
    high = int(max_hr) if max_hr else (220 - int(age) if age else HR_MAX_DEFAULT)
    if high <= low:
        low, high = HR_FLOOR_DEFAULT, HR_MAX_DEFAULT
    return Limits(hr_min=low, hr_max=high)


# --- sums ------------------------------------------------------------------------------

def total_s(steps) -> int:
    return sum(int(s.get("duration_s") or 0) for s in steps or [])


def run_s(steps) -> int:
    return sum(int(s.get("duration_s") or 0) for s in steps or [] if s.get("intensity") != "walk")


def walk_s(steps) -> int:
    return sum(int(s.get("duration_s") or 0) for s in steps or [] if s.get("intensity") == "walk")


def load_for(steps) -> float:
    return session_load(run_s(steps) / 60, walk_s(steps) / 60)


def clock(seconds: int) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


# --- stored <-> editor -----------------------------------------------------------------

def effective_target(step: dict) -> str:
    """What the watch shows for a stored step (see planning/garmin_workout.step_band)."""
    if step.get("target") in TARGETS:
        return step["target"]
    if step.get("intensity") != "walk" and step.get("hr_min") and step.get("hr_max"):
        return "hr"
    return "auto"


def edit_step(step: dict) -> dict:
    kind = step.get("kind") or "other"
    kind = FROM_STORED.get(kind, kind if kind in EDIT_KINDS else "other")
    return {"kind": kind, "duration_s": int(step.get("duration_s") or 0),
            "intensity": step.get("intensity") if step.get("intensity") in INTENSITIES
            else DEFAULT_INTENSITY[kind],
            "target": effective_target(step),
            "hr_low": step.get("hr_min"), "hr_high": step.get("hr_max"),
            "pace_low": step.get("pace_min_s"), "pace_high": step.get("pace_max_s"),
            "note": step.get("note")}


def edit_items(steps: list[dict]) -> list[dict]:
    """Stored steps as the editor's items, identical consecutive blocks folded."""
    live = [s for s in steps or [] if (s.get("duration_s") or 0) > 0]
    out = []
    for iterations, block in group_repeats(live):
        if iterations == 1:
            out.append(edit_step(block[0]))
        else:
            out.append({"repeat": iterations, "steps": [edit_step(s) for s in block]})
    return out


LABELS = {"warmup": "Warm-up", "cooldown": "Cool-down", "walk": "Walk",
          "recovery": "Recovery", "stride": "Stride", "other": "Other"}
RUN_LABELS = {"easy": "Run", "moderate": "Steady", "hard": "Hard", "walk": "Walk"}


def label_for(kind: str, intensity: str, duration: int, note: str | None) -> str:
    name = RUN_LABELS.get(intensity, "Run") if kind in ("run", "interval") \
        else LABELS.get(kind, "Step")
    if kind in ("warmup", "cooldown") and intensity == "walk":
        name = f"Walk {name.lower()}"
    text = f"{name} {clock(duration)}"
    return f"{text} · {note}" if note else text


def _int(value, name: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise EditError(f"{name} must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise EditError(f"{name} must be a number.") from exc
    if not math.isfinite(number):
        raise EditError(f"{name} must be a number.")
    return int(round(number))


def _hr_pair(low, high, limits: Limits, where: str) -> tuple[int | None, int | None]:
    low, high = _int(low, "hr_low"), _int(high, "hr_high")
    if low is None and high is None:
        return None, None
    if low is None or high is None:
        raise EditError(f"{where}: give both ends of the heart-rate range.")
    if low >= high:
        raise EditError(f"{where}: the heart-rate range must go from low to high.")
    if low < limits.hr_min or high > limits.hr_max:
        raise EditError(f"{where}: heart rate must be between {limits.hr_min} and "
                        f"{limits.hr_max} bpm.")
    return low, high


def _pace_pair(low, high, where: str) -> tuple[int | None, int | None]:
    low, high = _int(low, "pace_low"), _int(high, "pace_high")
    if low is None and high is None:
        return None, None
    if low is None or high is None:
        raise EditError(f"{where}: give both ends of the pace range.")
    if low > high:
        raise EditError(f"{where}: pace_low is the fast end (fewer seconds per km).")
    if low < PACE_MIN_S or high > PACE_MAX_S:
        raise EditError(f"{where}: pace must be between {clock(PACE_MIN_S)} and "
                        f"{clock(PACE_MAX_S)} per km.")
    return low, high


def stored_step(raw: dict, limits: Limits, where: str = "Step") -> dict:
    """One EditStep -> a stored step. Raises EditError."""
    if not isinstance(raw, dict):
        raise EditError(f"{where} must be an object.")
    kind = raw.get("kind")
    if kind not in EDIT_KINDS:
        raise EditError(f"{where}: kind must be one of {', '.join(EDIT_KINDS)}.")
    duration = _int(raw.get("duration_s"), "duration_s")
    if duration is None or not STEP_MIN_S <= duration <= STEP_MAX_S:
        raise EditError(f"{where}: each step must be between {STEP_MIN_S} s and "
                        f"{STEP_MAX_S // 60} min.")
    intensity = raw.get("intensity") or DEFAULT_INTENSITY[kind]
    if intensity not in INTENSITIES:
        raise EditError(f"{where}: intensity must be one of {', '.join(INTENSITIES)}.")
    if kind == "walk":
        intensity = "walk"
    hr_low, hr_high = _hr_pair(raw.get("hr_low"), raw.get("hr_high"), limits, where)
    pace_low, pace_high = _pace_pair(raw.get("pace_low"), raw.get("pace_high"), where)
    target = raw.get("target")
    if target in (None, ""):
        target = "hr" if hr_low else "pace" if pace_low else "auto"
    if target not in TARGETS:
        raise EditError(f"{where}: target must be one of {', '.join(TARGETS)}.")
    if target == "hr" and not hr_low:
        raise EditError(f"{where}: a heart-rate target needs hr_low and hr_high.")
    if target == "pace" and not pace_low:
        raise EditError(f"{where}: a pace target needs pace_low and pace_high.")
    note = raw.get("note")
    note = " ".join(str(note).split())[:NOTE_MAX] if note else None
    stored_kind = TO_STORED.get(kind, kind)
    return {"kind": stored_kind, "duration_s": duration, "intensity": intensity,
            "label": label_for(stored_kind, intensity, duration, note),
            "pace_min_s": pace_low, "pace_max_s": pace_high,
            "hr_min": hr_low, "hr_max": hr_high, "target": target, "note": note}


def expand(items, limits: Limits) -> list[dict]:
    """EditItems -> flat stored steps, validated (limits on every step and the total)."""
    if not isinstance(items, list) or not items:
        raise EditError("steps must be a non-empty list.")
    out: list[dict] = []
    for index, item in enumerate(items, start=1):
        where = f"Step {index}"
        if isinstance(item, dict) and "repeat" in item:
            times = _int(item.get("repeat"), "repeat")
            if times is None or not REPEAT_MIN <= times <= REPEAT_MAX:
                raise EditError(f"{where}: repeat must be {REPEAT_MIN}–{REPEAT_MAX} times.")
            block = item.get("steps")
            if not isinstance(block, list) or not 1 <= len(block) <= BLOCK_MAX_STEPS:
                raise EditError(f"{where}: a repeat holds 1–{BLOCK_MAX_STEPS} steps.")
            if any(isinstance(s, dict) and "repeat" in s for s in block):
                raise EditError(f"{where}: repeats can't be nested.")
            converted = [stored_step(s, limits, f"{where}.{i}") for i, s in
                         enumerate(block, start=1)]
            for _ in range(times):
                out += [dict(s) for s in converted]
        else:
            out.append(stored_step(item, limits, where))
        if len(out) > MAX_STEPS:
            raise EditError(f"At most {MAX_STEPS} steps (repeats counted out).")
    return validate(out, limits)


def validate(steps: list[dict], limits: Limits) -> list[dict]:
    """Limits every saved step list must meet (also after scaling or ± minutes)."""
    if not steps:
        raise EditError("A session needs at least one step.")
    if len(steps) > MAX_STEPS:
        raise EditError(f"At most {MAX_STEPS} steps (repeats counted out).")
    for index, step in enumerate(steps, start=1):
        duration = int(step.get("duration_s") or 0)
        if not STEP_MIN_S <= duration <= STEP_MAX_S:
            raise EditError(f"Step {index}: each step must be between {STEP_MIN_S} s and "
                            f"{STEP_MAX_S // 60} min.")
        if step.get("target") == "hr" or step.get("hr_min") or step.get("hr_max"):
            _hr_pair(step.get("hr_min"), step.get("hr_max"), limits, f"Step {index}")
    total = total_s(steps)
    if not TOTAL_MIN_S <= total <= TOTAL_MAX_S:
        raise EditError(f"The session must be {TOTAL_MIN_S // 60}–{TOTAL_MAX_S // 60} min "
                        f"in total (this is {round(total / 60)} min).")
    return steps


# --- transforms (each returns a NEW list; inputs are never mutated) ----------------------

def _relabel(step: dict) -> dict:
    """After a duration change: an edited step's label follows; a generated label with a
    clock in it ("Run 4:00") gets the new clock."""
    step = dict(step)
    if "target" in step:
        step["label"] = label_for(step["kind"], step.get("intensity") or "easy",
                                  step["duration_s"], step.get("note"))
    elif step.get("label"):
        step["label"] = re.sub(r"\d+:\d{2}(?::\d{2})?|\b\d+s\b", clock(step["duration_s"]),
                               step["label"], count=1)
    return step


def _with_duration(step: dict, duration: int) -> dict:
    if int(step.get("duration_s") or 0) == duration:
        return dict(step)
    return _relabel({**step, "duration_s": int(duration)})


def scale_to(steps: list[dict], target_total: int) -> list[dict]:
    """Every step scaled to reach `target_total` seconds exactly."""
    current = total_s(steps)
    if current <= 0:
        raise EditError("This session has no timed steps to scale.")
    factor = target_total / current
    durations = []
    for step in steps:
        d = int(step.get("duration_s") or 0) * factor
        grid = GRID_S if d >= 2 * GRID_S else STEP_MIN_S
        durations.append(max(STEP_MIN_S, int(round(d / grid)) * grid))
    residual = target_total - sum(durations)
    order = sorted(range(len(durations)), key=lambda i: -durations[i])
    for i in order:                                     # put the rounding on the biggest
        if residual == 0:
            break
        new = max(STEP_MIN_S, durations[i] + residual)
        residual -= new - durations[i]
        durations[i] = new
    return [_with_duration(s, d) for s, d in zip(steps, durations)]


def _parts(steps: list[dict], apply_to: str) -> list[int]:
    if apply_to == "both":
        return [i for i, s in enumerate(steps) if s.get("kind") != "stride"]
    if apply_to == "walk":
        return [i for i, s in enumerate(steps) if s.get("intensity") == "walk"]
    easy = [i for i, s in enumerate(steps) if s.get("intensity") == "easy"
            and s.get("kind") != "stride"]
    return easy or [i for i, s in enumerate(steps) if s.get("intensity") != "walk"
                    and s.get("kind") != "stride"]


def add_seconds(steps: list[dict], delta: int, apply_to: str = "run") -> list[dict]:
    """Spread ±delta seconds over the run / walk / all parts, proportionally to their
    length, on the 30-s grid; no part drops below 30 s."""
    if apply_to not in APPLY_TO:
        raise EditError("apply_to must be run, walk or both.")
    units = int(round(delta / GRID_S))
    if units == 0:
        raise EditError("Change by at least 30 seconds.")
    steps = [dict(s) for s in steps]
    idx = _parts(steps, apply_to)
    if not idx:
        if apply_to == "walk" and units > 0:
            walk = units * GRID_S
            steps.append({"kind": "cooldown", "duration_s": walk, "intensity": "walk",
                          "label": label_for("cooldown", "walk", walk, None),
                          "pace_min_s": None, "pace_max_s": None, "hr_min": None,
                          "hr_max": None, "target": "auto", "note": None})
            return steps
        raise EditError("This session has no " + ("walking" if apply_to == "walk" else
                                                  "running") + " to change.")
    durations = {i: int(steps[i]["duration_s"]) for i in idx}
    pool = list(idx)
    left = units
    while left and pool:
        weight = sum(durations[i] for i in pool) or len(pool)
        shares = {i: left * (durations[i] or 1) / weight for i in pool}
        alloc = {i: int(math.floor(shares[i])) if left > 0 else int(math.ceil(shares[i]))
                 for i in pool}
        rest = left - sum(alloc.values())
        step_sign = 1 if rest > 0 else -1
        for i in sorted(pool, key=lambda i: -abs(shares[i] - alloc[i])):
            if rest == 0:
                break
            alloc[i] += step_sign
            rest -= step_sign
        clamped = []
        for i in pool:
            new = durations[i] + alloc[i] * GRID_S
            if new < SHORTEST_PART_S:
                alloc[i] = -((durations[i] - SHORTEST_PART_S) // GRID_S)
                clamped.append(i)
        for i in pool:
            durations[i] += alloc[i] * GRID_S
        left -= sum(alloc.values())
        pool = [i for i in pool if i not in clamped]
        if not clamped:
            break
    if left:
        raise EditError(f"Can't take {abs(delta) // 60} min off — there isn't enough "
                        + ("walking" if apply_to == "walk" else "running") + " to shorten.")
    return [_with_duration(s, durations[i]) if i in durations else s
            for i, s in enumerate(steps)]


def add_walk_breaks(steps: list[dict], run_minutes: int) -> list[dict]:
    """Split every easy run step longer than N+1 min into N min run / 1 min walk. The
    walking comes out of the run time, so the total is unchanged."""
    run_part = int(run_minutes) * 60
    out: list[dict] = []
    split = False
    for step in steps:
        long_easy = (step.get("kind") == "run" and step.get("intensity") in ("easy", "moderate")
                     and int(step.get("duration_s") or 0) > run_part + WALK_BREAK_S)
        if not long_easy:
            out.append(dict(step))
            continue
        split = True
        left = int(step["duration_s"])
        while left >= run_part + WALK_BREAK_S + 60:
            out.append(_with_duration(step, run_part))
            out.append({"kind": "walk", "duration_s": WALK_BREAK_S, "intensity": "walk",
                        "label": label_for("walk", "walk", WALK_BREAK_S, None),
                        "pace_min_s": None, "pace_max_s": None, "hr_min": None,
                        "hr_max": None, "target": "auto", "note": None})
            left -= run_part + WALK_BREAK_S
        out.append(_with_duration(step, left))
    if not split:
        raise EditError(f"No run block is longer than {run_minutes + 1} min — nothing to "
                        "break up.")
    return out


def set_hr_range(steps: list[dict], low: int, high: int, limits: Limits) -> list[dict]:
    low, high = _hr_pair(low, high, limits, "Heart-rate range")
    if low is None:
        raise EditError("Give hr_low and hr_high.")
    out = []
    for step in steps:
        step = dict(step)
        if step.get("intensity") != "walk":
            step.update(hr_min=low, hr_max=high, target="hr")
            step.setdefault("note", None)
        out.append(step)
    return out


def retitle(title: str, total: int) -> str:
    """"45m easy aerobic run" / "Long run 60m" follow the new total minutes."""
    matches = re.findall(r"\b\d+m\b", title or "")
    if len(matches) != 1:
        return title
    return re.sub(r"\b\d+m\b", f"{round(total / 60)}m", title, count=1)


# --- warnings ---------------------------------------------------------------------------

def hr_tops(steps) -> list[int]:
    return [int(s["hr_max"]) for s in steps or []
            if effective_target(s) == "hr" and s.get("hr_max")]


def is_hard(kind: str, steps, easy_top: int | None) -> bool:
    if kind in HARD_KINDS:
        return True
    hard = sum(int(s.get("duration_s") or 0) for s in steps or []
               if s.get("intensity") in ("moderate", "hard") and s.get("kind") != "stride")
    if hard >= HARD_MINUTES_S:
        return True
    return bool(easy_top) and any(
        effective_target(s) == "hr" and s.get("hr_min") and int(s["hr_min"]) > easy_top
        for s in steps or [])


def _long_share(run: int, other_runs: list[int]) -> float | None:
    if not other_runs or run <= 0 or run < max(other_runs):
        return None
    return run / (run + sum(other_runs))


def warnings_for(*, kind: str, base_steps, new_steps, hr_ceiling: int | None,
                 easy_top: int | None, neighbour_hard: bool,
                 week_other_runs: list[int]) -> list[dict]:
    """Plain-words warnings for an edit that made the session harder than planned.
    Only what the EDIT made worse is reported; the generated plan is the baseline."""
    out = []
    base_run, new_run = run_s(base_steps), run_s(new_steps)
    if base_run > 0 and new_run > base_run * (1 + RUN_INCREASE):
        pct = round((new_run / base_run - 1) * 100)
        out.append({"key": "run_increase",
                    "text": f"That's {pct} % more running than planned ({round(base_run / 60)} → "
                            f"{round(new_run / 60)} min). Big jumps are how injuries start."})
    tops, base_tops = hr_tops(new_steps), hr_tops(base_steps)
    if hr_ceiling and tops and max(tops) > hr_ceiling and (
            not base_tops or max(tops) > max(base_tops)):
        out.append({"key": "hr_above_ceiling",
                    "text": f"A heart-rate target goes up to {max(tops)} bpm — above your "
                            f"ceiling of {hr_ceiling} bpm."})
    if neighbour_hard and is_hard(kind, new_steps, easy_top) and not is_hard(
            kind, base_steps, easy_top):
        out.append({"key": "hard_days_in_a_row",
                    "text": "This makes two hard days in a row. Keep the day before or after "
                            "easy so your legs can recover."})
    share = _long_share(new_run, week_other_runs)
    base_share = _long_share(base_run, week_other_runs)
    if share is not None and share > LONG_SHARE and (base_share is None
                                                     or base_share <= LONG_SHARE):
        out.append({"key": "long_run_share",
                    "text": f"This run is {round(share * 100)} % of the week's running. More "
                            "than 40 % in one session raises the injury risk."})
    return out


def increase_ratio(base_steps, new_steps) -> float:
    """How much harder (running time; total time when the plan has no running)."""
    base, new = run_s(base_steps), run_s(new_steps)
    if base <= 0:
        base, new = total_s(base_steps), total_s(new_steps)
    if base <= 0:
        return 0.0
    return new / base - 1


# --- a whole edit request ------------------------------------------------------------------

STEP_KEYS = ("steps", "total_minutes", "add_minutes", "add_walk_breaks", "hr_low", "hr_high")
ALL_KEYS = STEP_KEYS + ("notes",)


def _number(value, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or value is None:
        raise EditError(f"{name} must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise EditError(f"{name} must be a number.") from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise EditError(f"{name} must be between {low:g} and {high:g}.")
    return number


def parse_changes(data: dict) -> dict:
    """The request body -> normalised changes. Raises EditError."""
    if not isinstance(data, dict):
        raise EditError("Send a JSON object.")
    out: dict = {}
    if data.get("steps") is not None:
        out["steps"] = data["steps"]
    if data.get("total_minutes") is not None:
        out["total_minutes"] = _number(data["total_minutes"], "total_minutes",
                                       TOTAL_MIN_S / 60, TOTAL_MAX_S / 60)
    if data.get("add_minutes") is not None:
        minutes = _number(data["add_minutes"], "add_minutes", -120, 120)
        if abs(minutes) < 0.5:
            raise EditError("add_minutes must be at least half a minute either way.")
        out["add_minutes"] = minutes
    apply_to = data.get("apply_to")
    if apply_to not in (None, ""):
        if apply_to not in APPLY_TO:
            raise EditError("apply_to must be run, walk or both.")
        out["apply_to"] = apply_to
    if data.get("add_walk_breaks") is not None:
        out["add_walk_breaks"] = int(_number(data["add_walk_breaks"], "add_walk_breaks", 1, 30))
    if data.get("hr_low") is not None or data.get("hr_high") is not None:
        if data.get("hr_low") is None or data.get("hr_high") is None:
            raise EditError("Send both hr_low and hr_high.")
        out["hr_low"], out["hr_high"] = data["hr_low"], data["hr_high"]
    if "notes" in data and data["notes"] is not None:
        if not isinstance(data["notes"], str):
            raise EditError("notes must be text.")
        if len(data["notes"]) > NOTES_MAX:
            raise EditError(f"Keep notes under {NOTES_MAX} characters.")
        out["notes"] = data["notes"].strip()
    if not any(k in out for k in ALL_KEYS):
        raise EditError("Nothing to change — send steps, total_minutes, add_minutes, "
                        "add_walk_breaks, hr_low/hr_high or notes.")
    return out


def touches_steps(changes: dict) -> bool:
    return any(k in changes for k in STEP_KEYS + ("scale",))


def apply(steps: list[dict], changes: dict, limits: Limits) -> list[dict]:
    """Apply the step changes in the documented order; the result is validated."""
    out = [dict(s) for s in steps or [] if (s.get("duration_s") or 0) > 0]
    if "steps" in changes:
        out = expand(changes["steps"], limits)
    if "total_minutes" in changes:
        out = scale_to(out, int(round(changes["total_minutes"] * 60)))
    if "add_minutes" in changes:
        out = add_seconds(out, int(round(changes["add_minutes"] * 60)),
                          changes.get("apply_to") or "run")
    if "add_walk_breaks" in changes:
        out = add_walk_breaks(out, changes["add_walk_breaks"])
    if "hr_low" in changes:
        out = set_hr_range(out, changes["hr_low"], changes["hr_high"], limits)
    return validate(out, limits)


WEEK_ACTIONS = ("add_minutes", "scale", "add_walk_breaks", "set_hr_range")


def week_changes(action: str, value, apply_to: str | None = None) -> dict:
    """POST /plan/week-edit/ {action, value} -> the per-workout changes, except `scale`,
    which needs each workout's own total: {"scale": factor}."""
    if action not in WEEK_ACTIONS:
        raise EditError(f"action must be one of {', '.join(WEEK_ACTIONS)}.")
    if action == "add_minutes":
        minutes = _number(value, "value", -60, 60)
        if abs(minutes) < 0.5:
            raise EditError("value must be at least half a minute either way.")
        changes = {"add_minutes": minutes}
        if apply_to not in (None, ""):
            if apply_to not in APPLY_TO:
                raise EditError("apply_to must be run, walk or both.")
            changes["apply_to"] = apply_to
        return changes
    if action == "scale":
        return {"scale": _number(value, "value", 0.5, 1.5)}
    if action == "add_walk_breaks":
        return {"add_walk_breaks": int(_number(value, "value", 1, 30))}
    if isinstance(value, dict):
        low, high = value.get("hr_low", value.get("low")), value.get("hr_high", value.get("high"))
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        low, high = value
    else:
        raise EditError("value must be {hr_low, hr_high} or [low, high].")
    if low is None or high is None:
        raise EditError("value must be {hr_low, hr_high} or [low, high].")
    return {"hr_low": low, "hr_high": high}


def scaled_changes(changes: dict, steps) -> dict:
    """Turn a week `scale` into this workout's total_minutes."""
    if "scale" not in changes:
        return changes
    return {"total_minutes": max(1.0, total_s(steps) * changes["scale"] / 60)}
