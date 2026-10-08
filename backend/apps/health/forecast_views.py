"""R10 §C14 tomorrow's readiness forecast. Gathers today's numbers; analysis/forecast.py
does the estimate. Habits read are smoke and alcohol only — never the private habit."""

from __future__ import annotations

import datetime as dt

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import forecast as maths
from analysis import insights as insight_maths
from analysis import sleep as sleep_maths

from .common import metrics_rows

READINESS_DAYS = 3
LATE_MARGIN_MIN = 30


def _today_score(rows) -> tuple[int | None, str | None]:
    """Newest readiness within the last 3 days: Garmin's, else the computed stand-in."""
    score, source, _ = _today_score_dated(rows)
    return score, source


def _today_score_dated(rows):
    """(score, source, date the score is from) — R16 §C."""
    if not rows:
        return None, None, None
    for row in reversed(rows[-READINESS_DAYS:]):
        if row.training_readiness is not None:
            return row.training_readiness, "garmin", row.metric_date
    last = rows[-1]
    resting = [r.resting_hr for r in rows[:-1] if r.resting_hr]
    score, _ = insight_maths.computed_readiness(
        sleep_h=last.sleep_seconds / 3600 if last.sleep_seconds else None,
        hrv=last.hrv_overnight_avg,
        hrv_baseline=(last.hrv_baseline_low, last.hrv_baseline_high),
        resting_hr=last.resting_hr,
        resting_baseline=insight_maths.mean(resting[-28:]) if resting else None,
        form=None)
    return score, ("computed" if score is not None else None), \
        (last.metric_date if score is not None else None)


def forecast_payload(athlete) -> dict:
    from apps.athletes.profile_views import daily_loads
    from apps.habits.models import HabitLog
    from apps.habits.services import counts_on

    today = athlete.local_today
    rows = metrics_rows(athlete, today - dt.timedelta(days=30), today)
    recent3 = [r for r in rows if r.metric_date >= today - dt.timedelta(days=READINESS_DAYS - 1)]
    score, source, score_date = _today_score_dated(recent3)
    scores14 = [r.training_readiness for r in rows
                if r.metric_date >= today - dt.timedelta(days=13) and r.training_readiness is not None]

    loads = daily_loads(athlete)
    chronic = sum(loads.get(today - dt.timedelta(days=i), 0.0) for i in range(28)) / 28

    week = [r for r in rows if r.metric_date >= today - dt.timedelta(days=6)]
    from apps.athletes.effective import night_need_s, override_s, sleep_need

    need_info = sleep_need(athlete)                  # R18: one helper everywhere
    debt = sleep_maths.debt([(r.sleep_seconds, night_need_s(need_info, r.sleep_need_seconds))
                             for r in week])
    need = (override_s(need_info) or debt["need_s"]
            or sleep_maths.median([r.sleep_need_seconds for r in week]))
    tonight = sleep_maths.tonight([r.sleep_end_local for r in week], round(need) if need else None)
    late = False
    if tonight["bedtime"]:
        hour, minute = (int(p) for p in tonight["bedtime"].split(":"))
        target = sleep_maths.minutes_after_noon(dt.datetime(2000, 1, 1, hour, minute))
        recent_beds = [sleep_maths.minutes_after_noon(r.sleep_start_local)
                       for r in week[-3:] if r.sleep_start_local]
        late = bool(recent_beds) and sum(recent_beds) / len(recent_beds) > target + LATE_MARGIN_MIN

    counts = counts_on(athlete, today)              # smoke / alcohol / sugar only
    drink_days = HabitLog.objects.filter(
        athlete=athlete, kind="alcohol", quantity__gt=0,
        local_date__gte=today - dt.timedelta(days=6)).values("local_date").distinct().count()
    hrv_rows = [r.hrv_overnight_avg for r in rows[-3:]]
    baseline_row = next((r for r in reversed(rows) if r.hrv_baseline_low is not None), None)

    inputs = maths.ForecastInputs(
        today_score=score,
        recent_scores=scores14 if score is not None else [],
        today_load=loads.get(today, 0.0), chronic_daily_load=chronic,
        hrv_recent=hrv_rows,
        hrv_baseline_low=baseline_row.hrv_baseline_low if baseline_row else None,
        hrv_baseline_high=baseline_row.hrv_baseline_high if baseline_row else None,
        sleep_debt_s=debt["debt_s"], need_s=need, bedtime_target=tonight["bedtime"],
        late_bedtimes=late,
        alcohol_today=counts.get("alcohol", 0), smoke_today=counts.get("smoke", 0),
        drinks_regularly=drink_days >= 2 or athlete.alcohol_goal == "reduce",
    )
    result = maths.forecast(inputs)
    return {"date": today + dt.timedelta(days=1), "estimate": result["estimate"],
            "low": result["low"], "high": result["high"], "label": result["label"],
            "is_estimate": True,
            "today": {"score": score, "source": source, "date": score_date},
            "factors": result["factors"], "levers": result["levers"],
            "best_case": result["best_case"], "sentence": result["sentence"],
            "note": result["note"]}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def readiness_forecast(request):
    from django.utils import timezone

    from apps.athletes.versioning import cached

    athlete = request.user.athlete
    body = cached(athlete, "forecast", lambda: forecast_payload(athlete))   # R18
    return Response({**body, "as_of": timezone.now()})
