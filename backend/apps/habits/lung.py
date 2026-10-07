"""R10 §C9 lung recovery tracker: GET /habits/lung-recovery/. Rows in; the comparison
and the (non-causal) wording are in analysis/lung.py."""

from __future__ import annotations

import datetime as dt

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import habits as habit_maths
from analysis import lung as maths
from apps.ingest.models import DailyMetrics

from .models import HabitLog


def lung_payload(athlete) -> dict:
    from .services import _runs, quit_moment

    today = athlete.local_today
    quit_date = athlete.smoke_quit_date
    empty = {"available": False, "quit_date": quit_date, "days_since_quit": None,
             "metrics": [], "milestones": [], "note": maths.NOTE}
    if quit_date is None:
        return {**empty, "reason": "no_quit_date"}
    if quit_date > today:
        return {**empty, "reason": "quit_date_in_future"}
    start = quit_date - dt.timedelta(days=maths.BEFORE_DAYS)
    rows = list(DailyMetrics.objects.filter(athlete=athlete, metric_date__gte=start,
                                            metric_date__lte=today))
    series = {
        "sleep_breathing_rate": {r.metric_date: r.respiration_sleep_avg for r in rows
                                 if r.respiration_sleep_avg is not None},
        "spo2": {r.metric_date: r.sleep_spo2_avg for r in rows if r.sleep_spo2_avg is not None},
        "resting_hr": {r.metric_date: float(r.resting_hr) for r in rows if r.resting_hr},
        "easy_hr": {day: v["easy_hr"] for day, v in _runs(athlete, start, today).items()
                    if v.get("easy_hr") is not None},
    }
    quit_at = quit_moment(athlete)
    last = (HabitLog.objects.filter(athlete=athlete, kind="smoke", at__gte=quit_at)
            .order_by("-at").values_list("at", flat=True).first())
    quit_at = max(quit_at, last) if last else quit_at
    return {
        "available": True, "reason": None, "quit_date": quit_date,
        "days_since_quit": (today - quit_date).days,
        "metrics": [maths.metric(key, series[key], quit_date, today) for key in maths.METRICS],
        # R8 rule: from the later of the quit date and the last cigarette after it.
        "milestones": habit_maths.milestones(quit_at, athlete.local_now),
        "note": maths.NOTE,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lung_recovery(request):
    return Response(lung_payload(request.user.athlete))
