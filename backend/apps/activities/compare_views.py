"""Comparing several runs against each other.

Garmin lets you tick up to four activities and put them side by side, and that
is the right shape: a trend line across forty runs tells you the direction, but
the question an athlete actually has is narrower — *was Tuesday better than last
Tuesday, and in what way.*

Two decisions carry this module.

**Every figure is the segmented one.** Garmin's list shows 2.50 km at 12:39/km
for a run that contained a few hundred metres of actual running; comparing two
of those compares how long somebody was outside. What is compared here is run
distance, run time, run pace and the longest unbroken block — the numbers that
change when fitness changes.

**A delta has to know which way is good.** Pace falling is an improvement;
distance falling is not; heart rate falling at the same pace is. Each metric
declares its own direction, so "better" is never inferred from the sign. Getting
this wrong is how a comparison screen tells somebody a good week was a bad one.
"""

from __future__ import annotations

import logging

from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Activity

logger = logging.getLogger(__name__)

MAX_COMPARE = 4

#: key -> (label, direction, note). direction: 1 higher is better, -1 lower is
#: better, 0 neither. The note is what the number means, not what it is.
METRICS: dict[str, tuple[str, int, str]] = {
    "run_distance_m": ("Running distance", 1, "Segmented, not what the watch logged"),
    "run_duration_s": ("Time spent running", 1, "Excludes every walk break"),
    "longest_run_s": ("Longest unbroken block", 1, "The number that decides race day"),
    "run_pace_s_per_km": ("Running pace", -1, "Over run blocks only"),
    "avg_run_hr": ("Average heart rate while running", -1, "Lower at the same pace is fitter"),
    "avg_run_cadence_spm": ("Cadence", 1, "Steps per minute while running"),
    "run_fraction": ("Run fraction", 1, "Share of the outing actually run"),
    "run_block_count": ("Run blocks", 0, "How many times you started running"),
    "hr_drift_percent": ("Heart-rate drift", -1, "Rising HR at steady pace means fatigue"),
}


class CompareSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(), min_length=2, max_length=MAX_COMPARE,
    )
    #: Costs a model call, so it is opt-in rather than automatic on every tick.
    explain = serializers.BooleanField(default=False)


def _row(activity: Activity) -> dict:
    metrics = getattr(activity, "metrics", None)
    out = {
        "id": activity.pk,
        "date": activity.local_date,
        "sport": activity.sport,
        "logged_km": round((activity.total_distance_m or 0) / 1000, 2),
        "duration_s": round(activity.total_timer_s or activity.total_elapsed_s or 0),
        "avg_hr": activity.avg_hr,
        "analysed": metrics is not None,
    }
    if metrics is None:
        # Said plainly rather than filled with zeros: an unanalysed run and a run
        # with no running in it are different facts.
        out["values"] = {}
        return out

    out["values"] = {
        "run_distance_m": metrics.run_distance_m,
        "run_duration_s": metrics.run_duration_s,
        "longest_run_s": metrics.longest_run_s,
        "run_pace_s_per_km": metrics.run_pace_s_per_km,
        "avg_run_hr": metrics.avg_run_hr,
        "avg_run_cadence_spm": metrics.avg_run_cadence_spm,
        "run_fraction": round((metrics.run_fraction or 0) * 100, 1),
        "run_block_count": metrics.run_block_count,
        "hr_drift_percent": metrics.hr_drift_percent,
    }
    return out


def _deltas(rows: list[dict]) -> list[dict]:
    """Each metric across the selection, against the OLDEST as the baseline.

    Oldest-first because the question is "how has this changed", and a
    comparison that reads right-to-left answers it backwards. Garmin uses the
    first row you ticked, which depends on the order you clicked in — a
    comparison should not change its mind because you selected differently.
    """
    analysed = [r for r in rows if r["analysed"]]
    if len(analysed) < 2:
        return []

    base = min(analysed, key=lambda r: r["date"])
    out = []
    for key, (label, direction, note) in METRICS.items():
        series = [(r["id"], r["values"].get(key)) for r in analysed]
        if any(value is None for _, value in series):
            continue
        baseline = base["values"].get(key)
        if not baseline:
            continue
        out.append({
            "key": key, "label": label, "direction": direction, "note": note,
            "baseline_id": base["id"],
            "values": {str(i): v for i, v in series},
            "change_pct": {
                str(i): round((v - baseline) / baseline * 100, 1) for i, v in series
            },
        })
    return out


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def compare(request):
    """Two to four runs, side by side, on the numbers that actually move."""
    form = CompareSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    ids = form.validated_data["ids"]

    activities = list(
        Activity.objects.filter(athlete=request.user.athlete, pk__in=ids)
        .select_related("metrics")
        .order_by("local_date")
    )
    if len(activities) < 2:
        return Response(
            {"detail": "Pick at least two of your own activities."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    rows = [_row(a) for a in activities]
    payload = {
        "activities": rows,
        "metrics": _deltas(rows),
        "unanalysed": [r["id"] for r in rows if not r["analysed"]],
    }

    if form.validated_data["explain"]:
        payload["review"] = _explain(request.user.athlete, rows, payload["metrics"])
    return Response(payload)


def _explain(athlete, rows: list[dict], metrics: list[dict]) -> dict:
    """The model's read of a comparison Python has already computed.

    The division of labour is the same as everywhere else in this codebase:
    Python decides what changed, the model explains what it means and what to do
    about it. A model asked to compute the comparison will confidently invent a
    pace, and a model asked only to interpret one cannot.
    """
    from apps.coaching.client import AIUnavailable
    from apps.coaching.services import compare_runs

    try:
        return compare_runs(athlete, rows, metrics)
    except AIUnavailable as exc:
        logger.warning("comparison review unavailable: %s", exc)
        return {
            "available": False,
            "detail": "The numbers are above; the written read could not be "
                      "produced just now.",
        }
