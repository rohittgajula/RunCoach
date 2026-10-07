"""Running form trends (R10 §B5): cadence, ground contact, vertical oscillation and
stride length per run, and the last 5 runs against the 5 before. Pure."""

from __future__ import annotations

import datetime as dt

from .insights import slope_per_week

WINDOW = 5
NOISE_PCT = 1.0
CADENCE_TARGET = 168

# key -> (run field, label, unit, digits)
METRICS = {
    "cadence": ("cadence_spm", "Cadence", "spm", 0),
    "ground_contact": ("ground_contact_ms", "Ground contact time", "ms", 0),
    "vertical_oscillation": ("vertical_oscillation_cm", "Vertical oscillation", "cm", 1),
    "stride_length": ("stride_length_m", "Stride length", "m", 2),
}
DYNAMICS = ("ground_contact_ms", "vertical_oscillation_cm", "stride_length_m")


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _better(key: str, current: float, previous: float) -> bool | None:
    if not previous or abs(current - previous) / abs(previous) * 100 < NOISE_PCT:
        return None
    if key == "cadence":
        closer = abs(current - CADENCE_TARGET) < abs(previous - CADENCE_TARGET)
        same = abs(current - CADENCE_TARGET) == abs(previous - CADENCE_TARGET)
        return None if same else closer
    if key in ("ground_contact", "vertical_oscillation"):
        return current < previous
    return None                     # stride length: neither good nor bad by itself


def metric_rows(runs: list[dict]) -> list[dict]:
    """runs oldest first, each with the METRICS fields and a `date` (ISO string)."""
    rows = []
    for key, (field, label, unit, digits) in METRICS.items():
        valued = [r for r in runs if r.get(field) is not None]
        current = _mean([r[field] for r in valued[-WINDOW:]])
        previous = _mean([r[field] for r in valued[-2 * WINDOW:-WINDOW]])
        change = better = None
        if current is not None and previous is not None:
            change = round(current - previous, digits) if digits else round(current - previous)
            better = _better(key, current, previous)
        slope = slope_per_week([(dt.date.fromisoformat(r["date"]), r[field]) for r in valued])

        def rnd(v):
            if v is None:
                return None
            return round(v, digits) if digits else round(v)

        rows.append({"key": key, "label": label, "unit": unit, "current": rnd(current),
                     "previous": rnd(previous), "change": change, "better": better,
                     "trend_per_week": round(slope, 2) if slope is not None else None,
                     "n": len(valued)})
    return rows


def has_dynamics(runs: list[dict]) -> bool:
    return any(r.get(f) is not None for r in runs for f in DYNAMICS)
