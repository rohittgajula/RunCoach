"""Synthetic per-second streams for the R17 data-quality tests (no wall clock)."""

from analysis.data_quality import QSample

M_PER_DEG_LAT = 111_320.0


def run_stream(seconds=1800, speed=2.8, cadence=165.0, hr_start=130, hr_end=150,
               lat0=12.97, lon0=77.59):
    out = []
    for t in range(seconds):
        dist = speed * t
        # Real wrist HR wobbles a beat or two; a perfectly smooth line would read as frozen.
        hr = round(hr_start + (hr_end - hr_start) * t / max(1, seconds - 1)) + (t * 7) % 3 - 1
        out.append(QSample(offset_s=float(t), distance_m=dist, speed_mps=speed,
                           cadence_spm=cadence, heart_rate=hr,
                           latitude=lat0 + dist / M_PER_DEG_LAT, longitude=lon0))
    return out
