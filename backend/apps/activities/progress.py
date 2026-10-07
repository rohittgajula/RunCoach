"""GET /progress/ and POST /progress/review/ (R8 §C). Rows in, analysis/progress.py
does the maths; the AI review is written from that payload only."""

from __future__ import annotations

import datetime as dt
import json

from django.core.cache import cache

from analysis import progress as maths

from .models import Activity, ActivityRecord

HISTORY_DAYS = 365
MAX_RUNS = 300
FASTEST_KM_CACHE_S = 30 * 24 * 3600


def fastest_1k_s(activity: Activity) -> float | None:
    """Quickest 1000 m anywhere in the run, from the distance stream (two pointers).
    Cached per activity and segmentation version — the stream does not change."""
    key = f"progress:fastest1k:{activity.pk}:{activity.segmentation_version}"
    hit = cache.get(key)
    if hit is not None:
        return hit or None
    points = [(t, d) for t, d in ActivityRecord.objects.filter(
        activity=activity, distance_m__isnull=False).values_list("offset_s", "distance_m")]
    best, left = None, 0
    for right in range(len(points)):
        while left < right and points[right][1] - points[left + 1][1] >= 1000:
            left += 1
        if points[right][1] - points[left][1] >= 1000:
            elapsed = points[right][0] - points[left][0]
            if elapsed > 0 and (best is None or elapsed < best):
                best = elapsed
    cache.set(key, round(best, 1) if best else 0, FASTEST_KM_CACHE_S)
    return round(best, 1) if best else None


def _easy_hr(activity, low_pace: float, high_pace: float) -> float | None:
    """Duration-weighted HR over run blocks whose pace sits in the easy band."""
    blocks = [s for s in activity.segments.all() if s.kind == "run" and s.hr_avg
              and s.avg_pace_s_per_km and low_pace <= s.avg_pace_s_per_km <= high_pace]
    seconds = sum(s.duration_s for s in blocks)
    if not seconds:
        return None
    return sum(s.hr_avg * s.duration_s for s in blocks) / seconds


def run_dicts(athlete, sport: str = "running") -> list[dict]:
    since = athlete.local_today - dt.timedelta(days=HISTORY_DAYS)
    word = "run" if sport == "running" else sport
    acts = list(Activity.objects.filter(athlete=athlete, sport__icontains=word,
                                        local_date__gte=since)
                .select_related("metrics").prefetch_related("segments")
                .order_by("-started_at")[:MAX_RUNS])
    acts.reverse()
    low, high = athlete.easy_pace_min - 15, athlete.easy_pace_max + 30
    runs = []
    for a in acts:
        m = getattr(a, "metrics", None)
        if m is None or m.run_block_count <= 0:
            continue
        zones = m.time_in_zone or {}
        zone_total = sum(v or 0 for v in zones.values())
        pace, hr = m.run_pace_s_per_km, m.avg_run_hr or a.avg_hr
        runs.append({
            "id": a.pk, "date": a.local_date.isoformat(),
            "run_km": m.run_distance_m / 1000, "total_km": (a.total_distance_m or 0) / 1000,
            "run_pace": pace, "avg_hr": a.avg_hr, "max_hr": a.max_hr,
            "easy_hr": _easy_hr(a, low, high),
            "efficiency": (60000 / pace) / hr if pace and hr else None,
            "hr_drift": m.hr_drift_percent, "cadence": m.avg_run_cadence_spm,
            "run_fraction": m.run_fraction, "longest_run_s": m.longest_run_s,
            "z2_pct": (zones.get("Z2", 0) or 0) / zone_total * 100 if zone_total else None,
            "fastest_1k_s": fastest_1k_s(a),
        })
    return runs


def progress_payload(athlete, window: int, sport: str = "running") -> dict:
    from .progress_ai import review_state

    body = maths.progress(run_dicts(athlete, sport), window)
    body["sport"] = sport
    body["today"] = athlete.local_today
    body["review"] = review_state(athlete, window)
    return body


def ai_payload(body: dict) -> dict:
    """The comparison without the per-run series: aggregates only."""
    return {"window": body["window"], "today": str(body["today"]),
            "current_n": body["current_n"], "previous_n": body["previous_n"],
            "metrics": body["metrics"], "bests": body["bests"], "focus": body["focus"],
            "distance_buckets": [b for b in body["distance_buckets"] if b["current_n"]]}


def dumps(payload: dict) -> str:
    return json.dumps(payload, indent=2, default=str)
