"""Planned vs done for one workout (R6 §3). Pure: plain dicts in, a score out.

Each check compares one prescribed thing with what the watch recorded and says
`hit`, `close` or `missed`. The score is their mean (hit 100, close 60, missed 0), so
a workout can be "done" and still score low — an easy run raced at threshold is the
commonest way a beginner gets hurt, and a tick alone would hide it.

Inputs:
    planned = {kind, duration_s, target_zone, steps: [Step dicts]}
    actual  = {duration_s, run_duration_s, longest_run_s, time_in_zone: {Z1..Z5,
               below} | None, run_blocks: [{duration_s, hr_avg, hr_max, pace_s_per_km}]}
"""

from __future__ import annotations

ZONES = ("Z1", "Z2", "Z3", "Z4", "Z5")
STATUS_POINTS = {"hit": 100, "close": 60, "missed": 0}
EASY_KINDS = {"EASY", "RUN_WALK", "LONG", "WALK"}
HARD_KINDS = {"INTERVALS", "TEMPO", "RACE"}
EASY_ZONE_SHARE = 0.70


def _clock(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _ratio_status(ratio: float, hit=(0.9, 1.15), close=(0.75, 1.3)) -> str:
    if hit[0] <= ratio <= hit[1]:
        return "hit"
    if close[0] <= ratio <= close[1]:
        return "close"
    return "missed"


def _check(key, label, status, planned, actual, note) -> dict:
    return {"key": key, "label": label, "status": status, "planned": planned,
            "actual": actual, "note": note}


def _duration(planned: dict, actual: dict) -> dict | None:
    want, got = planned.get("duration_s") or 0, actual.get("duration_s") or 0
    if want <= 0:
        return None
    ratio = got / want
    status = _ratio_status(ratio)
    note = ("About as long as planned." if status == "hit"
            else "Shorter than planned." if ratio < 1 else "Longer than planned.")
    return _check("duration", "Duration", status, _clock(want), _clock(got), note)


def _run_time(planned: dict, actual: dict) -> dict | None:
    want = sum(s.get("duration_s") or 0 for s in planned.get("steps") or []
               if s.get("intensity") != "walk")
    if want <= 0:
        return None
    got = actual.get("run_duration_s") or 0
    ratio = got / want
    # Running more than prescribed is not a hit: it is the load the plan did not ask for.
    status = _ratio_status(ratio, hit=(0.85, 1.15), close=(0.65, 1.35))
    note = ("Running time on target." if status == "hit"
            else "Less running than planned." if ratio < 1 else "More running than planned.")
    return _check("run_time", "Running time", status, _clock(want), _clock(got), note)


def _easy_effort(planned: dict, actual: dict) -> dict | None:
    target = planned.get("target_zone")
    zones = actual.get("time_in_zone") or {}
    if planned.get("kind") not in EASY_KINDS or target not in ZONES or not zones:
        return None
    total = sum(zones.get(z, 0) or 0 for z in (*ZONES, "below"))
    if total <= 0:
        return None
    limit = ZONES.index(target)
    # At or below the target zone counts: walking breaks sit in Z1 and that is right.
    easy = (zones.get("below", 0) or 0) + sum(zones.get(z, 0) or 0 for z in ZONES[: limit + 1])
    share = easy / total
    status = "hit" if share >= EASY_ZONE_SHARE else "close" if share >= 0.5 else "missed"
    note = (f"{round(share * 100)} % of the time at or below {target}."
            + ("" if status == "hit" else " Slow the running blocks down."))
    return _check("easy_effort", f"Easy effort ({target} or below)", status,
                  f"≥ {round(EASY_ZONE_SHARE * 100)} %", f"{round(share * 100)} %", note)


def _hr_ceiling(planned: dict, actual: dict, ceiling: int | None) -> dict | None:
    blocks = [b for b in actual.get("run_blocks") or [] if b.get("hr_max")]
    if not ceiling or not blocks or planned.get("kind") in HARD_KINDS:
        return None
    over = [b for b in blocks if b["hr_max"] > ceiling]
    status = ("hit" if not over else "close" if len(over) <= max(1, len(blocks) // 4)
              else "missed")
    peak = max(b["hr_max"] for b in blocks)
    note = ("No run block went over your ceiling." if not over
            else f"{len(over)} of {len(blocks)} run blocks went over {ceiling} bpm — "
                 "walk as soon as you cross it.")
    return _check("hr_ceiling", "HR ceiling", status, f"≤ {ceiling} bpm", f"{peak} bpm", note)


def _continuous_block(planned: dict, actual: dict) -> dict | None:
    if planned.get("kind") != "LONG":
        return None
    want = max((s.get("duration_s") or 0 for s in planned.get("steps") or []
                if s.get("kind") == "run"), default=0)
    if want <= 0:
        return None
    got = actual.get("longest_run_s") or 0
    ratio = got / want
    status = "hit" if ratio >= 0.9 else "close" if ratio >= 0.7 else "missed"
    note = ("Longest unbroken run reached the target." if status == "hit"
            else "Longest unbroken run fell short of the target block.")
    return _check("continuous_block", "Longest unbroken run", status, _clock(want),
                  _clock(got), note)


def hard_blocks(planned: dict, actual: dict) -> int:
    """Run blocks that look like the prescribed hard reps."""
    reps = [s for s in planned.get("steps") or [] if s.get("kind") == "interval"]
    blocks = actual.get("run_blocks") or []
    if not reps:
        return 0
    rep = reps[0]
    pace_limit = rep.get("pace_max_s")
    hr_floor = rep.get("hr_min")
    rep_s = rep.get("duration_s") or 0
    count = 0
    for block in blocks:
        if pace_limit and block.get("pace_s_per_km"):
            hard = block["pace_s_per_km"] <= pace_limit + 15
        elif hr_floor and block.get("hr_avg"):
            hard = block["hr_avg"] >= hr_floor
        else:
            hard = rep_s > 0 and 0.5 * rep_s <= (block.get("duration_s") or 0) <= 1.5 * rep_s
        count += bool(hard)
    return count


def _intervals(planned: dict, actual: dict) -> dict | None:
    if planned.get("kind") != "INTERVALS":
        return None
    want = sum(1 for s in planned.get("steps") or [] if s.get("kind") == "interval")
    if want <= 0:
        return None
    got = hard_blocks(planned, actual)
    status = "hit" if got >= want else "close" if got >= 0.7 * want else "missed"
    note = ("All the hard reps were there." if status == "hit"
            else f"{got} of {want} hard reps found.")
    return _check("intervals", "Hard reps", status, str(want), str(got), note)


# R7 §2: how the athlete said it felt (post-run check-in RPE, 1-10).
EASY_RPE_HIT_MAX = 5
EASY_RPE_MISSED_MIN = 7


def _effort(planned: dict, actual: dict) -> dict | None:
    """Easy sessions only: RPE >= 7 means the easy run was not easy."""
    rpe = actual.get("rpe")
    if rpe is None or planned.get("kind") not in EASY_KINDS:
        return None
    status = ("hit" if rpe <= EASY_RPE_HIT_MAX else
              "missed" if rpe >= EASY_RPE_MISSED_MIN else "close")
    note = {"hit": "Felt easy, as an easy session should.",
            "close": "Felt a little harder than easy.",
            "missed": "Felt harder than an easy run should."}[status]
    return _check("effort", "Felt easy (RPE)", status, f"≤ {EASY_RPE_HIT_MAX}/10",
                  f"{rpe}/10", note)


def time_above(samples, cap: int | None) -> tuple[int, int] | None:
    """(seconds above `cap` bpm, seconds with HR) from (offset_s, hr) pairs.

    Weighted by the gap to the next sample like zones.time_in_zones; gaps over 30 s
    are pauses and count for nothing. None without a cap or any HR.
    """
    if not cap:
        return None
    ordered = sorted((o, h) for o, h in samples if h is not None)
    above = total = 0.0
    for (start, hr), (nxt, _) in zip(ordered, ordered[1:]):
        gap = max(nxt - start, 0.0)
        if gap > 30:
            continue
        total += gap
        if hr > cap:
            above += gap
    if total <= 0:
        return None
    return round(above), round(total)


def evaluate(planned: dict, actual: dict, hr_ceiling: int | None = None) -> dict:
    checks = [c for c in (
        _duration(planned, actual),
        _run_time(planned, actual),
        _easy_effort(planned, actual),
        _hr_ceiling(planned, actual, hr_ceiling),
        _continuous_block(planned, actual),
        _intervals(planned, actual),
        _effort(planned, actual),
    ) if c is not None]
    score = (round(sum(STATUS_POINTS[c["status"]] for c in checks) / len(checks))
             if checks else None)
    return {"score": score, "checks": checks}
