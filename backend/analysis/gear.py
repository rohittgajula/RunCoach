"""Shoes (R10 §B8): distance and replacement flags. Pure."""

from __future__ import annotations

DEFAULT_RETIRE_KM = 700.0
SOON_FRACTION = 0.9


def status(distance_km: float, retire_km: float | None) -> dict:
    limit = retire_km or DEFAULT_RETIRE_KM
    return {"remaining_km": round(max(limit - distance_km, 0.0), 1),
            "replace_soon": distance_km >= limit * SOON_FRACTION,
            "replace_due": distance_km >= limit}
