"""Weekly adaptation: last week's actual running against what was planned (R6 §2).

Deterministic and one-directional, like every safety rule here — it can hold the plan
back, never push it on:

* actual < 60 % of planned  -> repeat last week's volume instead of progressing;
* actual > 130 % of planned -> do not increase further: the plan stays as written
  (the extra running is not banked as a reason to ramp faster);
* otherwise                 -> follow the plan.

Pure: seconds in, a decision out.
"""

from __future__ import annotations

from dataclasses import dataclass

LOW_RATIO = 0.60
HIGH_RATIO = 1.30


@dataclass(frozen=True)
class Decision:
    rule: str            # "repeat" | "cap" | "follow" | "none"
    factor: float        # what next week's future workouts are scaled by (<= 1.0)
    reason: str


def _minutes(seconds: float) -> int:
    return round(seconds / 60)


def decide(planned_run_s: float, actual_run_s: float, next_planned_run_s: float) -> Decision:
    if planned_run_s <= 0:
        return Decision("none", 1.0, "Nothing was planned last week, so nothing to compare.")

    ratio = actual_run_s / planned_run_s
    did = (f"You ran {_minutes(actual_run_s)} of {_minutes(planned_run_s)} planned minutes "
           f"last week ({round(ratio * 100)} %).")
    if ratio < LOW_RATIO:
        if next_planned_run_s > planned_run_s > 0:
            factor = round(planned_run_s / next_planned_run_s, 3)
            return Decision("repeat", factor, f"{did} This week repeats last week's volume "
                                              "instead of progressing.")
        return Decision("repeat", 1.0, f"{did} This week was already no bigger than last, "
                                       "so it stays as planned.")
    if ratio > HIGH_RATIO:
        return Decision("cap", 1.0, f"{did} That is more than planned — the plan does not "
                                    "increase further because of it. Keep the extra easy.")
    return Decision("follow", 1.0, f"{did} On track: the plan continues as written.")
