"""Heart adaptation, run by run (R14 §9). Pure — no Django.

Rohit's question: "I ran 5 min at 150 bpm on day 1 — how is my heart improving or
adjusting, day by day?" Every number below is computed from the per-second records of
one run and its run/walk blocks (segmentation), RUNNING ONLY:

* **Steady running** — 30-s windows inside run blocks, after the first 5 min of the
  activity (warm-up) and after the first 60 s of each block (HR lag), with steady pace
  (speed coefficient of variation ≤ 12 %), mostly HR-covered, faster than a shuffle.
* **HR at reference pace** — time-weighted mean HR over steady windows whose pace is
  within ±15 s/km of the reference (the middle of the athlete's easy band); needs ≥ 2 min.
* **Pace at reference HR** — time-weighted mean pace over steady windows whose mean HR
  is within ±3 bpm of the reference HR (default 150); needs ≥ 2 min.
* **Efficiency** — steady metres per minute ÷ mean HR (higher = more speed per beat);
  `efficiency_adj` adds 8 m per metre climbed and uses heat-adjusted HR.
* **Aerobic decoupling (Pa:HR)** — efficiency of the first half of the steady running
  vs the second half, as % lost; needs ≥ 10 min steady.
* **HR recovery** — peak HR around the end of a run block (−10 … +20 s) minus HR 60 s
  after the block ended, for blocks ≥ 2 min followed by ≥ 60 s of walking/stopping (or
  data after the last block); median, plus the last block alone (`…_end`).
* **Time to settle** — in run blocks ≥ 4 min, seconds from the block start to the first
  60 s in which HR stays within 6 bpm; median.
* **Run duration under the cap** — the longest continuous running stretch (walk breaks
  end it) with 10-s-smoothed HR ≤ cap. Warm-up included: it is "how long can I run
  before passing 150".

Heat: `hot` when feels-like at the run's start is ≥ 28 °C; HR is heat-adjusted by
1 bpm per °C above 20 °C (a population rule of thumb, labelled as an estimate).
Terrain: elevation gain per running km (smoothed altitude), `hilly` at ≥ 15 m/km.
Wording elsewhere is non-causal: numbers describe change, not its cause.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass

WARMUP_S = 300
BLOCK_LAG_S = 60
WINDOW_S = 30
MIN_WINDOW_COVER_S = 20
MAX_SPEED_CV = 0.12
MIN_RUN_SPEED = 1.4             # m/s (~12:00/km) — slower is a shuffle, not steady running
MIN_HR_SHARE = 0.8
MAX_GAP_S = 10.0
REF_PACE_BAND_S = 15
REF_HR_BAND = 3
MIN_MATCH_S = 120
MIN_EFFICIENCY_S = 300
MIN_DECOUPLING_S = 600
RECOVERY_MIN_BLOCK_S = 120
RECOVERY_AFTER_S = 60
SETTLE_MIN_BLOCK_S = 240
SETTLE_WINDOW_S = 60
SETTLE_RANGE_BPM = 6
CAP_SMOOTH_S = 10
CLIMB_FACTOR_M = 8.0
HILLY_M_PER_KM = 15.0
HOT_FEELS_C = 28.0
HEAT_REF_C = 20.0
HEAT_BPM_PER_C = 1.0
SHORT_RUN_S = 600
TREND_RUNS = 7
TREND_MIN = 3
SNAPSHOT_RUNS = 3


@dataclass(frozen=True)
class Point:
    t: float                      # seconds since start
    hr: int | None = None
    speed: float | None = None    # m/s
    alt: float | None = None


@dataclass(frozen=True)
class Block:
    kind: str                     # run | walk | stop
    start: float
    duration: float

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass
class Window:
    start: float
    duration: float
    hr: float
    speed: float
    distance: float
    climb: float

    @property
    def pace(self) -> float:
        return 1000.0 / self.speed


# --- helpers ---------------------------------------------------------------------------

def _weights(points: list[Point]) -> list[float]:
    """Seconds each sample stands for (gap to the next, capped; the last gets 1 s)."""
    out = []
    for i, p in enumerate(points):
        gap = points[i + 1].t - p.t if i + 1 < len(points) else 1.0
        out.append(max(0.0, min(gap, MAX_GAP_S)))
    return out


def _in_blocks(t: float, blocks: list[Block]) -> Block | None:
    for b in blocks:
        if b.start <= t < b.end:
            return b
    return None


def _wmean(pairs) -> float | None:
    pairs = [(v, w) for v, w in pairs if v is not None and w > 0]
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total else None


def smoothed_alt(points: list[Point], span: int = 15) -> list[float | None]:
    alts = [p.alt for p in points]
    out = []
    for i in range(len(points)):
        window = [a for a in alts[max(0, i - span // 2): i + span // 2 + 1] if a is not None]
        out.append(statistics.median(window) if window else None)
    return out


def steady_windows(points: list[Point], blocks: list[Block]) -> list[Window]:
    import bisect

    runs = [b for b in blocks if b.kind == "run"]
    weights = _weights(points)
    alts = smoothed_alt(points)
    times = [p.t for p in points]
    windows: list[Window] = []
    for b in runs:
        begin = max(b.start + BLOCK_LAG_S, WARMUP_S)
        t0 = begin
        while t0 + WINDOW_S <= b.end:
            idx = range(bisect.bisect_left(times, t0), bisect.bisect_left(times, t0 + WINDOW_S))
            t0 += WINDOW_S
            cover = sum(weights[i] for i in idx)
            if cover < MIN_WINDOW_COVER_S:
                continue
            hr_cover = sum(weights[i] for i in idx if points[i].hr)
            speeds = [points[i].speed for i in idx if points[i].speed is not None]
            if hr_cover < MIN_HR_SHARE * cover or len(speeds) < 3:
                continue
            mean_speed = _wmean((points[i].speed, weights[i]) for i in idx)
            if mean_speed is None or mean_speed < MIN_RUN_SPEED:
                continue
            if statistics.pstdev(speeds) / mean_speed > MAX_SPEED_CV:
                continue
            hr = _wmean((points[i].hr, weights[i]) for i in idx if points[i].hr)
            seq = [alts[i] for i in idx if alts[i] is not None]
            climb = sum(max(0.0, b2 - a) for a, b2 in zip(seq, seq[1:]))
            windows.append(Window(points[idx[0]].t, cover, hr, mean_speed,
                                  mean_speed * cover, climb))
    return windows


def _hr_at(points: list[Point], t: float, tolerance: float = 5.0) -> int | None:
    best = None
    for p in points:
        if p.hr and abs(p.t - t) <= tolerance and (best is None or abs(p.t - t) < abs(best.t - t)):
            best = p
    return best.hr if best else None


def recoveries(points: list[Point], blocks: list[Block]) -> list[int]:
    """Per qualifying run block, in time order: peak − HR 60 s after the block ended."""
    ordered = sorted(blocks, key=lambda b: b.start)
    last_t = points[-1].t if points else 0
    out = []
    for i, b in enumerate(ordered):
        if b.kind != "run" or b.duration < RECOVERY_MIN_BLOCK_S:
            continue
        after = ordered[i + 1] if i + 1 < len(ordered) else None
        if after is not None and (after.kind == "run" or after.duration < RECOVERY_AFTER_S):
            continue
        if after is None and last_t < b.end + RECOVERY_AFTER_S:
            continue
        peak = [p.hr for p in points if p.hr and b.end - 10 <= p.t <= b.end + 20]
        later = _hr_at(points, b.end + RECOVERY_AFTER_S)
        if peak and later is not None:
            out.append(max(peak) - later)
    return out


def settle_times(points: list[Point], blocks: list[Block]) -> list[int]:
    import bisect

    out = []
    for b in blocks:
        if b.kind != "run" or b.duration < SETTLE_MIN_BLOCK_S:
            continue
        inside = [p for p in points if b.start <= p.t < b.end and p.hr]
        times = [p.t for p in inside]
        for i, p in enumerate(inside):
            if p.t + SETTLE_WINDOW_S > b.end:
                break
            j = bisect.bisect_right(times, p.t + SETTLE_WINDOW_S)
            window = [q.hr for q in inside[i:j]]
            if len(window) >= 5 and times[j - 1] - p.t >= SETTLE_WINDOW_S * 0.8 \
                    and max(window) - min(window) <= SETTLE_RANGE_BPM:
                out.append(int(round(p.t - b.start)))
                break
    return out


def longest_under_cap(points: list[Point], blocks: list[Block], cap: int) -> int:
    """Longest continuous running (inside run blocks, no data gap > 10 s) with the
    10-s smoothed HR at or below `cap`."""
    weights = _weights(points)
    best = current = 0.0
    previous_block = None
    previous_t = None
    for i, p in enumerate(points):
        block = _in_blocks(p.t, blocks)
        running = block is not None and block.kind == "run"
        recent = [q.hr for q in points[max(0, i - 30): i + 1]
                  if q.hr and p.t - CAP_SMOOTH_S < q.t <= p.t]
        smooth = sum(recent) / len(recent) if recent else None
        broken = (not running or smooth is None or smooth > cap
                  or (previous_t is not None and p.t - previous_t > MAX_GAP_S)
                  or (previous_block is not None and block is not previous_block))
        if broken:
            best = max(best, current)
            current = 0.0
            if running and smooth is not None and smooth <= cap:
                current = weights[i]
        else:
            current += weights[i]
        previous_block = block if running else None
        previous_t = p.t
    return int(round(max(best, current)))


def heat_adjusted(hr: float | None, feels_like: float | None) -> float | None:
    if hr is None:
        return None
    if feels_like is None or feels_like <= HEAT_REF_C:
        return hr
    return hr - HEAT_BPM_PER_C * (feels_like - HEAT_REF_C)


def _median_int(values: list) -> int | None:
    values = [v for v in values if v is not None]
    return int(round(statistics.median(values))) if values else None


def analyse_run(points: list[Point], blocks: list[Block], *, ref_hr: int, ref_pace: int,
                cap: int | None = None, feels_like: float | None = None) -> dict:
    """Everything for one run. Values None when the data can't support them."""
    points = sorted(points, key=lambda p: p.t)
    cap = cap or ref_hr
    run_blocks = [b for b in blocks if b.kind == "run"]
    run_s = sum(b.duration for b in run_blocks)
    weights = _weights(points)
    run_distance = sum((p.speed or 0) * w for p, w in zip(points, weights)
                       if _in_blocks(p.t, run_blocks) is not None)
    hr_cover = sum(w for p, w in zip(points, weights) if p.hr)
    total_cover = sum(weights) or 1.0
    windows = steady_windows(points, blocks)
    steady_s = sum(w.duration for w in windows)

    def matched(pred):
        chosen = [w for w in windows if pred(w)]
        return chosen if sum(w.duration for w in chosen) >= MIN_MATCH_S else []

    at_pace = matched(lambda w: abs(w.pace - ref_pace) <= REF_PACE_BAND_S)
    hr_at_pace = _wmean((w.hr, w.duration) for w in at_pace) if at_pace else None
    at_hr = matched(lambda w: abs(w.hr - ref_hr) <= REF_HR_BAND)
    speed_at_hr = _wmean((w.speed, w.duration) for w in at_hr) if at_hr else None

    efficiency = efficiency_adj = None
    if steady_s >= MIN_EFFICIENCY_S:
        dist = sum(w.distance for w in windows)
        climb = sum(w.climb for w in windows)
        hr = _wmean((w.hr, w.duration) for w in windows)
        if hr:
            efficiency = round(dist / steady_s * 60 / hr, 3)
            adj_hr = heat_adjusted(hr, feels_like)
            efficiency_adj = round((dist + CLIMB_FACTOR_M * climb) / steady_s * 60 / adj_hr, 3)

    decoupling = None
    if steady_s >= MIN_DECOUPLING_S:
        half, acc, first, second = steady_s / 2, 0.0, [], []
        for w in sorted(windows, key=lambda w: w.start):
            (first if acc < half else second).append(w)
            acc += w.duration
        ef = []
        for part in (first, second):
            dur = sum(w.duration for w in part)
            hr = _wmean((w.hr, w.duration) for w in part)
            ef.append(sum(w.distance for w in part) / dur / hr if dur and hr else None)
        if ef[0] and ef[1]:
            decoupling = round((ef[0] - ef[1]) / ef[0] * 100, 1)

    recs = recoveries(points, blocks)
    end_rec = None
    ordered_runs = sorted(run_blocks, key=lambda b: b.start)
    if ordered_runs and recs:
        tail = recoveries(points, [b for b in blocks if b.start >= ordered_runs[-1].start])
        end_rec = tail[-1] if tail else None

    alts = smoothed_alt(points)
    climb_run = 0.0
    previous = None
    for p, a in zip(points, alts):
        inside = _in_blocks(p.t, run_blocks) is not None
        if inside and a is not None and previous is not None:
            climb_run += max(0.0, a - previous)
        previous = a if inside else None
    has_alt = any(a is not None for a in alts)
    gain_per_km = round(climb_run / (run_distance / 1000), 1) if has_alt and run_distance >= 500 \
        else None

    hot = None if feels_like is None else feels_like >= HOT_FEELS_C
    flags = []
    if hot:
        flags.append("hot")
    hilly = gain_per_km is not None and gain_per_km >= HILLY_M_PER_KM
    if hilly:
        flags.append("hilly")
    if run_s < SHORT_RUN_S:
        flags.append("short")
    if hr_cover < 0.5 * total_cover:
        flags.append("no_hr")
    return {
        "run_s": int(round(run_s)), "steady_s": int(round(steady_s)),
        "distance_km": round(run_distance / 1000, 2),
        "hr_at_ref_pace": int(round(hr_at_pace)) if hr_at_pace is not None else None,
        "hr_at_ref_pace_adj": int(round(heat_adjusted(hr_at_pace, feels_like)))
        if hr_at_pace is not None else None,
        "pace_at_ref_hr": int(round(1000 / speed_at_hr)) if speed_at_hr else None,
        "efficiency": efficiency, "efficiency_adj": efficiency_adj,
        "decoupling_pct": decoupling,
        "hr_recovery_bpm": _median_int(recs), "hr_recovery_end_bpm": end_rec,
        "settle_s": _median_int(settle_times(points, blocks)),
        "duration_under_cap_s": longest_under_cap(points, blocks, cap) if hr_cover else 0,
        "feels_like_c": feels_like, "hot": hot,
        "elev_gain_per_km": gain_per_km, "hilly": hilly, "flags": flags,
    }


# --- across runs ---------------------------------------------------------------------------

TREND_KEYS = ("hr_at_ref_pace", "pace_at_ref_hr", "efficiency", "decoupling_pct",
              "duration_under_cap_s")


def _median(values: list):
    values = [v for v in values if v is not None]
    if not values:
        return None
    m = statistics.median(values)
    return round(m, 3) if isinstance(m, float) and not float(m).is_integer() else m


def rolling_trend(runs: list[dict]) -> list[dict]:
    """Per run (oldest first): the median of the last ≤ 7 runs, once ≥ 3 have a value."""
    out = []
    for i, run in enumerate(runs):
        recent = runs[max(0, i - TREND_RUNS + 1): i + 1]
        row = {"date": run["date"], "activity_id": run["activity_id"]}
        for key in TREND_KEYS:
            values = [r[key] for r in recent if r.get(key) is not None]
            value = _median(values) if len(values) >= TREND_MIN else None
            if value is not None and key in ("hr_at_ref_pace", "pace_at_ref_hr",
                                             "duration_under_cap_s"):
                value = int(round(value))
            row[key] = value
        out.append(row)
    return out


def snapshot(runs: list[dict]) -> dict | None:
    if not runs:
        return None
    return {"date": runs[0]["date"], "runs": len(runs),
            "duration_under_cap_s": _median_int([r["duration_under_cap_s"] for r in runs
                                                 if r.get("duration_under_cap_s")]),
            "hr_at_ref_pace": _median_int([r.get("hr_at_ref_pace") for r in runs]),
            "pace_at_ref_hr": _median_int([r.get("pace_at_ref_hr") for r in runs]),
            "efficiency": _median([r.get("efficiency") for r in runs])}


def minutes_text(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds} s"
    minutes = seconds / 60
    return f"{minutes:.0f} min" if minutes >= 10 else f"{minutes:.1f} min".replace(".0 ", " ")


def pace_text(seconds: int | float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}/km"


def _day(value) -> str:
    day = value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))
    return f"{day.day} {day.strftime('%b')}"


def since_day1(all_runs: list[dict], *, ref_hr: int, ref_pace: int) -> dict | None:
    """First runs vs latest runs, in plain sentences (all history, oldest first)."""
    usable = [r for r in all_runs if "no_hr" not in r.get("flags", [])]
    if len(usable) < SNAPSHOT_RUNS + 1:
        return None
    n = min(SNAPSHOT_RUNS, len(usable) // 2)
    first, latest = snapshot(usable[:n]), snapshot(usable[-n:])
    sentences = []
    a, b = first["duration_under_cap_s"], latest["duration_under_cap_s"]
    if a is not None and b is not None:
        if abs(b - a) < 30:
            sentences.append(f"Running at or under {ref_hr} bpm: about {minutes_text(b)} at a "
                             f"time, the same as at the start ({_day(first['date'])}).")
        else:
            sentences.append(f"Day 1 ({_day(first['date'])}): {minutes_text(a)} of running at or "
                             f"under {ref_hr} bpm. Now: {minutes_text(b)}.")
    a, b = first["hr_at_ref_pace"], latest["hr_at_ref_pace"]
    if a is not None and b is not None:
        diff = b - a
        if abs(diff) < 2:
            sentences.append(f"At the same pace ({pace_text(ref_pace)}) your heart rate is about "
                             "the same as in your first runs.")
        else:
            sentences.append(f"At the same pace ({pace_text(ref_pace)}) your heart rate is "
                             f"{abs(diff)} bpm {'lower' if diff < 0 else 'higher'} than in your "
                             "first runs.")
    a, b = first["pace_at_ref_hr"], latest["pace_at_ref_hr"]
    if a is not None and b is not None and abs(b - a) >= 5:
        faster = b < a
        sentences.append(f"At {ref_hr} bpm you now run {pace_text(abs(b - a)).replace('/km', '')}"
                         f" per km {'faster' if faster else 'slower'} than at first.")
    return {"first": first, "latest": latest, "sentences": sentences}


def heat_view(runs: list[dict]) -> dict:
    hot = [r for r in runs if r.get("hot") is True]
    cool = [r for r in runs if r.get("hot") is False]
    unknown = len(runs) - len(hot) - len(cool)
    hot_vals = [r["hr_at_ref_pace"] for r in hot if r.get("hr_at_ref_pace") is not None]
    cool_vals = [r["hr_at_ref_pace"] for r in cool if r.get("hr_at_ref_pace") is not None]
    vs = None
    sentence = None
    if len(hot_vals) >= 2 and len(cool_vals) >= 2:
        h, c = statistics.mean(hot_vals), statistics.mean(cool_vals)
        vs = {"metric": "hr_at_ref_pace", "hot_avg": round(h), "cool_avg": round(c),
              "diff": round(h - c), "n_hot": len(hot_vals), "n_cool": len(cool_vals)}
        sentence = (f"On hot runs your heart rate at the reference pace averaged {round(h)} bpm, "
                    f"vs {round(c)} bpm on cooler ones ({len(hot_vals)} hot, "
                    f"{len(cool_vals)} cool runs).")
    adaptation = None
    if len(hot_vals) >= 4:
        half = len(hot_vals) // 2
        early, recent = hot_vals[:half], hot_vals[-half:]
        e, r = statistics.mean(early), statistics.mean(recent)
        adaptation = {"early_hot_avg": round(e), "recent_hot_avg": round(r),
                      "diff": round(r - e), "n_early": len(early), "n_recent": len(recent)}
        word = "lower" if r < e else "higher" if r > e else "the same"
        extra = (f"Your recent hot runs show {abs(round(r - e))} bpm {word} heart rate at that "
                 "pace than your early hot runs." if word != "the same" else
                 "Recent hot runs look the same as early ones at that pace.")
        sentence = f"{sentence} {extra}" if sentence else extra
    return {"hot_runs": len(hot), "cool_runs": len(cool), "unknown_runs": unknown,
            "hot_vs_cool": vs, "adaptation": adaptation, "sentence": sentence}


INFO = {
    "duration_under_cap": "The longest stretch you ran without your heart rate (smoothed over "
                          "10 s) going above the cap. Walk breaks end a stretch.",
    "hr_at_ref_pace": "Average heart rate in steady running near your reference pace (±15 s/km),"
                      " warm-up left out. Lower at the same pace usually means less effort.",
    "pace_at_ref_hr": "Your average pace in steady running at the reference heart rate (±3 bpm). "
                      "Faster at the same heart rate is more speed for the same effort.",
    "decoupling": "How much your pace-per-heartbeat dropped from the first half of steady "
                  "running to the second. Under 5 % is a steady aerobic run.",
}


def key_numbers(trend: list[dict], first: dict | None, ref_hr: int) -> list[dict]:
    latest = trend[-1] if trend else {}

    def item(key, label, field, unit, lower_better, fmt):
        value = latest.get(field)
        start = (first or {}).get(field) if field != "decoupling_pct" else None
        change = (value - start) if value is not None and start is not None else None
        if isinstance(change, float):
            change = round(change, 2)
        better = None if change in (None, 0) else (change < 0) == lower_better
        return {"key": key, "label": label, "value": value, "unit": unit,
                "display": fmt(value) if value is not None else None, "change": change,
                "better": better, "info": INFO[key]}

    return [
        item("duration_under_cap", f"Run time at ≤ {ref_hr} bpm", "duration_under_cap_s", "s",
             False, minutes_text),
        item("hr_at_ref_pace", "HR at your easy pace", "hr_at_ref_pace", "bpm", True,
             lambda v: f"{v} bpm"),
        item("pace_at_ref_hr", f"Pace at {ref_hr} bpm", "pace_at_ref_hr", "s/km", True,
             pace_text),
        item("decoupling", "Aerobic decoupling", "decoupling_pct", "%", True,
             lambda v: f"{v:.1f}%"),
    ]


CAVEAT = ("These numbers describe how your heart rate and pace changed, not why — heat, "
          "hills, sleep, illness, caffeine and how the watch sits all move them. The heat "
          "adjustment (1 bpm per °C above 20 °C) is a rough estimate.")


def headline(day1: dict | None, runs: list[dict], ref_hr: int) -> str:
    if day1 and day1["sentences"]:
        return day1["sentences"][0]
    if not runs:
        return "No runs with heart-rate data in this range yet."
    return (f"{len(runs)} run{'s' if len(runs) != 1 else ''} so far — after a few more you'll "
            f"see how your heart rate at {ref_hr} bpm and at your easy pace changes.")
