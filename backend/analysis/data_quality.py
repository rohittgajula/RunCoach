"""Bad-data filter (R17 §2): optical-HR and GPS artefacts in one activity. Pure.

Raw samples go in; a cleaned copy of the series, the flags, a 0–100 quality score and
the metrics affected come out. The raw samples are never changed — the caller stores
only the summary and recomputes the cleaned series from the raw rows when it needs it.

Nothing here decides to drop a run from anything. A low score only *suggests* leaving
the run out of trends; the athlete decides (Rohit: "sometimes they might be true").

Rules (every duration is measured on the sample clock, so 1 Hz and smart recording
behave the same):

* hr_cadence_lock — |HR − cadence| ≤ 5 continuously for more than 60 s at a running
  cadence (≥ 120 spm): the wrist sensor is counting steps. HR masked over the span.
* hr_spike — HR moves more than 25 bpm in under 5 s with no matching pace change (speed
  changes < 15 %) and comes back within 10 bpm of where it was inside 60 s. HR is
  interpolated across it. A jump that does not come back is left alone: it is real.
* hr_flatline — the same HR value for 120 s or more while moving: the sensor froze. Masked.
* hr_above_max — HR above the athlete's max HR + 3 (220 when unknown). Masked.
* gps_teleport — more than 50 m between samples at most 1.5 s apart. Position masked;
  a distance increment that big is replaced by a plausible one.
* gps_speed — implied speed above 7 m/s (foot sports only). As above.
* gps_drift — stopped (cadence < 30) for 30 s or more while distance grows ≥ 25 m: the
  position wandered. Distance held flat, speed 0.
* pause_mismarked — stationary for 60 s or more while the timer ran, or a recording gap
  of 10 s or more across which you moved ≥ 20 m. Flagged only; nothing changes.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

VERSION = 1

LOCK_TOLERANCE = 5
LOCK_MIN_S = 60.0
LOCK_MIN_CADENCE = 120.0
SPIKE_BPM = 25
SPIKE_WITHIN_S = 5.0
SPIKE_RETURN_BPM = 10
SPIKE_RETURN_S = 60.0
SPIKE_PACE_MATCH = 0.15
FLAT_MIN_S = 120.0
MAX_HR_TOLERANCE = 3
DEFAULT_HR_LIMIT = 220
TELEPORT_M = 50.0
TELEPORT_DT_S = 1.5
RUNNER_MAX_MPS = 7.0
STOP_CADENCE = 30.0
DRIFT_MIN_S = 30.0
DRIFT_MIN_M = 25.0
STATIONARY_MPS = 0.3
PAUSE_MIN_S = 60.0
GAP_MIN_S = 10.0
GAP_MIN_M = 20.0
MAX_SAMPLE_WEIGHT_S = 5.0
EXCLUDE_BELOW = 50

HR_KINDS = ("hr_cadence_lock", "hr_spike", "hr_flatline", "hr_above_max")
GPS_KINDS = ("gps_speed", "gps_teleport", "gps_drift")
PAUSE_KINDS = ("pause_mismarked",)
AFFECTS = {
    "hr": ["avg_hr", "hr_drift", "time_in_zone", "heart_adaptation"],
    "gps": ["pace", "distance", "splits", "route", "records"],
    "pause": ["pace"],
}
INFO = ("Wrist heart-rate sensors sometimes lock onto your step rate or spike, and GPS "
        "can jump between buildings. RunCoach spots these and can fix them in a copy of "
        "the data — your original recording is never changed. A low score only suggests "
        "leaving the run out of trends; you decide.")


@dataclass(slots=True)
class QSample:
    offset_s: float
    distance_m: float | None = None
    speed_mps: float | None = None
    cadence_spm: float | None = None
    heart_rate: int | None = None
    latitude: float | None = None
    longitude: float | None = None


@dataclass
class Flag:
    kind: str
    start_s: float
    end_s: float
    severity: str
    fix: str
    text: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "start_s": round(self.start_s, 1),
                "end_s": round(self.end_s, 1), "severity": self.severity,
                "fix": self.fix, "text": self.text}


@dataclass
class Cleaned:
    """The cleaned series, index-aligned with the input samples."""
    heart_rate: list[float | None] = field(default_factory=list)
    hr_fixed: list[bool] = field(default_factory=list)
    distance_m: list[float | None] = field(default_factory=list)
    speed_mps: list[float | None] = field(default_factory=list)
    latitude: list[float | None] = field(default_factory=list)
    longitude: list[float | None] = field(default_factory=list)
    gps_fixed: list[bool] = field(default_factory=list)


@dataclass
class Result:
    flags: list[Flag]
    cleaned: Cleaned
    score: int
    counts: dict[str, int]
    hr_fixed_s: int
    gps_fixed_s: int
    hr_fixed_pct: int
    gps_fixed_pct: int
    affected: list[str]
    use_default: str              # cleaned | raw
    use_suggestion: str | None    # cleaned | None
    suggestion: str | None        # exclude | None
    suggestion_reason: str | None
    summary: str

    def summary_dict(self) -> dict:
        return {"version": VERSION, "score": self.score,
                "flags": [f.as_dict() for f in self.flags], "counts": self.counts,
                "hr_fixed_s": self.hr_fixed_s, "gps_fixed_s": self.gps_fixed_s,
                "hr_fixed_pct": self.hr_fixed_pct, "gps_fixed_pct": self.gps_fixed_pct,
                "affected": self.affected, "use_default": self.use_default,
                "use_suggestion": self.use_suggestion, "suggestion": self.suggestion,
                "suggestion_reason": self.suggestion_reason, "summary": self.summary}


def hr_limit_for(max_hr: int | None) -> int:
    return int(max_hr) + MAX_HR_TOLERANCE if max_hr else DEFAULT_HR_LIMIT


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _weights(samples: list[QSample]) -> list[float]:
    out = []
    for i, s in enumerate(samples):
        if i + 1 < len(samples):
            out.append(max(0.0, min(MAX_SAMPLE_WEIGHT_S, samples[i + 1].offset_s - s.offset_s)))
        else:
            out.append(1.0)
    return out


def _runs(indices: list[int]) -> list[tuple[int, int]]:
    """Consecutive index runs → [(first, last)]."""
    out: list[tuple[int, int]] = []
    for i in indices:
        if out and i == out[-1][1] + 1:
            out[-1] = (out[-1][0], i)
        else:
            out.append((i, i))
    return out


def _span_s(samples, a, b) -> float:
    return samples[b].offset_s - samples[a].offset_s


def _minutes(seconds: float) -> str:
    if seconds < 90:
        return f"{round(seconds)} s"
    return f"{round(seconds / 60)} min"


def _speed_around(samples, t0, t1) -> float | None:
    values = [s.speed_mps for s in samples
              if s.speed_mps is not None and t0 <= s.offset_s <= t1]
    return statistics.mean(values) if values else None


def _moving(s: QSample) -> bool:
    return (s.speed_mps or 0) > 0.5 or (s.cadence_spm or 0) >= STOP_CADENCE


# --- heart rate ---------------------------------------------------------------------

def _hr_rules(samples, hr_limit, flags) -> tuple[list[float | None], list[bool]]:
    n = len(samples)
    hr: list[float | None] = [float(s.heart_rate) if s.heart_rate else None for s in samples]
    fixed = [False] * n

    # Above max.
    above = [i for i in range(n) if hr[i] is not None and hr[i] > hr_limit]
    for a, b in _runs(above):
        for i in range(a, b + 1):
            hr[i], fixed[i] = None, True
        flags.append(Flag("hr_above_max", samples[a].offset_s, samples[b].offset_s,
                          "medium", "masked",
                          f"Heart rate read above your max ({hr_limit - MAX_HR_TOLERANCE} "
                          f"bpm) — left out."))

    # Cadence lock.
    locked = [i for i in range(n)
              if hr[i] is not None and samples[i].cadence_spm is not None
              and samples[i].cadence_spm >= LOCK_MIN_CADENCE
              and abs(hr[i] - samples[i].cadence_spm) <= LOCK_TOLERANCE]
    for a, b in _runs(locked):
        span = _span_s(samples, a, b)
        if span <= LOCK_MIN_S:
            continue
        for i in range(a, b + 1):
            hr[i], fixed[i] = None, True
        flags.append(Flag("hr_cadence_lock", samples[a].offset_s, samples[b].offset_s,
                          "high" if span >= 300 else "medium", "masked",
                          f"Heart rate locked onto your step rate for {_minutes(span)} — "
                          f"left out."))

    # Flat line.
    i = 0
    while i < n:
        if hr[i] is None or not _moving(samples[i]):
            i += 1
            continue
        j = i
        while j + 1 < n and hr[j + 1] == hr[i] and _moving(samples[j + 1]):
            j += 1
        span = _span_s(samples, i, j)
        if span >= FLAT_MIN_S:
            for k in range(i, j + 1):
                hr[k], fixed[k] = None, True
            flags.append(Flag("hr_flatline", samples[i].offset_s, samples[j].offset_s,
                              "medium", "masked",
                              f"Heart rate stuck at one value for {_minutes(span)} — "
                              f"left out."))
        i = j + 1

    # Spikes (on what is left).
    valid = [k for k in range(n) if hr[k] is not None]
    pos = 0
    while pos < len(valid):
        i = valid[pos]
        t_i = samples[i].offset_s
        jump = None
        q = pos + 1
        while q < len(valid) and samples[valid[q]].offset_s - t_i < SPIKE_WITHIN_S:
            if abs(hr[valid[q]] - hr[i]) > SPIKE_BPM:
                jump = q
                break
            q += 1
        if jump is None:
            pos += 1
            continue
        j = valid[jump]
        before = _speed_around(samples, t_i - 5, t_i)
        after = _speed_around(samples, samples[j].offset_s, samples[j].offset_s + 5)
        if before and after and abs(after - before) / max(before, 0.1) >= SPIKE_PACE_MATCH:
            pos += 1                      # pace changed too: a real effort change
            continue
        back = None
        r = jump + 1
        while r < len(valid) and samples[valid[r]].offset_s - t_i <= SPIKE_RETURN_S:
            if abs(hr[valid[r]] - hr[i]) <= SPIKE_RETURN_BPM:
                back = r
                break
            r += 1
        if back is None:
            pos += 1                      # it stayed: real, leave it
            continue
        k = valid[back]
        t0, t1 = samples[i].offset_s, samples[k].offset_s
        for m in range(i + 1, k):
            frac = (samples[m].offset_s - t0) / (t1 - t0) if t1 > t0 else 0
            hr[m] = round(hr[i] + (hr[k] - hr[i]) * frac, 1)
            fixed[m] = True
        flags.append(Flag("hr_spike", samples[i + 1].offset_s, samples[k - 1].offset_s
                          if k - 1 > i else samples[i + 1].offset_s, "low", "interpolated",
                          "A short heart-rate spike that your pace didn't match — "
                          "smoothed over."))
        pos = back
    # Masked samples inside the lock/flat spans are None; that is the "masked" fix.
    return hr, fixed


# --- GPS ----------------------------------------------------------------------------

def _plausible_increment(samples, speeds, i, dt, foot) -> float:
    s = samples[i].speed_mps
    limit = RUNNER_MAX_MPS if foot else 60.0
    if s is not None and 0 <= s <= limit:
        return s * dt
    recent = [v for v in speeds[max(0, i - 10):i] if v is not None and 0 <= v <= limit]
    return (statistics.median(recent) if recent else 0.0) * dt


def _gps_rules(samples, foot, flags, cleaned: Cleaned) -> None:
    n = len(samples)
    lat = [s.latitude for s in samples]
    lon = [s.longitude for s in samples]
    speed = [s.speed_mps for s in samples]
    fixed = [False] * n
    limit = RUNNER_MAX_MPS if foot else None

    # Positions.
    teleport, fast = [], []
    last = None
    for i in range(n):
        if lat[i] is None or lon[i] is None:
            continue
        if last is not None:
            d = haversine_m(lat[last], lon[last], lat[i], lon[i])
            dt = samples[i].offset_s - samples[last].offset_s
            if dt <= TELEPORT_DT_S and d > TELEPORT_M:
                teleport.append(i)
                continue
            if limit and dt > 0 and d / dt > limit:
                fast.append(i)
                continue
        last = i

    # Recorded speed.
    for i in range(n):
        if limit and speed[i] is not None and speed[i] > limit:
            fast.append(i)
            fixed[i] = True

    # Distance stream: increments that are impossible.
    dist = [s.distance_m for s in samples]
    new_dist: list[float | None] = list(dist)
    running = None
    prev_raw = None
    prev_t = None
    for i in range(n):
        if dist[i] is None:
            continue
        if running is None:
            running, prev_raw, prev_t = dist[i], dist[i], samples[i].offset_s
            new_dist[i] = running
            continue
        inc = dist[i] - prev_raw
        dt = samples[i].offset_s - prev_t
        bad = False
        if dt <= TELEPORT_DT_S and inc > TELEPORT_M:
            bad = True
            teleport.append(i)
        elif limit and dt > 0 and inc / dt > limit and dt < GAP_MIN_S:
            bad = True
            fast.append(i)
        if bad:
            inc = _plausible_increment(samples, speed, i, dt, foot)
            fixed[i] = True
        running += max(inc, 0.0)
        new_dist[i] = running
        prev_raw, prev_t = dist[i], samples[i].offset_s

    for i in set(teleport) | set(fast):
        lat[i] = lon[i] = None
        fixed[i] = True
        if limit and speed[i] is not None and speed[i] > limit:
            speed[i] = None

    # Interpolate masked speeds from neighbours.
    for i in range(n):
        if fixed[i] and speed[i] is not None and limit and speed[i] > limit:
            speed[i] = None
    for i in range(n):
        if fixed[i] and speed[i] is None and samples[i].speed_mps is not None:
            prev = next((speed[k] for k in range(i - 1, -1, -1) if speed[k] is not None
                         and not fixed[k]), None)
            nxt = next((speed[k] for k in range(i + 1, n) if speed[k] is not None
                        and not fixed[k]), None)
            vals = [v for v in (prev, nxt) if v is not None]
            speed[i] = round(statistics.mean(vals), 3) if vals else None

    for kind, idx in (("gps_teleport", sorted(set(teleport))),
                      ("gps_speed", sorted(set(fast) - set(teleport)))):
        for a, b in _runs(idx):
            text = ("GPS jumped " + ("more than 50 m in a second" if kind == "gps_teleport"
                                     else "faster than anyone runs")
                    + " — that bit of track and distance was corrected.")
            flags.append(Flag(kind, samples[a].offset_s, samples[b].offset_s,
                              "medium" if b - a >= 10 else "low", "masked", text))

    # Stationary drift.
    stopped = [i for i in range(n) if samples[i].cadence_spm is not None
               and samples[i].cadence_spm < STOP_CADENCE]
    for a, b in _runs(stopped):
        if _span_s(samples, a, b) < DRIFT_MIN_S:
            continue
        values = [new_dist[k] for k in range(a, b + 1) if new_dist[k] is not None]
        if len(values) < 2 or values[-1] - values[0] < DRIFT_MIN_M:
            continue
        grown = values[-1] - values[0]
        base = values[0]
        for k in range(a, b + 1):
            if new_dist[k] is not None:
                new_dist[k] = base
            speed[k] = 0.0 if speed[k] is not None else None
            fixed[k] = True
        for k in range(b + 1, n):
            if new_dist[k] is not None:
                new_dist[k] -= grown
        flags.append(Flag("gps_drift", samples[a].offset_s, samples[b].offset_s, "low",
                          "masked", f"You were stopped but GPS wandered {round(grown)} m — "
                          f"that distance was removed."))

    cleaned.distance_m = new_dist
    cleaned.speed_mps = speed
    cleaned.latitude = lat
    cleaned.longitude = lon
    cleaned.gps_fixed = fixed


def _pause_rules(samples, flags) -> None:
    n = len(samples)
    still = [i for i in range(n) if (samples[i].speed_mps is not None
                                     and samples[i].speed_mps < STATIONARY_MPS)
             and (samples[i].cadence_spm is None or samples[i].cadence_spm < STOP_CADENCE)]
    for a, b in _runs(still):
        span = _span_s(samples, a, b)
        if span >= PAUSE_MIN_S:
            flags.append(Flag("pause_mismarked", samples[a].offset_s, samples[b].offset_s,
                              "low", "flagged",
                              f"Stopped for {_minutes(span)} while the timer kept running "
                              f"— your average pace includes it."))
    for i in range(1, n):
        gap = samples[i].offset_s - samples[i - 1].offset_s
        d0, d1 = samples[i - 1].distance_m, samples[i].distance_m
        if gap >= GAP_MIN_S and d0 is not None and d1 is not None and d1 - d0 >= GAP_MIN_M:
            flags.append(Flag("pause_mismarked", samples[i - 1].offset_s, samples[i].offset_s,
                              "low", "flagged",
                              f"The recording paused for {_minutes(gap)} while you kept "
                              f"moving {round(d1 - d0)} m."))


# --- the whole thing ----------------------------------------------------------------

def analyse(samples: list[QSample], *, max_hr: int | None = None,
            foot: bool = True) -> Result:
    samples = sorted(samples, key=lambda s: s.offset_s)
    flags: list[Flag] = []
    cleaned = Cleaned()
    if not samples:
        return _result([], cleaned, [], [], 0, 0)
    hr, hr_fixed = _hr_rules(samples, hr_limit_for(max_hr), flags)
    cleaned.heart_rate, cleaned.hr_fixed = hr, hr_fixed
    _gps_rules(samples, foot, flags, cleaned)
    _pause_rules(samples, flags)
    weights = _weights(samples)
    hr_with = sum(w for s, w in zip(samples, weights) if s.heart_rate)
    hr_bad = sum(w for f, w in zip(hr_fixed, weights) if f)
    gps_with = sum(w for s, w in zip(samples, weights)
                   if s.latitude is not None or s.distance_m is not None)
    gps_bad = sum(w for f, w in zip(cleaned.gps_fixed, weights) if f)
    flags.sort(key=lambda f: (f.start_s, f.kind))
    return _result(samples, cleaned, flags, weights, (hr_bad, hr_with), (gps_bad, gps_with))


def _result(samples, cleaned, flags, weights, hr_pair, gps_pair) -> Result:
    hr_bad, hr_with = hr_pair if isinstance(hr_pair, tuple) else (0, 0)
    gps_bad, gps_with = gps_pair if isinstance(gps_pair, tuple) else (0, 0)
    hr_share = hr_bad / hr_with if hr_with else 0.0
    gps_share = gps_bad / gps_with if gps_with else 0.0
    counts: dict[str, int] = {}
    for f in flags:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    hr_pen = min(60.0, 150 * hr_share)
    gps_pen = min(40.0, 120 * gps_share)
    score = 100 - hr_pen - gps_pen - min(10, 2 * counts.get("hr_spike", 0)) \
        - min(6, 2 * counts.get("pause_mismarked", 0))
    score = max(0, min(100, int(round(score))))
    affected: list[str] = []
    for group, kinds in (("hr", HR_KINDS), ("gps", GPS_KINDS), ("pause", PAUSE_KINDS)):
        if any(counts.get(k) for k in kinds):
            for metric in AFFECTS[group]:
                if metric not in affected:
                    affected.append(metric)
    changing = {f.kind for f in flags if f.fix != "flagged"}
    minor = changing <= {"hr_spike"}
    suggestion = "exclude" if score < EXCLUDE_BELOW else None
    reason = None
    if suggestion:
        reason = "Wrist HR unreliable" if hr_pen >= gps_pen else "GPS unreliable"
    return Result(
        flags=flags, cleaned=cleaned, score=score, counts=counts,
        hr_fixed_s=int(round(hr_bad)), gps_fixed_s=int(round(gps_bad)),
        hr_fixed_pct=int(round(hr_share * 100)), gps_fixed_pct=int(round(gps_share * 100)),
        affected=affected, use_default="cleaned" if minor else "raw",
        use_suggestion=None if minor else "cleaned",
        suggestion=suggestion, suggestion_reason=reason,
        summary=summary_sentence(counts, score))


_NOUNS = {"hr_cadence_lock": ("HR lock", "HR locks"), "hr_spike": ("HR spike", "HR spikes"),
          "hr_flatline": ("frozen HR stretch", "frozen HR stretches"),
          "hr_above_max": ("HR reading above max", "HR readings above max"),
          "gps_speed": ("GPS jump", "GPS jumps"), "gps_teleport": ("GPS teleport", "GPS teleports"),
          "gps_drift": ("GPS drift", "GPS drifts"),
          "pause_mismarked": ("pause issue", "pause issues")}


def describe_counts(counts: dict[str, int]) -> str:
    parts = []
    for kind, (one, many) in _NOUNS.items():
        n = counts.get(kind, 0)
        if n:
            parts.append(f"{n} {one if n == 1 else many}")
    return ", ".join(parts)


def summary_sentence(counts: dict[str, int], score: int) -> str:
    if not counts:
        return "No sensor problems found in this run."
    return f"Found {describe_counts(counts)} (data score {score}/100)."


def status_and_chip(summary: dict, *, decision: str | None, use_choice: str | None
                    ) -> dict:
    """Presentation fields from a stored summary + the athlete's choices."""
    counts = summary.get("counts") or {}
    use = use_choice or summary.get("use_default") or "raw"
    pending = bool((summary.get("suggestion") and decision is None)
                   or (summary.get("use_suggestion") and use_choice is None))
    if not counts:
        status, chip = "clean", "Clean"
    elif pending:
        status = "review"
        reason = summary.get("suggestion_reason")
        chip = (f"Check this run — {reason[0].lower()}{reason[1:]}" if reason
                else "Check this run — fixes available")
    else:
        status = "fixed"
        fixes = {k: v for k, v in counts.items()
                 if k != "pause_mismarked"} if use == "cleaned" else {}
        chip = f"Fixed {describe_counts(fixes)}" if fixes else "Checked"
    if decision == "exclude":
        chip = "Excluded from trends"
    return {"status": status, "chip": chip, "use": use, "pending_review": pending,
            "excluded_from_trends": decision == "exclude"}
