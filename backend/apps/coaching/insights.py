"""GET /insights/ and POST /insights/summary/ (R6 §5).

Gathers rows and hands them to analysis/insights.py. Every number on the Insights tab
is computed here; the AI overview is a paragraph written from this payload and is
told never to add a number of its own.
"""

from __future__ import annotations

import datetime as dt

from rest_framework import status as http
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import insights as maths
from apps.activities.models import Activity
from apps.athletes.models import Athlete
from apps.ingest.models import DailyMetrics

from .throttles import ChatThrottle

RANGES = {"4w": 28, "12w": 84, "6m": 182}
DEFAULT_RANGE = "4w"
HARD_KINDS = {"INTERVALS", "TEMPO", "RACE"}


def _avg(rows, attr, digits=1):
    return maths.mean([getattr(r, attr) for r in rows], digits)


def _series(rows, attr, key="value", scale=1.0, digits=1):
    return [{"date": r.metric_date, key: round(getattr(r, attr) * scale, digits)}
            for r in rows if getattr(r, attr) is not None]


def _latest(rows, attr):
    """Newest non-empty value of `attr` (rows oldest first)."""
    for row in reversed(rows):
        value = getattr(row, attr)
        if value not in (None, ""):
            return value
    return None


def _latest_date(rows, attr):
    """R16 §C: the day `_latest(rows, attr)` comes from."""
    for row in reversed(rows):
        if getattr(row, attr) not in (None, ""):
            return row.metric_date
    return None


def _wellness(athlete: Athlete, rows: list[DailyMetrics], today: dt.date, form) -> dict:
    hrv_low = _latest(rows, "hrv_baseline_low")
    hrv_high = _latest(rows, "hrv_baseline_high")
    last = rows[-1] if rows else None
    today_row = last if last and last.metric_date >= today - dt.timedelta(days=1) else None

    resting_history = [r.resting_hr for r in rows[:-1] if r.resting_hr]
    score, drivers = maths.computed_readiness(
        sleep_h=(today_row.sleep_seconds / 3600) if today_row and today_row.sleep_seconds else None,
        hrv=today_row.hrv_overnight_avg if today_row else None,
        hrv_baseline=(hrv_low, hrv_high),
        resting_hr=today_row.resting_hr if today_row else None,
        resting_baseline=maths.mean(resting_history[-28:]) if resting_history else None,
        form=form,
    )
    if today_row and today_row.training_readiness is not None:
        garmin_score = today_row.training_readiness
        level = (today_row.training_readiness_level or "").replace("_", " ").title()
        readiness = {"score": garmin_score, "label": level or maths.readiness_label(garmin_score),
                     "drivers": drivers, "source": "garmin",
                     "date": today_row.metric_date}
    else:
        readiness = {"score": score, "label": maths.readiness_label(score),
                     "drivers": drivers, "source": "computed",
                     "date": today_row.metric_date if today_row and score is not None else None}

    resting = [(r.metric_date, r.resting_hr) for r in rows if r.resting_hr]
    slope = maths.slope_per_week(resting)
    vo2 = [r for r in rows if r.vo2max]
    prediction = next((r for r in reversed(rows) if r.race_pred_5k_s or r.race_pred_10k_s), None)

    return {
        "readiness": readiness,
        "hrv": {
            "last_night_ms": _latest(rows, "hrv_overnight_avg"),
            "last_night_date": _latest_date(rows, "hrv_overnight_avg"),
            "weekly_avg_ms": _latest(rows, "hrv_weekly_avg"),
            "baseline_low": hrv_low,
            "baseline_high": hrv_high,
            "status": maths.hrv_status(_latest(rows, "hrv_status")),
            "series": [{"date": r.metric_date, "ms": r.hrv_overnight_avg}
                       for r in rows if r.hrv_overnight_avg],
        },
        "sleep": {
            "avg_s": round(maths.mean([r.sleep_seconds for r in rows], 0) or 0) or None,
            "avg_score": _avg(rows, "sleep_score", 0),
            "series": [{"date": r.metric_date, "s": r.sleep_seconds, "score": r.sleep_score}
                       for r in rows if r.sleep_seconds],
        },
        "resting_hr": {
            "current": _latest(rows, "resting_hr"),
            "current_date": _latest_date(rows, "resting_hr"),
            "trend_bpm_per_week": round(slope, 2) if slope is not None else None,
            "series": _series(rows, "resting_hr", digits=0),
        },
        "body_battery": {
            "avg": _avg(rows, "body_battery_high", 0),
            "date": _latest_date(rows, "body_battery_high"),
            "series": [{"date": r.metric_date, "value": r.body_battery_high,
                        "low": r.body_battery_low} for r in rows if r.body_battery_high is not None],
        },
        "stress": {"avg": _avg(rows, "stress_avg", 0), "date": _latest_date(rows, "stress_avg"),
                   "series": _series(rows, "stress_avg", digits=0)},
        "respiration": {
            "avg_rpm": _avg(rows, "respiration_avg"),
            "sleep_avg_rpm": _avg(rows, "respiration_sleep_avg"),
            "series": [{"date": r.metric_date, "value": r.respiration_avg,
                        "sleep_value": r.respiration_sleep_avg}
                       for r in rows if r.respiration_avg or r.respiration_sleep_avg],
        },
        "vo2max": {"value": vo2[-1].vo2max, "date": vo2[-1].metric_date,
                   "series": _series(vo2, "vo2max")} if vo2 else None,
        "race_predictions": {
            "5k_s": prediction.race_pred_5k_s, "10k_s": prediction.race_pred_10k_s,
            "half_s": prediction.race_pred_half_s, "marathon_s": prediction.race_pred_marathon_s,
        } if prediction else None,
    }


def _easy_band(athlete: Athlete) -> tuple[int, int]:
    zones = athlete.zones()
    if zones:
        band = zones.band("Z2")
        return band.low, band.high
    return athlete.hr_easy_min, athlete.hr_easy_max


def _running(athlete: Athlete, start: dt.date, end: dt.date | None = None) -> tuple[dict, dict]:
    """The "How you're running" card, plus the inputs the focus rules need."""
    from apps.planning.models import PlannedWorkout

    end = end or athlete.local_today
    runs = [
        a for a in Activity.objects.filter(athlete=athlete, sport__icontains="run",
                                           local_date__gte=start, local_date__lte=end)
        .select_related("metrics").prefetch_related("segments").order_by("local_date")
        if getattr(a, "metrics", None) and a.metrics.run_block_count > 0
    ]
    hard_ids = set(PlannedWorkout.objects.filter(
        athlete=athlete, completed_activity__in=runs, kind__in=HARD_KINDS,
    ).values_list("completed_activity_id", flat=True))
    low, high = _easy_band(athlete)

    easy_pace, above, total_zone, cvs = [], 0.0, 0.0, []
    for run in runs:
        blocks = [s for s in run.segments.all() if s.kind == "run"]
        cvs.append(maths.pace_cv([(s.avg_pace_s_per_km, s.duration_s) for s in blocks]))
        in_band = [s for s in blocks if s.hr_avg and low <= s.hr_avg <= high
                   and s.avg_pace_s_per_km]
        seconds = sum(s.duration_s for s in in_band)
        if seconds:
            easy_pace.append({"date": run.local_date, "value": round(
                sum(s.avg_pace_s_per_km * s.duration_s for s in in_band) / seconds)})
        zones = run.metrics.time_in_zone or {}
        if zones and run.pk not in hard_ids:
            above += sum(zones.get(z, 0) or 0 for z in ("Z3", "Z4", "Z5"))
            total_zone += sum(zones.values())

    cadence_points = [(r.local_date, r.metrics.avg_run_cadence_spm) for r in runs]
    fraction_points = [(r.local_date, r.metrics.run_fraction) for r in runs]
    cadence_avg = maths.mean([v for _, v in cadence_points], 0)
    cadence_slope = maths.slope_per_week(cadence_points)
    fraction_slope = maths.slope_per_week(fraction_points)
    low_t, high_t = maths.CADENCE_TARGET
    if cadence_avg is None:
        note = "No cadence recorded on your runs yet."
    elif cadence_avg < low_t:
        note = f"Below the {low_t}–{high_t} band: shorter, quicker steps."
    elif cadence_avg > high_t:
        note = f"Above the {low_t}–{high_t} band — fine if it feels natural."
    else:
        note = f"Inside the {low_t}–{high_t} band."

    def avg_metric(attr, digits):
        return maths.mean([getattr(r.metrics, attr) for r in runs], digits)

    form = {
        "ground_contact_ms": avg_metric("avg_ground_contact_ms", 0),
        "vertical_oscillation_cm": avg_metric("avg_vertical_oscillation_cm", 1),
        "stride_length_m": avg_metric("avg_stride_length_m", 2),
    }
    running = {
        "runs": len(runs),
        "run_km": round(sum(r.metrics.run_distance_m for r in runs) / 1000, 1),
        "run_fraction_trend": [{"date": d, "value": round(v, 2)} for d, v in fraction_points],
        "longest_run_trend": [{"date": r.local_date, "value": round(r.metrics.longest_run_s)}
                              for r in runs],
        "easy_pace_trend": easy_pace,
        "cadence": {
            "avg": cadence_avg,
            "trend": round(cadence_slope, 2) if cadence_slope is not None else None,
            "target": {"low": low_t, "high": high_t},
            "note": note,
        },
        "hr_drift_avg": avg_metric("hr_drift_percent", 1),
        "pace_cv_avg": maths.mean(cvs, 3),
        "form": form if any(v is not None for v in form.values()) else None,
    }
    focus_inputs = {
        "avg_cadence": cadence_avg,
        "easy_above_z2_share": (above / total_zone) if total_zone else None,
        "run_fraction_slope": fraction_slope,
        "avg_run_fraction": maths.mean([v for _, v in fraction_points], 2),
        "runs": len(runs),
    }
    return running, focus_inputs


def _load(athlete: Athlete, today: dt.date) -> dict:
    from apps.athletes.profile_views import daily_loads, fitness_for

    points, label = fitness_for(athlete, today - dt.timedelta(days=1), today)
    last = points[-1] if points else None
    loads = daily_loads(athlete)
    acute = sum(loads.get(today - dt.timedelta(days=i), 0.0) for i in range(7)) / 7
    chronic = sum(loads.get(today - dt.timedelta(days=i), 0.0) for i in range(28)) / 28
    return {
        "fitness": last.fitness if last else None,
        "fatigue": last.fatigue if last else None,
        "form": last.form if last else None,
        "status": label,
        "acwr": round(acute / chronic, 2) if chronic > 0 else None,
    }


def _summary(athlete: Athlete, today: dt.date) -> dict:
    from .models import AIAnalysis

    row = AIAnalysis.objects.filter(athlete=athlete, kind=AIAnalysis.Kind.INSIGHTS).first()
    tz = athlete.local_now.tzinfo
    if row is None or row.created_at.astimezone(tz).date() != today:
        return {"status": "none", "markdown": "", "generated_at": None}
    return {"status": "ready", "markdown": (row.result or {}).get("markdown", ""),
            "generated_at": row.created_at}


def _bucket_series(payload: dict, freq: str) -> None:
    """R12 §A: fold the chart series into week/month points (identity for day)."""
    from analysis.buckets import bucket

    if freq == "day":
        return
    for key, digits in (("hrv", 0), ("sleep", 0), ("resting_hr", 0), ("body_battery", 0),
                        ("stress", 0), ("respiration", 1)):
        block = payload.get(key)
        if block and block.get("series"):
            block["series"] = bucket(block["series"], freq, "mean", digits=digits)
    if payload.get("vo2max"):
        payload["vo2max"]["series"] = bucket(payload["vo2max"]["series"], freq, "last")
    running = payload["running"]
    for key, digits in (("run_fraction_trend", 2), ("longest_run_trend", 0),
                        ("easy_pace_trend", 0)):
        running[key] = bucket(running[key], freq, "mean", digits=digits)


def insights_payload(athlete: Athlete, range_key) -> dict:
    """`range_key`: a preset key or an R12 Period (custom start/end, freq). The series
    cover the period; readiness, load and focus are always as of today."""
    from apps.health.period import LEGACY, as_period

    period = as_period(athlete, range_key, extra=LEGACY)
    today = athlete.local_today
    start, end = period.start, period.end
    rows = list(DailyMetrics.objects.filter(athlete=athlete, metric_date__gte=start,
                                            metric_date__lte=end).order_by("metric_date"))
    load = _load(athlete, today)
    payload = {**period.ranged(), "today": today,
               **_wellness(athlete, rows, today,
                           None if load["status"] == "insufficient_data" else load["form"])}
    running, focus_inputs = _running(athlete, start, end)
    payload["running"] = running
    payload["load"] = load

    last_run = (Activity.objects.filter(athlete=athlete, sport__icontains="run")
                .order_by("-local_date").values_list("local_date", flat=True).first())
    newest_first = list(reversed(rows))
    resp = [r.respiration_sleep_avg or r.respiration_avg for r in newest_first]
    baseline_resp = maths.mean(resp[3:31])
    hrv_low = payload["hrv"]["baseline_low"]
    payload["focus"] = maths.focus(maths.FocusInputs(
        **focus_inputs,
        hrv_last_days=[r.hrv_overnight_avg for r in newest_first[:3]],
        hrv_baseline_low=hrv_low,
        avg_sleep_h=(payload["sleep"]["avg_s"] / 3600) if payload["sleep"]["avg_s"] else None,
        gap_days=(today - last_run).days if last_run else None,
        respiration_recent=resp[:3],
        respiration_baseline=baseline_resp,
        **_habit_inputs(athlete, today),
    ))
    payload["summary"] = _summary(athlete, today)
    _bucket_series(payload, period.freq)
    return payload


def _habit_inputs(athlete: Athlete, today: dt.date) -> dict:
    """R8 §B focus inputs: smoking days (last 14 vs the 14 before), the smoke-free
    streak and the alcohol -> HRV impact row over 12 weeks."""
    from apps.habits.models import HabitLog

    if not HabitLog.objects.filter(athlete=athlete).exists():
        return {}
    from apps.habits.services import smoke_streak, summary_payload

    days = set(HabitLog.objects.filter(
        athlete=athlete, kind="smoke", local_date__gte=today - dt.timedelta(days=27),
        quantity__gt=0).values_list("local_date", flat=True))
    cut = today - dt.timedelta(days=13)
    impact = summary_payload(athlete, "12w", with_report=False)["impact"]
    return {
        "smoke_days_recent": sum(1 for d in days if d >= cut),
        "smoke_days_before": sum(1 for d in days if d < cut),
        "smoke_streak_days": smoke_streak(athlete)["current_days"],
        "alcohol_hrv": next((r for r in impact if r["habit"] == "alcohol"
                             and r["metric"] == "hrv" and not r["dose"]), None),
    }


def _period(request):
    from apps.health.period import LEGACY, parse_period

    return parse_period(request, request.user.athlete, DEFAULT_RANGE, extra=LEGACY)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def insights(request):
    from apps.health.freshness import freshness_json

    athlete = request.user.athlete
    fresh = freshness_json(athlete)
    return Response({**insights_payload(athlete, _period(request)), "as_of": fresh["as_of"],
                     "freshness": fresh})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatThrottle])
def insights_summary(request):
    """Generate (or return today's cached) AI overview. -> {status, markdown, generated_at}"""
    from .client import AIUnavailable
    from .services import insights_overview

    period = _period(request)
    athlete = request.user.athlete
    existing = _summary(athlete, athlete.local_today)
    # Cached per day: a second tap returns today's overview; ?refresh=1 rewrites it.
    if existing["status"] == "ready" and request.query_params.get("refresh") != "1":
        return Response(existing)
    try:
        insights_overview(athlete, insights_payload(athlete, period))
    except AIUnavailable as exc:
        return Response({"detail": str(exc) or "The coach is unavailable right now."},
                        status=http.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(_summary(athlete, athlete.local_today))
