"""R10 §C11 compare any two: the metric catalogue and the paired comparison.

Every series is per local day. Wellness rows use Garmin's date (a night is dated by the
morning it ends, so "sleep" on a date is the night before that day's run). Never sent to
the AI; the private habit is only offered when the athlete has turned it on.
"""

from __future__ import annotations

import datetime as dt

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import compare as maths
from analysis.sleep import minutes_after_noon
from apps.activities.models import Activity

from analysis.buckets import bucket_map, shift_back

from .common import BadRequest, metrics_rows
from .period import parse_period

SUM_KEYS = {"steps", "smoke", "alcohol", "sugar", "private", "run_km", "training_load"}

# key -> (label, unit, group, noun)
CATALOGUE: dict[str, tuple[str, str, str, str]] = {
    "sleep_h": ("Sleep", "h", "wellness", "sleep"),
    "sleep_score": ("Sleep score", "", "wellness", "sleep score"),
    "hrv": ("Overnight HRV", "ms", "wellness", "HRV"),
    "rhr": ("Resting HR", "bpm", "wellness", "resting HR"),
    "stress": ("Average stress", "", "wellness", "stress"),
    "body_battery": ("Body Battery high", "", "wellness", "Body Battery"),
    "breathing_rate": ("Breathing rate asleep", "brpm", "wellness", "breathing rate asleep"),
    "spo2": ("Overnight SpO2", "%", "wellness", "overnight SpO2"),
    "steps": ("Steps", "steps", "wellness", "steps"),
    "bedtime_h": ("Bedtime", "h", "wellness", "later bedtime"),
    "training_load": ("Training load", "", "wellness", "training load"),
    "smoke": ("Cigarettes", "count", "habits", "cigarettes"),
    "alcohol": ("Drinks", "standard drinks", "habits", "drinks"),
    "sugar": ("Sugar servings", "servings", "habits", "sugar"),
    "private": ("Private", "count", "habits", "Private"),
    # R11 §B8: the day between runs (IntradayDay aggregates)
    "active_min": ("Active time", "min", "day", "active time"),
    "sedentary_min": ("Sedentary time", "min", "day", "sedentary time"),
    "stress_high_min": ("High-stress time", "min", "day", "high-stress time"),
    "bb_bedtime": ("Body Battery at bedtime", "", "day", "Body Battery at bedtime"),
    "awake_hr": ("Awake HR", "bpm", "day", "awake heart rate"),
    "run_km": ("Run distance", "km", "runs", "running distance"),
    "run_pace": ("Run pace", "s/km", "runs", "run pace (seconds per km)"),
    "easy_hr": ("HR at easy pace", "bpm", "runs", "HR at easy pace"),
    "avg_hr": ("Average HR", "bpm", "runs", "average HR"),
    "efficiency": ("Efficiency", "m/min/bpm", "runs", "running efficiency"),
    "cadence": ("Cadence", "spm", "runs", "cadence"),
    "hr_drift": ("HR drift", "%", "runs", "HR drift"),
    "run_fraction": ("Time running", "%", "runs", "time spent running"),
}
WELLNESS_FIELDS = {
    "sleep_h": lambda r: round(r.sleep_seconds / 3600, 2) if r.sleep_seconds else None,
    "sleep_score": lambda r: r.sleep_score,
    "hrv": lambda r: r.hrv_overnight_avg,
    "rhr": lambda r: r.resting_hr,
    "stress": lambda r: r.stress_avg,
    "body_battery": lambda r: r.body_battery_high,
    "breathing_rate": lambda r: r.respiration_sleep_avg,
    "spo2": lambda r: r.sleep_spo2_avg,
    "steps": lambda r: r.steps,
    "bedtime_h": lambda r: (round(minutes_after_noon(r.sleep_start_local) / 60 + 12, 2)
                            if r.sleep_start_local else None),
}


def available_keys(athlete) -> list[str]:
    return [k for k in CATALOGUE if k != "private" or athlete.private_habit_enabled]


def catalogue_json(athlete) -> list[dict]:
    return [{"key": k, "label": CATALOGUE[k][0], "unit": CATALOGUE[k][1],
             "group": CATALOGUE[k][2], "noun": CATALOGUE[k][3]} for k in available_keys(athlete)]


def _wellness(athlete, key, start, end) -> dict[dt.date, float]:
    if key == "training_load":
        from apps.athletes.profile_views import daily_loads

        loads = daily_loads(athlete)
        if not loads:
            return {}
        first = max(start, min(loads))
        days = (end - first).days + 1
        return {first + dt.timedelta(days=i): round(loads.get(first + dt.timedelta(days=i), 0.0), 1)
                for i in range(max(days, 0))}
    getter = WELLNESS_FIELDS[key]
    out = {}
    for row in metrics_rows(athlete, start, end):
        value = getter(row)
        if value is not None:
            out[row.metric_date] = float(value)
    return out


DAY_FIELDS = {"active_min": "active_min", "sedentary_min": "sedentary_min",
              "stress_high_min": "stress_high_min", "bb_bedtime": "bb_at_bedtime",
              "awake_hr": "awake_hr_avg"}


def _day(athlete, key, start, end) -> dict[dt.date, float]:
    from apps.ingest.models import IntradayDay

    field = DAY_FIELDS[key]
    rows = (IntradayDay.objects.filter(athlete=athlete, day__gte=start, day__lte=end)
            .exclude(**{f"{field}__isnull": True}).values_list("day", field))
    return {day: float(value) for day, value in rows}


def _habit(athlete, kind, start, end) -> dict[dt.date, float]:
    from analysis import habits as habit_maths
    from apps.habits.models import HabitLog

    logs = list(HabitLog.objects.filter(athlete=athlete, kind=kind)
                .values_list("local_date", "quantity"))
    totals = habit_maths.daily_totals(logs)
    starts = [d for d in (min(totals) if totals else None,
                          athlete.smoke_quit_date if kind == "smoke" else None) if d]
    if not starts:
        return {}
    first = max(start, min(starts))
    days = (end - first).days + 1
    return {first + dt.timedelta(days=i): round(totals.get(first + dt.timedelta(days=i), 0.0), 2)
            for i in range(max(days, 0))}


def _runs(athlete, key, start, end) -> dict[dt.date, float]:
    easy_low, easy_high = athlete.easy_pace_min - 15, athlete.easy_pace_max + 30
    by_day: dict[dt.date, list[float]] = {}
    qs = (Activity.objects.filter(athlete=athlete, sport__icontains="run", local_date__gte=start,
                                  local_date__lte=end).select_related("metrics"))
    if key == "easy_hr":
        qs = qs.prefetch_related("segments")
    for a in qs:
        m = getattr(a, "metrics", None)
        if m is None or m.run_block_count <= 0:
            continue
        pace, hr = m.run_pace_s_per_km, m.avg_run_hr or a.avg_hr
        value = None
        if key == "run_km":
            value = m.run_distance_m / 1000
        elif key == "run_pace":
            value = pace
        elif key == "avg_hr":
            value = a.avg_hr
        elif key == "efficiency":
            value = (60000 / pace) / hr if pace and hr else None
        elif key == "cadence":
            value = m.avg_run_cadence_spm
        elif key == "hr_drift":
            value = m.hr_drift_percent
        elif key == "run_fraction":
            value = m.run_fraction * 100 if m.run_fraction is not None else None
        elif key == "easy_hr":
            from apps.activities.progress import _easy_hr

            value = _easy_hr(a, easy_low, easy_high)
        if value is not None:
            by_day.setdefault(a.local_date, []).append(float(value))
    digits = 3 if key == "efficiency" else 1
    return {day: round(sum(v) / len(v), digits) for day, v in by_day.items()}


def series_for(athlete, key: str, start: dt.date, end: dt.date) -> dict[dt.date, float]:
    group = CATALOGUE[key][2]
    if group == "wellness":
        return _wellness(athlete, key, start, end)
    if group == "habits":
        return _habit(athlete, key, start, end)
    if group == "day":
        return _day(athlete, key, start, end)
    return _runs(athlete, key, start, end)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def metrics(request):
    return Response({"metrics": catalogue_json(request.user.athlete)})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def compare(request):
    athlete = request.user.athlete
    period = parse_period(request, athlete, "3m")
    x, y = request.query_params.get("x"), request.query_params.get("y")
    keys = available_keys(athlete)
    for name, value in (("x", x), ("y", y)):
        if not value:
            raise BadRequest(f"{name} is required (see /health/compare/metrics/).")
        if value not in keys:
            raise BadRequest(f"Unknown metric for {name}: {value}.")
    if x == y:
        raise BadRequest("Pick two different metrics.")
    lag_raw = request.query_params.get("lag", "0")
    if lag_raw not in ("0", "1"):
        raise BadRequest("lag must be 0 or 1.")
    lag = int(lag_raw)
    start, end, freq = period.start, period.end, period.freq
    if freq == "day":
        xs = series_for(athlete, x, start, end)
        ys = series_for(athlete, y, start, end + dt.timedelta(days=lag))
        result = maths.compare(xs, ys, lag, CATALOGUE[x][3], CATALOGUE[y][3])
    else:
        # Buckets first (sum for counts, mean otherwise); lag 1 = the next bucket.
        reach = end + (dt.timedelta(days=31) if lag else dt.timedelta(0))
        xs = bucket_map(series_for(athlete, x, start, end), freq, "sum" if x in SUM_KEYS else "mean")
        ys = bucket_map(series_for(athlete, y, start, reach), freq, "sum" if y in SUM_KEYS else "mean")
        if lag:
            ys = shift_back(ys, freq)
        result = maths.compare(xs, ys, lag, CATALOGUE[x][3], CATALOGUE[y][3], freq=freq,
                               pre_shifted=True)

    def meta(key):
        return {"key": key, "label": CATALOGUE[key][0], "unit": CATALOGUE[key][1]}

    return Response({"x": meta(x), "y": meta(y), **period.ranged(), "lag": lag, **result})
