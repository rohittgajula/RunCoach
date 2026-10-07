"""Progress comparison (R8 §C): the last N runs against the N before. Pure.

A run is a plain dict (see `METRICS` for the keys it may carry, plus `date`, `id`,
`fastest_1k_s`). Runs come oldest first. Every delta is direction-aware: `better` is
True / False, or None when the change is too small to call (< 1 %) or the metric has
no better direction (average and max HR on their own).
"""

from __future__ import annotations

import statistics

WINDOWS = (1, 5, 10, 20)
WINDOW_ONE_PREVIOUS = 5
NOISE_PCT = 1.0
CADENCE_TARGET = 168
# key -> (label, unit, higher is better: True / False / None)
METRICS = {
    "run_km": ("Run distance", "km", True),
    "total_km": ("Total distance", "km", True),
    "run_pace": ("Run pace", "s/km", False),
    "avg_hr": ("Average HR", "bpm", None),
    "max_hr": ("Max HR", "bpm", None),
    "easy_hr": ("HR at easy pace", "bpm", False),
    "efficiency": ("Efficiency (m/min per bpm)", "m/min/bpm", True),
    "hr_drift": ("HR drift", "%", False),
    "cadence": ("Cadence", "spm", "target"),
    "run_fraction": ("Run fraction", "%", True),
    "longest_run_s": ("Longest continuous run", "s", True),
    "z2_pct": ("Time in Z2", "%", True),
}
BUCKETS = [("lt2", "< 2 km", 0, 2), ("2to5", "2–5 km", 2, 5), ("5to8", "5–8 km", 5, 8),
           ("8plus", "8 km +", 8, float("inf"))]


def bucket_of(total_km: float | None) -> str | None:
    if total_km is None:
        return None
    return next(key for key, _, low, high in BUCKETS if low <= total_km < high)


def split(runs: list[dict], window: int) -> tuple[list[dict], list[dict]]:
    """(current, previous). window=1 compares the last run with the 5 before it."""
    current = runs[-window:] if window else []
    before = runs[:-window] if window else runs
    previous = before[-(WINDOW_ONE_PREVIOUS if window == 1 else window):]
    return current, previous


def _mean(runs: list[dict], key: str):
    values = [r.get(key) for r in runs if r.get(key) is not None]
    return statistics.mean(values) if values else None


def _better(key: str, current, previous, delta, delta_pct):
    direction = METRICS[key][2]
    if direction is None or delta is None or delta == 0:
        return None
    if delta_pct is not None and abs(delta_pct) < NOISE_PCT:
        return None
    if direction == "target":
        return abs(current - CADENCE_TARGET) < abs(previous - CADENCE_TARGET)
    return (delta > 0) == direction


def _round(key: str, value):
    if value is None:
        return None
    if key in ("run_km", "total_km"):
        return round(value, 2)
    if key == "efficiency":
        return round(value, 3)
    if key == "run_fraction":
        return round(value * 100, 1)
    return round(value, 1)


def compare(current: list[dict], previous: list[dict]) -> list[dict]:
    rows = []
    for key, (label, unit, _) in METRICS.items():
        cur, prev = _mean(current, key), _mean(previous, key)
        delta = delta_pct = None
        if cur is not None and prev is not None:
            delta = cur - prev
            delta_pct = round(delta / prev * 100, 1) if prev else None
        rows.append({"key": key, "label": label, "unit": unit,
                     "current": _round(key, cur), "previous": _round(key, prev),
                     "delta": _round(key, delta), "delta_pct": delta_pct,
                     "better": _better(key, cur, prev, delta, delta_pct)})
    return rows


def distance_buckets(runs: list[dict], window: int) -> list[dict]:
    out = []
    for key, label, _, _ in BUCKETS:
        mine = [r for r in runs if bucket_of(r.get("total_km")) == key]
        current, previous = split(mine, window)
        out.append({"bucket": key, "label": label, "runs": len(mine),
                    "current_n": len(current), "previous_n": len(previous),
                    "metrics": compare(current, previous) if current else []})
    return out


def _best(runs, key, lowest: bool, current_ids: set):
    candidates = [r for r in runs if r.get(key) is not None]
    if not candidates:
        return None
    pick = (min if lowest else max)(candidates, key=lambda r: (r[key] if lowest else r[key],))
    return {"value": _round(key, pick[key]) if key in METRICS else round(pick[key], 1),
            "date": pick.get("date"), "activity_id": pick.get("id"),
            "new": pick.get("id") in current_ids}


def bests(runs: list[dict], current: list[dict]) -> dict:
    """All-time (as given) bests, each flagged `new` when set inside the current window."""
    ids = {r.get("id") for r in current}
    return {"fastest_1k_s": _best(runs, "fastest_1k_s", True, ids),
            "longest_run_km": _best(runs, "total_km", False, ids),
            "longest_continuous_s": _best(runs, "longest_run_s", False, ids),
            "lowest_easy_hr": _best(runs, "easy_hr", True, ids)}


def series(runs: list[dict]) -> list[dict]:
    return [{"date": r.get("date"), "activity_id": r.get("id"), "run_km": _round("run_km", r.get("run_km")),
             "total_km": _round("total_km", r.get("total_km")),
             "pace": _round("run_pace", r.get("run_pace")),
             "avg_hr": r.get("avg_hr"), "efficiency": _round("efficiency", r.get("efficiency")),
             "cadence": _round("cadence", r.get("cadence")),
             "bucket": bucket_of(r.get("total_km"))} for r in runs]


def _item(key, kind, title, why, how) -> dict:
    return {"key": key, "kind": kind, "title": title, "why": why, "how": how}


def focus(metrics: list[dict]) -> list[dict]:
    """Deterministic "what to improve / what to check" from the comparison rows."""
    by = {m["key"]: m for m in metrics}
    items = []
    drift = by["hr_drift"]
    if drift["current"] is not None and (
            (drift["delta"] is not None and drift["delta"] >= 2) or drift["current"] >= 8):
        items.append(_item("hr_drift", "check", "Check heat and hydration",
                           f"Heart-rate drift is {drift['current']}% on recent runs.",
                           "Run in the cooler part of the day, drink before you start and "
                           "slow down as it warms up."))
    easy = by["easy_hr"]
    if easy["delta"] is not None and easy["delta"] >= 3:
        items.append(_item("easy_hr", "check", "Easy runs costing more",
                           f"HR at easy pace is up {easy['delta']} bpm on the runs before.",
                           "Check sleep, stress and heat; keep the next few runs truly easy."))
    cadence = by["cadence"]
    if (cadence["current"] is not None and cadence["current"] < 160
            and (cadence["delta"] is None or abs(cadence["delta"]) < 2)):
        items.append(_item("cadence", "improve", "Cadence drills",
                           f"Cadence is flat at {cadence['current']:.0f} spm.",
                           "Add 4 × 20 s of quick, light steps to two easy runs a week."))
    fraction = by["run_fraction"]
    if (fraction["current"] is not None and fraction["current"] < 90
            and (fraction["delta"] is None or fraction["delta"] < 2)):
        items.append(_item("run_blocks", "improve", "Extend run blocks",
                           f"You are running {fraction['current']:.0f}% of the time, about "
                           "the same as before.",
                           "Add 30–60 s to each run block next week, keeping the walks the same."))
    pace, eff = by["run_pace"], by["efficiency"]
    if pace["better"] is False and eff["better"] is False:
        items.append(_item("fatigue", "check", "Slower and less efficient",
                           "Pace and efficiency both slipped against the runs before.",
                           "Look at sleep, heat and load — a lighter week often fixes it."))
    return items[:4]


def progress(runs: list[dict], window: int) -> dict:
    current, previous = split(runs, window)
    metrics = compare(current, previous) if current else []
    return {"window": window, "runs": len(runs), "current_n": len(current),
            "previous_n": len(previous), "metrics": metrics,
            "distance_buckets": distance_buckets(runs, window),
            "bests": bests(runs, current), "series": series(runs[-max(window * 2, 40):]),
            "focus": focus(metrics) if metrics else []}
