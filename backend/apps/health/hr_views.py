"""R24: Heart rate by what you were doing, over days and weeks.

Rohit asked to see his heart rate split by sleeping, running, walking and
ordinary daytime, and to watch it move. The maths is in
`analysis/hr_contexts.py`; this finds the windows those buckets need.

Three sources, cut against one intraday series per day:

* run and walk windows come from the activity segments, so "running" means
  running and not "an hour with a run somewhere in it" — the same distinction
  the rest of this codebase is built on;
* the sleep window is the night that ENDS on the day in question, which is how
  anybody reads "last night's sleeping heart rate";
* everything else awake is the remainder.

Also here: the pace-against-heart-rate comparison Rohit asked for — "at this
pace and distance HR was this much and now it has gone up or down". That is
the same question `analysis/heart_adaptation.py` already answers for the Heart
section; this returns it per run so the two can be put side by side.
"""

from __future__ import annotations

import datetime as dt

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import hr_contexts

MAX_DAYS = 180
DEFAULT_DAYS = 56


def _minutes(moment: dt.datetime | None, midnight: dt.datetime) -> float | None:
    if moment is None:
        return None
    return (moment - midnight).total_seconds() / 60


def _spans_for(activities, day: dt.date) -> tuple[list, list]:
    """(run spans, walk spans) in minutes from local midnight, for one day."""
    runs: list[tuple[float, float]] = []
    walks: list[tuple[float, float]] = []
    for activity in activities:
        start = activity.started_at
        if start is None:
            continue
        # Offset of the activity start within its own local day.
        begin = start.hour * 60 + start.minute + start.second / 60
        for segment in activity.segments.all():
            a = begin + (segment.start_offset_s or 0) / 60
            b = a + (segment.duration_s or 0) / 60
            if segment.kind == "run":
                runs.append((a, b))
            elif segment.kind == "walk":
                walks.append((a, b))
    return runs, walks


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def heart_rate(request):
    """GET /health/heart-rate/?days=56 -> one series per context, plus trends."""
    from apps.activities.models import Activity
    from apps.ingest.models import DailyMetrics, IntradayDay

    athlete = request.user.athlete
    today = athlete.local_today
    try:
        days = min(max(int(request.query_params.get("days") or DEFAULT_DAYS), 7), MAX_DAYS)
    except ValueError:
        days = DEFAULT_DAYS
    since = today - dt.timedelta(days=days)

    intraday = {r.day: r for r in IntradayDay.objects.filter(
        athlete=athlete, day__gte=since, day__lte=today)}
    wellness = {r.metric_date: r for r in DailyMetrics.objects.filter(
        athlete=athlete, metric_date__gte=since, metric_date__lte=today)}

    by_day: dict[dt.date, list] = {}
    for activity in (Activity.objects.filter(
        athlete=athlete, local_date__gte=since, local_date__lte=today,
    ).prefetch_related("segments")):
        by_day.setdefault(activity.local_date, []).append(activity)

    rows: list[hr_contexts.DayHR] = []
    for day, intra in sorted(intraday.items()):
        runs, walks = _spans_for(by_day.get(day, []), day)

        # The night that ENDS on this day, which is how anybody reads "last
        # night's sleeping heart rate". Clamped at midnight: the hours before
        # it belong to the previous day's series, not this one.
        sleep_span = None
        metrics = wellness.get(day)
        if metrics and metrics.sleep_end_local:
            end = metrics.sleep_end_local
            end_min = end.hour * 60 + end.minute
            start_min = 0.0
            if metrics.sleep_start_local:
                start = metrics.sleep_start_local
                start_min = (0.0 if start.date() < day
                             else start.hour * 60 + start.minute)
            if end_min > start_min:
                sleep_span = (start_min, end_min)

        rows.append(hr_contexts.bucket_day(
            day=day,
            hr_series=intra.hr or [],
            windows=hr_contexts.windows_for(runs, walks, sleep_span),
            resting=getattr(metrics, "resting_hr", None),
        ))

    return Response({
        "days": days,
        "contexts": [
            {
                "key": key,
                "label": hr_contexts.LABEL[key],
                "why": hr_contexts.WHY[key],
                "daily": hr_contexts.series(rows, key),
                "weekly": hr_contexts.weekly(rows, key),
                "trend": hr_contexts.direction(hr_contexts.series(rows, key)),
            }
            for key in hr_contexts.CONTEXTS
        ],
        "resting": [
            {"day": r.day.isoformat(), "bpm": r.resting}
            for r in rows if r.resting
        ],
        # Said on the page that charts heart rate, for the same reason it is
        # said in the Heart section: a wrist sensor is a training instrument.
        "note": (
            "Lower is generally better for every line here except running, "
            "where what matters is your heart rate at a given pace. None of "
            "this is a heart check — see Health → Heart."
        ),
    })
