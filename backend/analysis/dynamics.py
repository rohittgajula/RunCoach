"""Running dynamics and respiration, averaged over the right samples.

Stride length, vertical oscillation and ground contact are averaged over RUN blocks
only: a walking stride is a different movement, and including it makes every form
metric look worse in proportion to how much the athlete walked. Respiration is the
whole activity. Absent sensors give None, never zero.

Pure: samples come in as plain tuples.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DynamicsSample:
    offset_s: float
    cadence_spm: float | None = None
    stride_length_m: float | None = None
    vertical_oscillation_mm: float | None = None
    ground_contact_ms: float | None = None
    respiration_rate: float | None = None
    speed_mps: float | None = None


def _mean(values: list[float], digits: int) -> float | None:
    present = [v for v in values if v is not None and v > 0]
    return round(sum(present) / len(present), digits) if present else None


def _inside(offset: float, windows: list[tuple[float, float]]) -> bool:
    return any(start <= offset < start + duration for start, duration in windows)


def summarise(samples: list[DynamicsSample], run_windows: list[tuple[float, float]]) -> dict:
    """run_windows: (start_offset_s, duration_s) of each run block."""
    running = [s for s in samples if _inside(s.offset_s, run_windows)]
    cadences = [s.cadence_spm for s in running if s.cadence_spm]
    oscillation = _mean([s.vertical_oscillation_mm for s in running], 1)
    stride = _mean([s.stride_length_m for s in running], 2)
    if stride is None:
        # Watches without running dynamics still record speed and cadence, and stride
        # length is exactly their ratio (metres per minute / steps per minute).
        stride = _mean([s.speed_mps * 60 / s.cadence_spm for s in running
                        if s.speed_mps and s.cadence_spm], 2)
    return {
        "max_run_cadence_spm": round(max(cadences)) if cadences else None,
        "avg_stride_length_m": stride,
        "avg_vertical_oscillation_cm": round(oscillation / 10, 1) if oscillation else None,
        "avg_ground_contact_ms": _mean([s.ground_contact_ms for s in running], 0),
        "avg_respiration": _mean([s.respiration_rate for s in samples], 1),
    }
