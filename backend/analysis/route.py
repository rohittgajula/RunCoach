"""R11 §E: a run's route for the map — simplified polyline with pace, HR, run/walk
segment, elevation and distance at every kept point. Pure: no Django.

Privacy first: with `hide_m` set (the athlete's "Hide start/end on maps", on by default)
the first and last `hide_m` metres never leave the server.
"""

from __future__ import annotations

import bisect
import math

EARTH_M = 6_371_000.0
MAX_POINTS = 800
OVERLAY_POINTS = 150
HIDE_M = 200
PACE_WINDOW_S = 15
HR_WINDOW_S = 5
ELE_WINDOW_S = 10
SLOWEST_PACE = 1200            # slower than 20:00 /km is standing, not running
FASTEST_PACE = 150             # faster than 2:30 /km is a GPS jump, not a runner


def haversine(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_M * math.asin(min(1.0, math.sqrt(a)))


def project(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Equirectangular metres around the first point (fine at a city's scale)."""
    if not points:
        return []
    lat0 = math.radians(points[0][0])
    k = math.cos(lat0)
    return [(math.radians(lon) * EARTH_M * k, math.radians(lat) * EARTH_M) for lat, lon in points]


def _seg_dist(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def douglas_peucker(xy: list[tuple[float, float]], epsilon: float) -> list[int]:
    """Indices kept by Douglas–Peucker (iterative, so long runs don't recurse deeply)."""
    n = len(xy)
    if n <= 2:
        return list(range(n))
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        first, last = stack.pop()
        best, index = -1.0, None
        for i in range(first + 1, last):
            d = _seg_dist(xy[i], xy[first], xy[last])
            if d > best:
                best, index = d, i
        if index is not None and best > epsilon:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [i for i, k in enumerate(keep) if k]


def simplify(xy: list[tuple[float, float]], max_points: int = MAX_POINTS,
             must_keep: set[int] | None = None, epsilon: float = 1.0) -> list[int]:
    """Grow the tolerance until at most `max_points` remain (`must_keep` always kept)."""
    must_keep = must_keep or set()
    while True:
        kept = sorted(set(douglas_peucker(xy, epsilon)) | must_keep)
        if len(kept) <= max_points or epsilon > 1e6:
            return kept[:max_points] if len(kept) > max_points else kept
        epsilon *= 1.6


def _window_means(times: list[float], values: list, half: float) -> list[float | None]:
    """Mean of non-null values within ±half seconds of each sample (two pointers)."""
    n = len(times)
    out: list[float | None] = []
    lo = hi = 0
    total, count = 0.0, 0
    for i in range(n):
        while hi < n and times[hi] <= times[i] + half:
            if values[hi] is not None:
                total += values[hi]
                count += 1
            hi += 1
        while times[lo] < times[i] - half:
            if values[lo] is not None:
                total -= values[lo]
                count -= 1
            lo += 1
        out.append(total / count if count else None)
    return out


def _paces(times: list[float], dists: list[float], half: float = PACE_WINDOW_S) -> list[int | None]:
    n = len(times)
    out: list[int | None] = []
    lo = hi = 0
    for i in range(n):
        while hi < n - 1 and times[hi + 1] <= times[i] + half:
            hi += 1
        while lo < i and times[lo] < times[i] - half:
            lo += 1
        dt_s, dd = times[hi] - times[lo], dists[hi] - dists[lo]
        if dt_s > 0 and dd > 0:
            pace = 1000 * dt_s / dd
            out.append(round(pace) if FASTEST_PACE <= pace < SLOWEST_PACE else None)
        else:
            out.append(None)
    return out


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def clean(samples: list[dict]) -> list[dict]:
    """Samples with a plausible GPS fix, oldest first, with a monotonic distance."""
    pts = [s for s in samples
           if s.get("lat") is not None and s.get("lon") is not None
           and -90 <= s["lat"] <= 90 and -180 <= s["lon"] <= 180
           and not (s["lat"] == 0 and s["lon"] == 0)]
    pts.sort(key=lambda s: s["t"])
    have_dist = sum(1 for s in pts if s.get("dist") is not None) >= 0.9 * len(pts) if pts else False
    walked = 0.0
    last_dist = 0.0
    out = []
    for i, s in enumerate(pts):
        if i:
            walked += haversine(pts[i - 1]["lat"], pts[i - 1]["lon"], s["lat"], s["lon"])
        dist = s.get("dist") if have_dist and s.get("dist") is not None else (
            last_dist if have_dist else walked)
        dist = max(dist, last_dist)
        last_dist = dist
        out.append({**s, "dist": dist})
    return out


def segment_at(t: float, segments: list[tuple[float, float, str]]) -> str | None:
    """segments = [(start_s, end_s, kind)] sorted by start."""
    if not segments:
        return None
    starts = [s[0] for s in segments]
    i = bisect.bisect_right(starts, t) - 1
    if i >= 0 and segments[i][0] <= t < segments[i][1]:
        return segments[i][2]
    return None


def _empty(reason: str, hidden: bool, trimmed: int, total: float, n: int) -> dict:
    return {"available": False, "reason": reason, "hidden_endpoints": hidden,
            "trimmed_m": trimmed, "total_distance_m": round(total, 1), "sampled_from": n,
            "bounds": None, "start": None, "finish": None, "has_hr": False,
            "has_elevation": False, "has_segments": False, "pace_range": None,
            "hr_range": None, "elevation": None, "km_markers": [], "points": []}


def trim(pts: list[dict], hide_m: float) -> list[dict]:
    if not pts or not hide_m:
        return pts
    total = pts[-1]["dist"]
    return [p for p in pts if hide_m <= p["dist"] <= total - hide_m]


def build(samples: list[dict], segments: list[tuple[float, float, str]] | None = None,
          hide_m: float = HIDE_M, max_points: int = MAX_POINTS) -> dict:
    """samples: [{t, lat, lon, dist, hr, alt}] (dist/hr/alt may be None).
    Returns the R11 route body (without activity_id)."""
    hidden = bool(hide_m)
    trimmed = int(hide_m) if hidden else 0
    pts = clean(samples)
    if len(pts) < 2:
        return _empty("no_gps", hidden, trimmed, 0.0, len(pts))
    total = pts[-1]["dist"]
    times = [p["t"] for p in pts]
    dists = [p["dist"] for p in pts]
    paces = _paces(times, dists)
    hrs = _window_means(times, [p.get("hr") for p in pts], HR_WINDOW_S)
    eles = _window_means(times, [p.get("alt") for p in pts], ELE_WINDOW_S)
    segments = sorted(segments or [])
    for i, p in enumerate(pts):
        p["pace"], p["hr_s"], p["ele"] = paces[i], hrs[i], eles[i]
        p["seg"] = segment_at(p["t"], segments)

    shown = trim(pts, hide_m) if hidden else pts
    if len(shown) < 2:
        return _empty("too_short", hidden, trimmed, total, len(pts))

    # km markers: the first sample at or past each whole km, always kept in the line.
    must = set()
    km_at: dict[int, int] = {}
    next_km = 1
    for i, p in enumerate(shown):
        while p["dist"] >= next_km * 1000:
            if next_km * 1000 >= shown[0]["dist"]:
                km_at[next_km] = i
                must.add(i)
            next_km += 1
    xy = project([(p["lat"], p["lon"]) for p in shown])
    kept = simplify(xy, max_points, must)
    index_of = {orig: new for new, orig in enumerate(kept)}

    out_points = []
    for i in kept:
        p = shown[i]
        out_points.append({
            "lat": round(p["lat"], 6), "lon": round(p["lon"], 6),
            "dist_m": round(p["dist"], 1), "t_s": int(round(p["t"])),
            "pace_s_per_km": p["pace"],
            "hr": int(round(p["hr_s"])) if p["hr_s"] is not None else None,
            "segment": p["seg"],
            "ele_m": round(p["ele"], 1) if p["ele"] is not None else None,
        })
    lats = [p["lat"] for p in out_points]
    lons = [p["lon"] for p in out_points]
    pace_vals = [p["pace"] for p in shown if p["pace"] is not None]
    hr_vals = [p["hr_s"] for p in shown if p["hr_s"] is not None]
    ele_vals = [p["ele"] for p in shown if p["ele"] is not None]
    elevation = None
    if len(ele_vals) >= 2:
        diffs = [b - a for a, b in zip(ele_vals, ele_vals[1:])]
        elevation = {"gain_m": round(sum(d for d in diffs if d > 0), 1),
                     "loss_m": round(-sum(d for d in diffs if d < 0), 1),
                     "min_m": round(min(ele_vals), 1), "max_m": round(max(ele_vals), 1)}
    return {
        "available": True, "reason": None, "hidden_endpoints": hidden, "trimmed_m": trimmed,
        "total_distance_m": round(total, 1), "sampled_from": len(pts),
        "bounds": {"south": min(lats), "west": min(lons), "north": max(lats), "east": max(lons)},
        "start": {"lat": out_points[0]["lat"], "lon": out_points[0]["lon"]},
        "finish": {"lat": out_points[-1]["lat"], "lon": out_points[-1]["lon"]},
        "has_hr": bool(hr_vals), "has_elevation": bool(ele_vals),
        "has_segments": any(p["segment"] for p in out_points),
        "pace_range": ({"min": round(percentile(pace_vals, 0.05)),
                        "max": round(percentile(pace_vals, 0.95))} if pace_vals else None),
        "hr_range": ({"min": round(percentile(hr_vals, 0.05)),
                      "max": round(percentile(hr_vals, 0.95))} if hr_vals else None),
        "elevation": elevation,
        "km_markers": [{"km": km, "lat": round(shown[i]["lat"], 6), "lon": round(shown[i]["lon"], 6),
                        "index": index_of[i]} for km, i in sorted(km_at.items())],
        "points": out_points,
    }


def overlay(samples: list[dict], hide_m: float = HIDE_M,
            max_points: int = OVERLAY_POINTS) -> list[list[float]]:
    """A light [[lat, lon]] line for the "Your routes" overlay (trimmed the same way)."""
    pts = clean(samples)
    if len(pts) < 2:
        return []
    shown = trim(pts, hide_m) if hide_m else pts
    if len(shown) < 2:
        return []
    xy = project([(p["lat"], p["lon"]) for p in shown])
    kept = simplify(xy, max_points, epsilon=5.0)
    return [[round(shown[i]["lat"], 5), round(shown[i]["lon"], 5)] for i in kept]
