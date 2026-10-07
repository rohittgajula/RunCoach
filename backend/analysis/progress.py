"""Progress comparison (R8 §C): the last N runs against the N before. Pure.

A run is a plain dict (see `METRICS` for the keys it may carry, plus `date`, `id`,
`fastest_1k_s`). Runs come oldest first. Every delta is direction-aware: `better` is
True / False, or None when the change is too small to call (< 1 %) or the metric has
no better direction (average and max HR on their own).
"""

from __future__ import annotations

import datetime as dt
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
    body = {"window": window, "runs": len(runs), "current_n": len(current),
            "previous_n": len(previous), "metrics": metrics,
            "distance_buckets": distance_buckets(runs, window),
            "bests": bests(runs, current), "series": series(runs[-max(window * 2, 40):]),
            "focus": focus(metrics) if metrics else []}
    body["period"] = {
        "mode": "window",
        "start": current[0].get("date") if current else None,
        "end": current[-1].get("date") if current else None,
        "compare_start": previous[0].get("date") if previous else None,
        "compare_end": previous[-1].get("date") if previous else None,
        "runs_current": len(current), "runs_previous": len(previous)}
    body["highlights"] = highlights(body, history_n=len(runs) - len(current))
    return body


# --- R9 §D: custom dates and the "Summary" bullets ----------------------------------

MAX_SERIES_DATES = 200
MAX_HIGHLIGHTS = 6
CONSISTENCY_STEP = 0.5        # runs/week that count as a change
MIN_SPAN_DAYS = 7


def progress_dates(runs: list[dict], start: str, end: str, compare_start: str,
                   compare_end: str) -> dict:
    """Runs dated in [start, end] against runs in [compare_start, compare_end]. Dates
    are ISO strings (they compare correctly as text). `runs` may reach back further
    than the comparison: earlier runs only count towards the all-time bests."""
    current = [r for r in runs if start <= (r.get("date") or "") <= end]
    previous = [r for r in runs if compare_start <= (r.get("date") or "") <= compare_end]
    first, last = min(start, compare_start), max(end, compare_end)
    span = [r for r in runs if first <= (r.get("date") or "") <= last]
    history = [r for r in runs if (r.get("date") or "") <= end]
    metrics = compare(current, previous) if current else []
    body = {"window": None, "runs": len(span), "current_n": len(current),
            "previous_n": len(previous), "metrics": metrics,
            "distance_buckets": bucket_rows(current, previous, span),
            "bests": bests(history, current), "series": series(span[-MAX_SERIES_DATES:]),
            "focus": focus(metrics) if metrics else [],
            "period": {"mode": "dates", "start": start, "end": end,
                       "compare_start": compare_start, "compare_end": compare_end,
                       "runs_current": len(current), "runs_previous": len(previous)}}
    current_ids = {r.get("id") for r in current}
    body["highlights"] = highlights(
        body, history_n=sum(1 for r in history if r.get("id") not in current_ids))
    return body


def bucket_rows(current: list[dict], previous: list[dict], runs: list[dict]) -> list[dict]:
    """Like-for-like by distance for two given sets of runs (date mode)."""
    out = []
    for key, label, _, _ in BUCKETS:
        cur = [r for r in current if bucket_of(r.get("total_km")) == key]
        prev = [r for r in previous if bucket_of(r.get("total_km")) == key]
        out.append({"bucket": key, "label": label,
                    "runs": sum(1 for r in runs if bucket_of(r.get("total_km")) == key),
                    "current_n": len(cur), "previous_n": len(prev),
                    "metrics": compare(cur, prev) if cur else []})
    return out


def _clock(seconds) -> str:
    seconds = int(round(abs(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _more_less(delta, more="more", less="less") -> str:
    return more if delta > 0 else less


def metric_text(row: dict) -> str | None:
    """"Run pace 7:12 → 6:58 /km — 14 s faster". None for rows without a sentence."""
    key, cur, prev, delta = row["key"], row["current"], row["previous"], row["delta"]
    if cur is None or prev is None or delta is None:
        return None
    if key == "run_pace":
        return (f"Run pace {_clock(prev)} → {_clock(cur)} /km — {abs(delta):.0f} s "
                f"{_more_less(delta, 'slower', 'faster')}")
    if key == "easy_hr":
        return (f"HR at easy pace {prev:.0f} → {cur:.0f} bpm — {abs(delta):.0f} bpm "
                f"{_more_less(delta, 'higher', 'lower')}")
    if key == "efficiency":
        pct = abs(row["delta_pct"] or 0)
        return (f"Efficiency {prev:.2f} → {cur:.2f} m/min per bpm — {pct:.0f}% "
                f"{_more_less(delta, 'better', 'lower')}")
    if key == "run_km":
        return (f"Run distance {prev:.1f} → {cur:.1f} km per run — {abs(delta):.1f} km "
                f"{_more_less(delta)}")
    if key == "run_fraction":
        return (f"Running {prev:.0f}% → {cur:.0f}% of the time — {abs(delta):.0f} points "
                f"{_more_less(delta)}")
    if key == "longest_run_s":
        return (f"Longest continuous run {_clock(prev)} → {_clock(cur)} — {_clock(delta)} "
                f"{_more_less(delta, 'longer', 'shorter')}")
    if key == "cadence":
        side = "closer to" if row["better"] else "further from"
        return f"Cadence {prev:.0f} → {cur:.0f} spm — {side} {CADENCE_TARGET}"
    if key == "hr_drift":
        return (f"HR drift {prev:.1f}% → {cur:.1f}% — {abs(delta):.1f} points "
                f"{_more_less(delta)}")
    if key == "z2_pct":
        return (f"Time in Z2 {prev:.0f}% → {cur:.0f}% — {abs(delta):.0f} points "
                f"{_more_less(delta)}")
    return None


HIGHLIGHT_ORDER = ("run_pace", "easy_hr", "efficiency", "run_km", "run_fraction",
                   "longest_run_s", "cadence", "hr_drift", "z2_pct")
BEST_TEXT = {
    "fastest_1k_s": lambda v: f"fastest 1 km in {_clock(v)}",
    "longest_run_km": lambda v: f"longest run {v:.1f} km",
    "longest_continuous_s": lambda v: f"longest continuous run {_clock(v)}",
    "lowest_easy_hr": lambda v: f"lowest easy-pace HR {v:.0f} bpm",
}


def _days_between(first: str | None, last: str | None) -> int | None:
    if not first or not last:
        return None
    return (dt.date.fromisoformat(last) - dt.date.fromisoformat(first)).days + 1


def _consistency(period: dict) -> dict | None:
    """Runs per week now vs before. Window mode measures each side's span from its
    first run (the previous side up to the first current run); spans < 7 days count
    as 7."""
    n_now, n_before = period["runs_current"], period["runs_previous"]
    if period["mode"] == "dates":
        days_now = _days_between(period["start"], period["end"])
        days_before = _days_between(period["compare_start"], period["compare_end"])
    else:
        if n_now < 2 or n_before < 2:
            return None
        days_now = _days_between(period["start"], period["end"])
        days_before = (_days_between(period["compare_start"], period["start"]) or 1) - 1
    if not days_now or not days_before or not n_before:
        return None
    now = n_now / max(days_now, MIN_SPAN_DAYS) * 7
    before = n_before / max(days_before, MIN_SPAN_DAYS) * 7
    diff = now - before
    if diff >= CONSISTENCY_STEP:
        tone = "good"
    elif diff <= -CONSISTENCY_STEP:
        tone = "bad"
    else:
        return {"tone": "neutral", "text": f"Consistency steady at {now:.1f} runs/week"}
    return {"tone": tone, "text": f"Consistency {before:.1f} → {now:.1f} runs/week"}


def highlights(body: dict, history_n: int = 0) -> list[dict]:
    """Up to 6 readable bullets, good first: metric changes, new bests in the period,
    like-for-like distance change, consistency. Never empty."""
    current_n, previous_n = body["current_n"], body["previous_n"]
    period = body.get("period") or {"mode": "window"}
    pinned = []
    if current_n == 0:
        return [{"tone": "neutral", "text": "No runs in this period"}]
    if current_n == 1 and (period["mode"] == "dates" or previous_n == 0):
        pinned.append({"tone": "neutral", "text": "Only one run in this period"})
    if previous_n == 0:
        pinned.append({"tone": "neutral", "text": "No runs in the previous period to compare "
                                                  "with" if period["mode"] == "dates" else
                       "No earlier runs to compare with yet"})
    items = []
    rows = {m["key"]: m for m in body["metrics"]}
    for key in HIGHLIGHT_ORDER:
        row = rows.get(key)
        if row is None or row["better"] is None:
            continue
        text = metric_text(row)
        if text:
            items.append({"tone": "good" if row["better"] else "bad", "text": text})
    if history_n:
        for key, best in (body.get("bests") or {}).items():
            if best and best.get("new") and best.get("value") is not None:
                when = f" ({best['date']})" if best.get("date") else ""
                items.append({"tone": "good",
                              "text": f"New best: {BEST_TEXT[key](best['value'])}{when}"})
    buckets = [b for b in body.get("distance_buckets") or []
               if b["current_n"] and b["previous_n"]
               and not (b["current_n"] == current_n and b["previous_n"] == previous_n)]
    for b in sorted(buckets, key=lambda b: -b["current_n"]):
        pace = next((m for m in b["metrics"] if m["key"] == "run_pace"), None)
        if pace and pace["better"] is not None:
            items.append({"tone": "good" if pace["better"] else "bad",
                          "text": f"{b['label']} runs: {metric_text(pace)[0].lower()}"
                                  f"{metric_text(pace)[1:]} ({b['current_n']} vs "
                                  f"{b['previous_n']} runs)"})
            break
    consistency = _consistency(period) if previous_n else None
    if consistency:
        items.append(consistency)
    if not items and previous_n:
        items.append({"tone": "neutral", "text": "Much the same as before — no measure moved "
                                                 "more than 1%"})
    order = {"good": 0, "bad": 1, "neutral": 2}
    items.sort(key=lambda i: order[i["tone"]])
    return items[:MAX_HIGHLIGHTS - len(pinned)] + pinned
