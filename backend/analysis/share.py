"""R15 §D: numbers for a run's share image. Pure: no Django."""

from __future__ import annotations

PARTIAL_MIN_M = 100


def title_for(hour: int) -> str:
    if 5 <= hour < 11:
        return "Morning run"
    if 11 <= hour < 14:
        return "Lunch run"
    if 14 <= hour < 17:
        return "Afternoon run"
    if 17 <= hour < 21:
        return "Evening run"
    return "Night run"


def km_splits(samples: list[tuple[float, float | None, int | None]]) -> list[dict]:
    """samples: [(offset_s, distance_m, heart_rate)] oldest first.
    → [{km, pace_s, hr, distance_m, partial}] — whole km, then a last partial split of
    ≥ 100 m with its pace normalised to per km."""
    splits: list[dict] = []
    start_t, start_d = 0.0, 0.0
    next_km = 1000.0
    hrs: list[int] = []
    last_t, last_d = 0.0, 0.0
    for t, d, hr in samples:
        if d is None:
            continue
        if hr:
            hrs.append(hr)
        while d >= next_km:
            # Interpolate the moment the km boundary was crossed.
            if d > last_d:
                cross = last_t + (t - last_t) * (next_km - last_d) / (d - last_d)
            else:
                cross = t
            splits.append({"km": int(next_km // 1000), "pace_s": int(round(cross - start_t)),
                           "hr": int(round(sum(hrs) / len(hrs))) if hrs else None,
                           "distance_m": 1000.0, "partial": False})
            start_t, start_d = cross, next_km
            next_km += 1000.0
            hrs = []
        last_t, last_d = t, d
    rest = last_d - start_d
    if rest >= PARTIAL_MIN_M and last_t > start_t:
        splits.append({"km": len(splits) + 1,
                       "pace_s": int(round((last_t - start_t) / rest * 1000)),
                       "hr": int(round(sum(hrs) / len(hrs))) if hrs else None,
                       "distance_m": round(rest, 1), "partial": True})
    return splits


def best_km(splits: list[dict]) -> dict | None:
    whole = [s for s in splits if not s["partial"] and s["pace_s"] > 0]
    if not whole:
        return None
    best = min(whole, key=lambda s: (s["pace_s"], s["km"]))
    return {"km": best["km"], "pace_s": best["pace_s"]}
