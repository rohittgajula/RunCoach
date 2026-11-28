""""Am I improving?" report. Pure.

Answers two separate questions, because a beginner building an aerobic base can be
doing the first right long before the second shows:

* **Control** — is he running easy enough? Time in zone 4-5 and HR in the running parts.
* **Fitness** — is the engine better? Metres per heartbeat in the running parts and
  resting HR. Metres per heartbeat = running speed / heart rate: how far one beat
  carries you. It rises as the aerobic base grows.

Everything comes from the *running* parts of a run/walk (ActivityMetrics), so walk
breaks never flatter or hide anything. Indoor / treadmill runs are left out: without
a calibrated foot pod their pace (and so metres per heartbeat) is not real.

A run is a dict: date (ISO), sport, total_s, total_m, run_s, run_pace_s (s/km),
run_hr, max_hr, zones ({below, Z1..Z5: seconds}), longest_run_s. Oldest first.
"""

from __future__ import annotations

import datetime as dt
import statistics

SHORT_RUN_S = 10 * 60          # flagged (kept in, shown greyed) below this
MPB_MIN_CHANGE = 0.03          # 3 %: smaller changes in metres per beat are noise
HR_MIN_CHANGE = 2              # bpm
Z45_MIN_CHANGE = 3             # percentage points
RHR_MIN_CHANGE = 1.0           # bpm, monthly median
GAP_DAYS = 14                  # a break this long resets some progress


def is_indoor(sport: str | None) -> bool:
    s = (sport or "").lower()
    return "treadmill" in s or "indoor" in s


def _mpb(run: dict) -> float | None:
    pace, hr = run.get("run_pace_s"), run.get("run_hr")
    if not pace or not hr:
        return None
    return round((1000 / pace) / (hr / 60), 2)


def _pct(zones: dict, *names: str) -> float | None:
    total = sum(v or 0 for v in (zones or {}).values())
    if not total:
        return None
    return round(100 * sum((zones or {}).get(n) or 0 for n in names) / total)


def run_row(run: dict) -> dict:
    zones = run.get("zones") or {}
    return {
        "date": run["date"],
        "total_min": round((run.get("total_s") or 0) / 60, 1),
        "total_km": round((run.get("total_m") or 0) / 1000, 2),
        "run_min": round((run.get("run_s") or 0) / 60, 1),
        "run_pace_s": round(run["run_pace_s"]) if run.get("run_pace_s") else None,
        "run_hr": run.get("run_hr"),
        "max_hr": run.get("max_hr"),
        "m_per_beat": _mpb(run),
        "z2_pct": _pct(zones, "Z2"),
        "z45_pct": _pct(zones, "Z4", "Z5"),
        "zones_pct": {k: _pct(zones, k) for k in ("below", "Z1", "Z2", "Z3", "Z4", "Z5")},
        "longest_run_min": round((run.get("longest_run_s") or 0) / 60, 1),
        "short": (run.get("total_s") or 0) < SHORT_RUN_S,
    }


def _avg(rows: list[dict], key: str, digits: int = 1):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(statistics.fmean(vals), digits) if vals else None


def _months_between(first: dt.date, last: dt.date) -> list[str]:
    out, d = [], first.replace(day=1)
    while d <= last:
        out.append(d.strftime("%Y-%m"))
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return out


def month_rows(rows: list[dict], rhr: list[tuple[str, int]]) -> list[dict]:
    if not rows:
        return []
    first = dt.date.fromisoformat(rows[0]["date"])
    last = dt.date.fromisoformat(rows[-1]["date"])
    out = []
    for month in _months_between(first, last):
        m_rows = [r for r in rows if r["date"].startswith(month)]
        m_rhr = [v for d, v in rhr if d.startswith(month) and v]
        out.append({
            "month": month, "runs": len(m_rows),
            "run_hr": _avg(m_rows, "run_hr"), "max_hr": _avg(m_rows, "max_hr"),
            "m_per_beat": _avg(m_rows, "m_per_beat", 2), "z45_pct": _avg(m_rows, "z45_pct"),
            "z2_pct": _avg(m_rows, "z2_pct"), "run_pace_s": _avg(m_rows, "run_pace_s", 0),
            "run_min": _avg(m_rows, "run_min"),
            "rhr": round(statistics.median(m_rhr), 1) if m_rhr else None,
        })
    return out


def _change(key: str, start, end, *, lower_is_better: bool, min_change: float,
            relative: bool = False) -> dict:
    if start is None or end is None:
        return {"key": key, "start": start, "end": end, "status": "unknown"}
    delta = end - start
    size = abs(delta) / start if relative and start else abs(delta)
    if size < min_change:
        status = "flat"
    else:
        status = "better" if (delta < 0) == lower_is_better else "worse"
    return {"key": key, "start": start, "end": end, "status": status}


def gaps(rows: list[dict], today: dt.date) -> list[dict]:
    """Breaks of GAP_DAYS or more between runs (and since the last run)."""
    dates = [dt.date.fromisoformat(r["date"]) for r in rows]
    out = []
    for a, b in zip(dates, dates[1:]):
        if (b - a).days >= GAP_DAYS:
            out.append({"from": a.isoformat(), "to": b.isoformat(), "days": (b - a).days})
    if dates and (today - dates[-1]).days >= GAP_DAYS:
        out.append({"from": dates[-1].isoformat(), "to": None, "days": (today - dates[-1]).days})
    return out


def verdict(control: str, fitness: str) -> dict:
    if control == "better" and fitness == "better":
        return {"key": "both", "title": "Yes, you're improving.",
                "text": "You run easier and your aerobic engine is better: each heartbeat "
                        "carries you further than when you started. Keep the same easy effort."}
    if control == "better":
        return {"key": "control", "title": "You're running more under control. You're not measurably fitter yet.",
                "text": "Your heart rate while running is lower and you spend less time in the hard "
                        "zones. Fitness (metres per heartbeat) hasn't moved yet. That usually takes "
                        "6–8 weeks of running without breaks."}
    if fitness == "better":
        return {"key": "fitness", "title": "You're getting fitter.",
                "text": "Each heartbeat carries you further. Watch the hard-zone time so easy runs stay easy."}
    if control == "worse":
        return {"key": "harder", "title": "Your runs are getting harder, not easier.",
                "text": "More time in the hard zones than before. Slow down or take more walk breaks "
                        "until your heart rate stays in your easy range."}
    return {"key": "early", "title": "No clear change yet.",
            "text": "Not enough steady running to see a trend. Keep 3 easy runs a week without "
                    "breaks and check again in 4 weeks."}


def report(runs: list[dict], rhr: list[tuple[str, int]], today: dt.date,
           easy_band: tuple[int, int] | None = None) -> dict:
    outdoor = [r for r in runs if not is_indoor(r.get("sport"))]
    rows = [run_row(r) for r in outdoor]
    months = month_rows(rows, rhr)
    with_runs = [m for m in months if m["runs"]]
    base = {"runs": rows, "months": months, "excluded_indoor": len(runs) - len(outdoor),
            "easy_band": list(easy_band) if easy_band else None,
            "gaps": gaps(rows, today), "first": rows[0]["date"] if rows else None,
            "last": rows[-1]["date"] if rows else None}
    if len(with_runs) < 2:
        return {**base, "status": "not_enough", "changes": [], "verdict": verdict("unknown", "unknown")}

    a, b = with_runs[0], with_runs[-1]
    changes = [
        _change("z45_pct", a["z45_pct"], b["z45_pct"], lower_is_better=True, min_change=Z45_MIN_CHANGE),
        _change("run_hr", a["run_hr"], b["run_hr"], lower_is_better=True, min_change=HR_MIN_CHANGE),
        _change("m_per_beat", a["m_per_beat"], b["m_per_beat"], lower_is_better=False,
                min_change=MPB_MIN_CHANGE, relative=True),
        _change("run_pace_s", a["run_pace_s"], b["run_pace_s"], lower_is_better=True,
                min_change=0.03, relative=True),
        _change("rhr", a["rhr"], b["rhr"], lower_is_better=True, min_change=RHR_MIN_CHANGE),
        _change("max_hr", a["max_hr"], b["max_hr"], lower_is_better=True, min_change=HR_MIN_CHANGE),
    ]
    by = {c["key"]: c["status"] for c in changes}
    control = "better" if "better" in (by["z45_pct"], by["run_hr"]) and "worse" not in (
        by["z45_pct"],) else ("worse" if by["z45_pct"] == "worse" else "flat")
    fitness = "better" if by["m_per_beat"] == "better" or by["rhr"] == "better" else "flat"
    mpb_now = b["m_per_beat"]
    return {**base, "status": "ok", "from_month": a["month"], "to_month": b["month"],
            "changes": changes, "verdict": verdict(control, fitness),
            "mpb_goal": [round(mpb_now + 0.05, 2), round(mpb_now + 0.10, 2)] if mpb_now else None}
