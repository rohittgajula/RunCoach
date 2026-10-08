"""GET /progress/ and POST /progress/review/ (R8 §C). Rows in, analysis/progress.py
does the maths; the AI review is written from that payload only."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass

from django.core.cache import cache

from analysis import progress as maths

from .models import Activity

HISTORY_DAYS = 365
MAX_RUNS = 300
FASTEST_KM_CACHE_S = 30 * 24 * 3600


def fastest_1k_s(activity: Activity) -> float | None:
    """Quickest 1000 m anywhere in the run, from the distance stream (two pointers).
    Cached per activity and segmentation version — the stream does not change."""
    from .quality import effective_use, series

    use = effective_use(activity)
    key = f"progress:fastest1k:{activity.pk}:{activity.segmentation_version}:{use}"
    hit = cache.get(key)
    if hit is not None:
        return hit or None
    points = [(r["offset_s"], r["distance_m"]) for r in series(activity, ("distance_m",),
                                                                use=use)
              if r["distance_m"] is not None]
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


def run_dicts(athlete, sport: str = "running", since: dt.date | None = None,
              until: dt.date | None = None, limit: int = MAX_RUNS) -> list[dict]:
    since = since or athlete.local_today - dt.timedelta(days=HISTORY_DAYS)
    word = "run" if sport == "running" else sport
    qs = Activity.objects.filter(athlete=athlete, sport__icontains=word, local_date__gte=since)
    if until is not None:
        qs = qs.filter(local_date__lte=until)
    qs = qs.exclude(quality__decision="exclude")      # R17: only the athlete's explicit choice
    acts = list(qs.select_related("metrics").prefetch_related("segments")
                .order_by("-started_at")[:limit])
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


MAX_RUNS_DATES = 600
MAX_RANGE_DAYS = 730


@dataclass(frozen=True)
class DateRange:
    """R9 §D: [start, end] against [compare_start, compare_end] (default: the
    same-length period just before)."""
    start: dt.date
    end: dt.date
    compare_start: dt.date
    compare_end: dt.date

    @classmethod
    def build(cls, start, end, compare_start=None, compare_end=None) -> "DateRange":
        if compare_start is None:
            length = (end - start).days + 1
            compare_end = start - dt.timedelta(days=1)
            compare_start = start - dt.timedelta(days=length)
        return cls(start, end, compare_start, compare_end)

    @property
    def key(self) -> str:
        """The review cache key for this comparison."""
        return (f"dates:{self.start.isoformat()}:{self.end.isoformat()}:"
                f"{self.compare_start.isoformat()}:{self.compare_end.isoformat()}")


def review_key(window: int | None, dates: DateRange | None):
    return dates.key if dates is not None else window


def progress_payload(athlete, window: int | None, sport: str = "running",
                     dates: DateRange | None = None) -> dict:
    from .progress_ai import review_state

    if dates is None:
        body = maths.progress(run_dicts(athlete, sport), window)
    else:
        # Reach back a year before the earlier side too, so "new best" means a best
        # against the history before the period, as in window mode.
        since = min(dates.start, dates.compare_start) - dt.timedelta(days=HISTORY_DAYS)
        runs = run_dicts(athlete, sport, since=since, until=max(dates.end, dates.compare_end),
                         limit=MAX_RUNS_DATES)
        body = maths.progress_dates(runs, dates.start.isoformat(), dates.end.isoformat(),
                                    dates.compare_start.isoformat(),
                                    dates.compare_end.isoformat())
    body["sport"] = sport
    body["today"] = athlete.local_today
    body["review"] = review_state(athlete, review_key(window, dates))
    return body


def ai_payload(body: dict) -> dict:
    """The comparison without the per-run series: aggregates only."""
    return {"window": body["window"], "today": str(body["today"]),
            "period": body.get("period"), "highlights": body.get("highlights"),
            "current_n": body["current_n"], "previous_n": body["previous_n"],
            "metrics": body["metrics"], "bests": body["bests"], "focus": body["focus"],
            "distance_buckets": [b for b in body["distance_buckets"] if b["current_n"]]}


def dumps(payload: dict) -> str:
    return json.dumps(payload, indent=2, default=str)
