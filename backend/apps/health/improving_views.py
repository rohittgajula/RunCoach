""""Am I improving?" (Health → Reports → Improving). Built on read from stored run
metrics and resting HR; nothing is stored. Maths in analysis.improving."""

from __future__ import annotations

import datetime as dt

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import improving as maths
from apps.activities.models import Activity
from apps.athletes.models import Athlete
from apps.ingest.models import DailyMetrics

HISTORY_DAYS = 365


def _runs(athlete, since: dt.date) -> list[dict]:
    acts = (Activity.objects.filter(athlete=athlete, sport__icontains="run", local_date__gte=since)
            .select_related("metrics").order_by("local_date", "started_at"))
    out = []
    for a in acts:
        m = getattr(a, "metrics", None)
        if m is None:
            continue
        out.append({
            "date": a.local_date.isoformat(), "sport": a.sport,
            "total_s": a.total_timer_s, "total_m": a.total_distance_m,
            "run_s": m.run_duration_s, "run_pace_s": m.run_pace_s_per_km,
            "run_hr": m.avg_run_hr, "max_hr": a.max_hr,
            "zones": m.time_in_zone or {}, "longest_run_s": m.longest_run_s,
        })
    return out


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def improving(request):
    athlete = Athlete.objects.get(user=request.user)
    today = athlete.local_today
    since = today - dt.timedelta(days=HISTORY_DAYS)
    rhr = list(DailyMetrics.objects.filter(athlete=athlete, metric_date__gte=since,
                                           resting_hr__isnull=False)
               .values_list("metric_date", "resting_hr"))
    body = maths.report(_runs(athlete, since), [(d.isoformat(), v) for d, v in rhr], today,
                        easy_band=athlete.easy_hr_band())
    zones = athlete.zones()
    body["zones"] = ([{"name": z.name, "low": z.low, "high": z.high} for z in zones.zones]
                     if zones else None)
    return Response(body)
