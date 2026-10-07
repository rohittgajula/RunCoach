"""R11 §B: one day in the athlete's life between runs — steps, sitting, stress, Body
Battery and daytime heart rate — from Garmin's intraday arrays. Pure: no Django.

Every series is a list of ``[minute_of_day, value]`` pairs in the athlete's local time
(steps buckets carry a third item, Garmin's activity level). Python does all the
arithmetic; nothing here is ever sent to a model.

Stress bands are Garmin's own: rest 0–25, low 26–50, medium 51–75, high 76–100.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from statistics import median

DAY_MIN = 1440
BUCKET_MIN = 15
STRESS_STEP_MIN = 3
HR_STEP_MIN = 2

BANDS = (("rest", 0, 25), ("low", 26, 50), ("medium", 51, 75), ("high", 76, 100))
STRESSFUL = 51
HIGH = 76
STRETCH_MIN = 30
STRETCH_GAP_MIN = 6
PEAK_WIDTH_MIN = 60

SEDENTARY_STEPS = 50          # fewer than this in a 15-minute bucket = sitting still
INTENSE_STEPS = 1000          # 1,000+ in 15 minutes ≈ brisk walking or running

GOAL_MIN, GOAL_MAX = 6000, 15000
GOAL_FACTOR = 1.05
GOAL_HISTORY_DAYS = 28
GOAL_MIN_DAYS = 7

DEFAULT_WAKE, DEFAULT_BED = 7 * 60, 23 * 60
NAP_MIN = 30
BB_EVENT_MIN = 5
BB_TURN = 3                   # a Body Battery reversal of 3+ points starts a new leg
BB_TOP = 3

LEVELS = ("sleeping", "sedentary", "active", "highly_active")


# --- small helpers -------------------------------------------------------------------

def hhmm(minute: int | float | None) -> str | None:
    if minute is None:
        return None
    m = int(max(0, min(int(minute), DAY_MIN - 1)))
    return f"{m // 60:02d}:{m % 60:02d}"


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _round(value, digits=0):
    if value is None:
        return None
    return round(value) if digits == 0 else round(value, digits)


def step_of(points: list, default: int) -> int:
    """Sampling interval in minutes (median gap), so totals stay right if Garmin
    changes its cadence."""
    if len(points) < 2:
        return default
    gaps = [b[0] - a[0] for a, b in zip(points, points[1:]) if b[0] > a[0]]
    return int(median(gaps)) if gaps else default


def value_at(points: list, minute: int | None, tolerance: int = 30):
    """The sample nearest `minute` (within tolerance), else None."""
    if minute is None or not points:
        return None
    best = min(points, key=lambda p: abs(p[0] - minute))
    return best[1] if abs(best[0] - minute) <= tolerance else None


def value_before(points: list, minute: int | None, tolerance: int = 45):
    """Step-function read of a change-points series (Body Battery): the last value at or
    before `minute`; the first value when `minute` is just before the series starts."""
    if minute is None or not points:
        return None
    before = [p for p in points if p[0] <= minute]
    if before:
        return before[-1][1]
    return points[0][1] if points[0][0] - minute <= tolerance else None


def overlap(a0: int, a1: int, b0: int, b1: int) -> int:
    return max(0, min(a1, b1) - max(a0, b0))


# --- awake window ---------------------------------------------------------------------

@dataclass
class Awake:
    start: int
    end: int
    source: str

    def as_dict(self) -> dict:
        return {"start": hhmm(self.start), "end": hhmm(self.end), "source": self.source}


def awake_window(wake_min: int | None, bed_min: int | None, steps: list) -> Awake:
    """Wake = end of last night, end = start of tonight (from sleep data). Without
    those: from Garmin's `sleeping` step buckets; failing that 07:00–23:00.
    `bed_min` may exceed 1440 (after midnight): the day is awake to its end."""
    sleeping = [s for s in steps if len(s) > 2 and s[2] == "sleeping"]
    source = "sleep" if wake_min is not None or bed_min is not None else "default"
    start, end = wake_min, bed_min
    if start is None:
        morning = [s[0] + BUCKET_MIN for s in sleeping if s[0] < 12 * 60]
        if morning:
            start, source = max(morning), (source if source == "sleep" else "steps")
        else:
            start = DEFAULT_WAKE
    if end is None:
        evening = [s[0] for s in sleeping if s[0] >= 18 * 60]
        if evening:
            end = min(evening)
            source = source if source == "sleep" else "steps"
        else:
            end = DEFAULT_BED
    end = min(end, DAY_MIN)
    if end <= start:
        start, end, source = DEFAULT_WAKE, DEFAULT_BED, "default"
    return Awake(int(start), int(end), source)


# --- steps ---------------------------------------------------------------------------

def bucket_kind(row) -> str:
    steps = row[1] or 0
    level = row[2] if len(row) > 2 else None
    if level == "sleeping":
        return "sleeping"
    if steps < SEDENTARY_STEPS:
        return "sedentary"
    if steps < INTENSE_STEPS:
        return "active"
    return "intense"


def hourly_steps(steps: list) -> list[dict]:
    hours = [0] * 24
    for row in steps:
        hours[min(23, max(0, int(row[0]) // 60))] += int(row[1] or 0)
    return [{"hour": h, "steps": v} for h, v in enumerate(hours)]


def _hour(row: dict) -> dict:
    h = row["hour"]
    return {"hour": h, "label": f"{h:02d}:00–{(h + 1) % 24:02d}:00", "steps": row["steps"]}


def active_hours(hourly: list[dict], awake: Awake) -> tuple[dict | None, dict | None]:
    """Most active hour of the day; least active full hour while awake."""
    if not any(r["steps"] for r in hourly):
        return None, None
    most = max(hourly, key=lambda r: (r["steps"], -r["hour"]))
    inside = [r for r in hourly if r["hour"] * 60 >= awake.start and (r["hour"] + 1) * 60 <= awake.end]
    least = min(inside, key=lambda r: (r["steps"], r["hour"])) if inside else None
    return _hour(most), (_hour(least) if least else None)


def adaptive_goal(history: list[int | None]) -> int | None:
    """Median of the last 28 days × 1.05, clamped 6,000–15,000, rounded to 100."""
    values = [v for v in history[-GOAL_HISTORY_DAYS:] if v]
    if len(values) < GOAL_MIN_DAYS:
        return None
    goal = median(values) * GOAL_FACTOR
    return int(round(max(GOAL_MIN, min(GOAL_MAX, goal)) / 100) * 100)


def choose_goal(garmin_goal: int | None, adaptive: int | None) -> tuple[int | None, str | None]:
    if garmin_goal:
        return int(garmin_goal), "garmin"
    if adaptive:
        return adaptive, "adaptive"
    return None, None


def goal_streak(days: dict[dt.date, tuple[int | None, int | None]], end: dt.date,
                allow_unmet_end: bool = False) -> int:
    """Consecutive days ending `end` with steps ≥ goal. While today is still going
    (`allow_unmet_end`), an unmet today does not break the streak."""
    streak, day = 0, end
    steps, goal = days.get(day, (None, None))
    if allow_unmet_end and not (steps and goal and steps >= goal):
        day -= dt.timedelta(days=1)
    while True:
        steps, goal = days.get(day, (None, None))
        if not (steps and goal and steps >= goal):
            return streak
        streak += 1
        day -= dt.timedelta(days=1)


def steps_trend(by_day: dict[dt.date, int | None], end: dt.date) -> dict:
    def avg(first, last):
        vals = [by_day.get(first + dt.timedelta(days=i)) for i in range((last - first).days + 1)]
        return _mean([v for v in vals if v])

    last7 = avg(end - dt.timedelta(days=6), end)
    prev7 = avg(end - dt.timedelta(days=13), end - dt.timedelta(days=7))
    change = round((last7 - prev7) / prev7 * 100) if last7 is not None and prev7 else None
    return {"last7_avg": _round(last7), "prev7_avg": _round(prev7), "change_pct": change}


def run_vs_rest(by_day: dict[dt.date, int | None], run_dates: set) -> dict:
    run = [v for d, v in by_day.items() if v and d in run_dates]
    rest = [v for d, v in by_day.items() if v and d not in run_dates]
    return {"run_days_avg": _round(_mean(run)), "rest_days_avg": _round(_mean(rest)),
            "run_days_n": len(run), "rest_days_n": len(rest)}


# --- active vs sedentary --------------------------------------------------------------

def activity_minutes(steps: list, summary: dict | None = None) -> dict:
    """Garmin's daily seconds when given, else from the 15-minute buckets."""
    summary = summary or {}
    keys = ("sedentary_s", "active_s", "highly_active_s")
    if any(summary.get(k) is not None for k in keys):
        def mins(key):
            v = summary.get(key)
            return round(v / 60) if v is not None else None
        return {"sedentary_min": mins("sedentary_s"), "active_min": mins("active_s"),
                "intense_min": mins("highly_active_s"), "sleeping_min": mins("sleeping_s"),
                "source": "garmin"}
    if not steps:
        return {"sedentary_min": None, "active_min": None, "intense_min": None,
                "sleeping_min": None, "source": None}
    counts = {"sedentary": 0, "active": 0, "intense": 0, "sleeping": 0}
    for row in steps:
        counts[bucket_kind(row)] += BUCKET_MIN
    return {"sedentary_min": counts["sedentary"], "active_min": counts["active"],
            "intense_min": counts["intense"], "sleeping_min": counts["sleeping"],
            "source": "steps"}


def _sedentary_runs(steps: list, start: int, end: int) -> list[tuple[int, int]]:
    """(start_min, end_min) of consecutive sedentary buckets inside [start, end)."""
    runs: list[list[int]] = []
    for row in sorted(steps, key=lambda r: r[0]):
        m = int(row[0])
        if m < start or m + BUCKET_MIN > end or bucket_kind(row) != "sedentary":
            continue
        if runs and runs[-1][1] == m:
            runs[-1][1] = m + BUCKET_MIN
        else:
            runs.append([m, m + BUCKET_MIN])
    return [(a, b) for a, b in runs]


def longest_sedentary(steps: list, awake: Awake) -> dict | None:
    runs = _sedentary_runs(steps, awake.start, awake.end)
    if not runs:
        return None
    a, b = max(runs, key=lambda r: (r[1] - r[0], -r[0]))
    return {"minutes": b - a, "start": hhmm(a), "end": hhmm(b)}


def trailing_sedentary(steps: list) -> tuple[int, int] | None:
    """(start_min, minutes) of the sedentary stretch that ends with the latest bucket,
    or None when the latest bucket is not sedentary."""
    rows = sorted(steps, key=lambda r: r[0])
    if not rows or bucket_kind(rows[-1]) != "sedentary":
        return None
    start = end = int(rows[-1][0]) + BUCKET_MIN
    for row in reversed(rows):
        if int(row[0]) + BUCKET_MIN != start or bucket_kind(row) != "sedentary":
            break
        start = int(row[0])
    return start, end - start


def naps(steps: list, awake: Awake) -> list[tuple[int, int]]:
    """Runs of `sleeping` buckets while awake, at least 30 minutes."""
    out: list[list[int]] = []
    for row in sorted(steps, key=lambda r: r[0]):
        m = int(row[0])
        if len(row) < 3 or row[2] != "sleeping" or m < awake.start or m + BUCKET_MIN > awake.end:
            continue
        if out and out[-1][1] == m:
            out[-1][1] = m + BUCKET_MIN
        else:
            out.append([m, m + BUCKET_MIN])
    return [(a, b) for a, b in out if b - a >= NAP_MIN]


# --- stress ---------------------------------------------------------------------------

def stress_bands(points: list) -> dict:
    step = step_of(points, STRESS_STEP_MIN)
    out = {f"{name}_min": 0 for name, _, _ in BANDS}
    for _, v in points:
        for name, low, high in BANDS:
            if low <= v <= high:
                out[f"{name}_min"] += step
                break
    out["stressful_min"] = out["medium_min"] + out["high_min"]
    return out


def stress_peak(points: list, width: int = PEAK_WIDTH_MIN, start: int = 0,
                end: int = DAY_MIN) -> dict | None:
    """The `width`-minute window with the highest mean stress (needs half coverage)."""
    pts = [p for p in points if start <= p[0] < end]
    if not pts:
        return None
    step = step_of(points, STRESS_STEP_MIN)
    need = max(1, (width // step) // 2)
    best = None
    j = 0
    total = 0
    for i, (m, _) in enumerate(pts):
        while j < len(pts) and pts[j][0] < m + width:
            total += pts[j][1]
            j += 1
        count = j - i
        if count >= need:
            avg = total / count
            if best is None or avg > best[1]:
                best = (m, avg)
        total -= pts[i][1]
    if best is None:
        return None
    return {"start": hhmm(best[0]), "end": hhmm(best[0] + width), "avg": round(best[1])}


def stress_stretches(points: list, threshold: int = STRESSFUL, min_minutes: int = STRETCH_MIN,
                     max_gap: int = STRETCH_GAP_MIN) -> list[dict]:
    """Spells at or above `threshold` lasting ≥ min_minutes; gaps ≤ max_gap bridged."""
    step = step_of(points, STRESS_STEP_MIN)
    groups: list[list] = []
    for m, v in sorted(points):
        if v < threshold:
            continue
        # A dip or missing samples shorter than max_gap do not end the spell.
        if groups and m - groups[-1][-1][0] <= max_gap:
            groups[-1].append((m, v))
        else:
            groups.append([(m, v)])
    out = []
    for g in groups:
        minutes = g[-1][0] - g[0][0] + step
        if minutes >= min_minutes:
            values = [v for _, v in g]
            out.append({"start": hhmm(g[0][0]), "end": hhmm(g[-1][0] + step), "minutes": minutes,
                        "avg": round(sum(values) / len(values)), "peak": max(values),
                        "_start": g[0][0], "_end": g[-1][0] + step})
    return out


def trailing_stress(points: list, threshold: int) -> tuple[int, int] | None:
    """(start_min, minutes) of the ≥ threshold spell that includes the latest sample."""
    pts = sorted(points)
    if not pts or pts[-1][1] < threshold:
        return None
    step = step_of(points, STRESS_STEP_MIN)
    start = pts[-1][0]
    for m, v in reversed(pts[:-1]):
        if v < threshold or start - m > STRETCH_GAP_MIN:
            break
        start = m
    return start, pts[-1][0] - start + step


def public(stretches: list[dict]) -> list[dict]:
    return [{k: v for k, v in s.items() if not k.startswith("_")} for s in stretches]


# --- body battery ---------------------------------------------------------------------

def bb_legs(points: list, turn: int = BB_TURN) -> list[tuple]:
    """Zig-zag the series into monotonic legs ((m0, v0), (m1, v1)); a reversal must be
    at least `turn` points to count, so sensor jitter does not split a long drain."""
    pts = sorted(points)
    if len(pts) < 2:
        return []
    pivots = [pts[0]]
    direction = 0
    extreme = pts[0]
    for p in pts[1:]:
        if direction == 0:
            if p[1] - pivots[-1][1] >= turn:
                direction, extreme = 1, p
            elif pivots[-1][1] - p[1] >= turn:
                direction, extreme = -1, p
        elif direction == 1:
            if p[1] >= extreme[1]:
                extreme = p
            elif extreme[1] - p[1] >= turn:
                pivots.append(extreme)
                direction, extreme = -1, p
        else:
            if p[1] <= extreme[1]:
                extreme = p
            elif p[1] - extreme[1] >= turn:
                pivots.append(extreme)
                direction, extreme = 1, p
    if direction != 0:
        pivots.append(extreme)
    return list(zip(pivots, pivots[1:]))


def bb_events(points: list, windows: dict[str, list[tuple[int, int]]],
              min_amount: int = BB_EVENT_MIN, top: int = BB_TOP) -> list[dict]:
    """The biggest charges and drains, each labelled by what overlaps it most:
    windows = {"sleep": [...], "nap": [...], "run": [...], "stress": [...]}."""
    charges, drains = [], []
    for (m0, v0), (m1, v1) in bb_legs(points):
        amount = abs(v1 - v0)
        if amount < min_amount or m1 <= m0:
            continue
        kind = "charge" if v1 > v0 else "drain"
        cause, best = ("rest" if kind == "charge" else "activity"), 0
        for name in ("sleep", "nap", "run", "stress"):
            covered = sum(overlap(m0, m1, a, b) for a, b in windows.get(name, []))
            if covered > best and covered >= max(15, (m1 - m0) / 3):
                cause, best = name, covered
        event = {"type": kind, "cause": cause, "start": hhmm(m0), "end": hhmm(m1),
                 "amount": int(amount), "from_value": int(v0), "to_value": int(v1), "_m": m0}
        (charges if kind == "charge" else drains).append(event)
    chosen = (sorted(charges, key=lambda e: -e["amount"])[:top]
              + sorted(drains, key=lambda e: -e["amount"])[:top])
    chosen.sort(key=lambda e: e["_m"])
    return [{k: v for k, v in e.items() if k != "_m"} for e in chosen]


def bb_summary(points: list, awake: Awake, wake_min: int | None, bed_min: int | None,
               next_points: list | None = None, summary: dict | None = None) -> dict:
    summary = summary or {}
    pts = sorted(points)
    if not pts:
        return {"start": None, "end": None, "high": None, "low": None,
                "charged": summary.get("bb_charged"), "drained": summary.get("bb_drained"),
                "at_wake": summary.get("bb_at_wake"), "at_bedtime": None}
    values = [v for _, v in pts]
    deltas = [b - a for a, b in zip(values, values[1:])]
    charged = summary.get("bb_charged")
    drained = summary.get("bb_drained")
    if charged is None:
        charged = sum(d for d in deltas if d > 0)
    if drained is None:
        drained = -sum(d for d in deltas if d < 0)
    at_wake = value_before(pts, wake_min if wake_min is not None else awake.start)
    if at_wake is None:
        at_wake = summary.get("bb_at_wake")
    at_bed = None
    if bed_min is not None:
        if bed_min < DAY_MIN:
            at_bed = value_before(pts, bed_min)
        elif next_points:
            at_bed = value_before(pts + [[m + DAY_MIN, v] for m, v in next_points], bed_min)
        elif bed_min <= DAY_MIN + 60:
            # Bedtime just after midnight and no next-day series yet: the day's last value.
            at_bed = pts[-1][1]
    return {"start": values[0], "end": values[-1], "high": max(values), "low": min(values),
            "charged": int(charged), "drained": int(drained), "at_wake": at_wake,
            "at_bedtime": at_bed}


# --- heart rate -----------------------------------------------------------------------

def awake_hr(points: list, awake: Awake, exclude: list[tuple[int, int]]) -> dict:
    """Awake heart rate, excluding the night and recorded activities."""
    values = [v for m, v in points
              if awake.start <= m < awake.end and v and not any(a <= m < b for a, b in exclude)]
    if not values:
        return {"awake_min": None, "awake_max": None, "awake_avg": None}
    return {"awake_min": min(values), "awake_max": max(values),
            "awake_avg": round(sum(values) / len(values))}


def week_change(by_day: dict[dt.date, int | None], end: dt.date) -> dict:
    def avg(first, last):
        return _mean([by_day.get(first + dt.timedelta(days=i))
                      for i in range((last - first).days + 1)])

    this = avg(end - dt.timedelta(days=6), end)
    prev = avg(end - dt.timedelta(days=13), end - dt.timedelta(days=7))
    return {"this_week_avg": _round(this), "prev_week_avg": _round(prev),
            "change": round(this - prev) if this is not None and prev is not None else None}


# --- score card -----------------------------------------------------------------------

def score_card(*, steps: int | None, goal: int | None, stress_avg: int | None,
               stressful_min: int, stretches: list[dict], longest_sit: dict | None,
               bb_start: int | None, bb_end: int | None, bb_at_bed: int | None,
               ran: bool, peak: dict | None, is_today: bool) -> dict:
    """Deterministic end-of-day summary: a sentence, up to 3 bullets, 1–2 tips."""
    if steps is None and stress_avg is None and bb_end is None:
        return {"status": "no_data", "sentence": "No daytime data from Garmin for this day yet.",
                "bullets": [], "tips": []}
    points = 0
    bullets: list[str] = []
    if steps is not None:
        if goal:
            pct = round(steps / goal * 100)
            met = steps >= goal
            points += 1 if met else (0 if pct >= 60 else -1)
            bullets.append(f"{steps:,} steps — {pct}% of your {goal:,} goal.")
        else:
            bullets.append(f"{steps:,} steps.")
    if stress_avg is not None:
        if stress_avg <= 25:
            mood, p = "calm", 1
        elif stress_avg <= 40:
            mood, p = "mostly calm", 0
        elif stress_avg <= 50:
            mood, p = "busy", 0
        else:
            mood, p = "stressful", -1
        points += p
        tail = f", {stressful_min} min stressed" if stressful_min else ""
        bullets.append(f"Stress averaged {stress_avg} ({mood}){tail}.")
    if bb_start is not None and bb_end is not None:
        bullets.append(f"Body Battery {bb_start} → {bb_end}.")
        if bb_end < 20:
            points -= 1
    elif longest_sit:
        bullets.append(f"Longest sitting spell {longest_sit['minutes']} min "
                       f"({longest_sit['start']}–{longest_sit['end']}).")
    bullets = bullets[:3]
    if ran:
        points += 1

    status = "good" if points >= 2 else ("low" if points <= -1 else "ok")
    day_word = "Today" if is_today else "This day"
    parts = []
    if ran:
        parts.append("a run")
    if steps is not None and goal:
        parts.append("the step goal met" if steps >= goal else "fewer steps than your goal")
    if stress_avg is not None:
        parts.append("calm stress levels" if stress_avg <= 25 else
                     "moderate stress" if stress_avg <= 50 else "high stress")
    if parts:
        joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        sentence = f"{day_word} so far: {joined}." if is_today else f"{day_word}: {joined}."
    else:
        sentence = f"{day_word}: only partial data from Garmin."

    tips: list[str] = []
    if longest_sit and longest_sit["minutes"] >= 120:
        tips.append("Break up long sitting spells — stand and walk for 3 minutes every hour.")
    if stretches:
        when = f" around {peak['start']}" if peak else ""
        tips.append(f"Plan a 5-minute breathing break{when}, when stress tends to build.")
    if steps is not None and goal and steps < 0.6 * goal and len(tips) < 2:
        tips.append("Add an easy 15-minute walk — after a meal is an easy time to fit it in.")
    if bb_at_bed is not None and bb_at_bed < 25 and len(tips) < 2:
        tips.append("Body Battery ended low: aim for an earlier, screen-free wind-down tonight.")
    if not tips:
        tips.append("Keep the same rhythm tomorrow — regular movement and an unhurried evening.")
    return {"status": status, "sentence": sentence, "bullets": bullets, "tips": tips[:2]}


# --- the whole day --------------------------------------------------------------------

@dataclass
class DayInput:
    date: dt.date
    is_today: bool = False
    hr: list = field(default_factory=list)
    stress: list = field(default_factory=list)
    body_battery: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    wake_min: int | None = None            # end of the night that ended this morning
    bed_min: int | None = None             # start of tonight (may be ≥ 1440)
    night_start_min: int | None = None     # start of last night when it began this day (after midnight)
    next_body_battery: list | None = None  # next day's series, for a bedtime after midnight
    summary: dict = field(default_factory=dict)   # Garmin daily totals (see aggregates)
    runs: list = field(default_factory=list)       # [{start, end, activity_id, label}]
    habits: list = field(default_factory=list)     # [{minute, kind, label}]
    step_history: dict = field(default_factory=dict)   # date -> steps (incl. this date)
    goal_history: dict = field(default_factory=dict)   # date -> garmin goal
    run_dates: set = field(default_factory=set)
    awake_hr_history: dict = field(default_factory=dict)  # date -> awake avg (incl. this date)


def sleep_windows(inp: DayInput, awake: Awake) -> list[tuple[int, int]]:
    out = []
    if inp.wake_min is not None or awake.source != "default":
        out.append((inp.night_start_min or 0, awake.start))
    if (inp.bed_min is not None and inp.bed_min < DAY_MIN) or \
            (awake.source == "steps" and awake.end < DAY_MIN):
        out.append((awake.end, DAY_MIN))
    return [(a, b) for a, b in out if b > a]


def aggregates(inp: DayInput) -> dict:
    """The per-day numbers stored on IntradayDay for trends and Compare."""
    awake = awake_window(inp.wake_min, inp.bed_min, inp.steps)
    run_windows = [(r["start"], r["end"]) for r in inp.runs]
    total = inp.summary.get("total_steps")
    if total is None and inp.steps:
        total = sum(int(r[1] or 0) for r in inp.steps)
    acts = activity_minutes(inp.steps, inp.summary)
    stress_vals = [v for _, v in inp.stress]
    bands = stress_bands(inp.stress)
    hr = awake_hr(inp.hr, awake, run_windows)
    bb = bb_summary(inp.body_battery, awake, inp.wake_min, inp.bed_min,
                    inp.next_body_battery, inp.summary)
    return {
        "steps_total": total,
        "step_goal": inp.summary.get("step_goal"),
        "sedentary_min": acts["sedentary_min"], "active_min": acts["active_min"],
        "intense_min": acts["intense_min"],
        "stress_avg": round(sum(stress_vals) / len(stress_vals)) if stress_vals else
        inp.summary.get("stress_avg"),
        "stress_high_min": bands["high_min"] if stress_vals else None,
        "stressful_min": bands["stressful_min"] if stress_vals else None,
        "awake_hr_avg": hr["awake_avg"],
        "bb_charged": bb["charged"], "bb_drained": bb["drained"],
        "bb_at_wake": bb["at_wake"], "bb_at_bedtime": bb["at_bedtime"],
    }


def analyse(inp: DayInput) -> dict:
    """Everything `GET /health/day/` shows for one date (see docs/API_NOTES.md R11 F1)."""
    awake = awake_window(inp.wake_min, inp.bed_min, inp.steps)
    run_windows = [(r["start"], r["end"]) for r in inp.runs]
    nap_windows = naps(inp.steps, awake)
    sleeps = sleep_windows(inp, awake)

    # Steps
    total = inp.summary.get("total_steps")
    if total is None and inp.steps:
        total = sum(int(r[1] or 0) for r in inp.steps)
    history = [inp.step_history[d] for d in sorted(inp.step_history) if d < inp.date]
    adaptive = adaptive_goal(history)
    goal, goal_source = choose_goal(inp.summary.get("step_goal"), adaptive)
    pct = round(total / goal * 100) if total is not None and goal else None
    hourly = hourly_steps(inp.steps)
    most, least = active_hours(hourly, awake)
    streak_days = {d: (inp.step_history.get(d),
                       inp.goal_history.get(d) or adaptive) for d in inp.step_history}
    streak_days[inp.date] = (total, goal)
    steps_block = {
        "total": total, "goal": goal, "goal_source": goal_source, "adaptive_goal": adaptive,
        "pct": pct, "met": (total >= goal) if total is not None and goal else None,
        "streak_days": goal_streak(streak_days, inp.date, allow_unmet_end=inp.is_today),
        "trend": steps_trend({**inp.step_history, inp.date: total}, inp.date),
        "most_active_hour": most, "least_active_hour": least, "hourly": hourly,
        **run_vs_rest({**inp.step_history, inp.date: total}, inp.run_dates),
    }

    # Active vs sedentary
    acts = activity_minutes(inp.steps, inp.summary)
    acts["longest_sedentary"] = longest_sedentary(inp.steps, awake)

    # Stress
    values = [v for _, v in inp.stress]
    bands = stress_bands(inp.stress)
    stretches = stress_stretches(inp.stress)
    peak = stress_peak(inp.stress, start=awake.start, end=awake.end) or stress_peak(inp.stress)
    stress_block = {"avg": round(sum(values) / len(values)) if values else inp.summary.get("stress_avg"),
                    "max": max(values) if values else None, **bands, "peak": peak,
                    "stretches": public(stretches)}

    # Body Battery
    bb = bb_summary(inp.body_battery, awake, inp.wake_min, inp.bed_min,
                    inp.next_body_battery, inp.summary)
    bb["now"] = inp.body_battery[-1][1] if inp.body_battery and inp.is_today else None
    bb["events"] = bb_events(inp.body_battery, {
        "sleep": sleeps, "nap": nap_windows, "run": run_windows,
        "stress": [(s["_start"], s["_end"]) for s in stretches]})

    # Heart rate
    hr = awake_hr(inp.hr, awake, run_windows + sleeps)
    history_hr = {**inp.awake_hr_history, inp.date: hr["awake_avg"]}
    hr_block = {"resting": inp.summary.get("resting_hr"), **hr,
                "trend": week_change(history_hr, inp.date)}

    # Timeline markers
    markers = []
    for a, b in sleeps:
        markers.append({"type": "sleep", "start_min": a, "end_min": min(b, DAY_MIN - 1),
                        "label": "Sleep", "activity_id": None, "kind": None})
    for a, b in nap_windows:
        markers.append({"type": "nap", "start_min": a, "end_min": b, "label": "Nap",
                        "activity_id": None, "kind": None})
    for r in inp.runs:
        markers.append({"type": "run", "start_min": r["start"], "end_min": min(r["end"], DAY_MIN - 1),
                        "label": r["label"], "activity_id": r["activity_id"], "kind": None})
    for h in inp.habits:
        markers.append({"type": "habit", "start_min": h["minute"], "end_min": None,
                        "label": h["label"], "activity_id": None, "kind": h["kind"]})
    markers.sort(key=lambda mk: (mk["start_min"], mk["type"]))

    last_points = [s[-1][0] for s in (inp.hr, inp.stress, inp.body_battery) if s]
    if inp.steps:
        last_points.append(inp.steps[-1][0] + BUCKET_MIN)
    data_as_of = hhmm(max(last_points)) if last_points else None

    card = score_card(steps=total, goal=goal, stress_avg=stress_block["avg"],
                      stressful_min=bands["stressful_min"], stretches=stretches,
                      longest_sit=acts["longest_sedentary"], bb_start=bb["start"],
                      bb_end=bb["end"], bb_at_bed=bb["at_bedtime"], ran=bool(inp.runs),
                      peak=peak, is_today=inp.is_today)
    now = {"steps": total if inp.is_today else None,
           "stress": inp.stress[-1][1] if inp.stress and inp.is_today else None,
           "stress_at": hhmm(inp.stress[-1][0]) if inp.stress and inp.is_today else None,
           "body_battery": bb["now"],
           "body_battery_at": hhmm(inp.body_battery[-1][0]) if inp.body_battery and inp.is_today else None}
    return {
        "data_as_of": data_as_of,
        "awake": awake.as_dict(),
        "timeline": {"hr": inp.hr, "stress": inp.stress, "body_battery": inp.body_battery,
                     "steps": [[int(r[0]), int(r[1] or 0)] for r in inp.steps],
                     "markers": markers},
        "steps": steps_block,
        "activity": acts,
        "stress": stress_block,
        "body_battery": bb,
        "heart_rate": hr_block,
        "score_card": card,
        "now": now,
    }
