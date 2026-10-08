"""R17 endpoints on activities: data quality, recovery routine, deleted activities."""

from __future__ import annotations

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Activity, ActivityTombstone


def _own(request, pk):
    return (Activity.objects.filter(athlete=request.user.athlete, pk=pk)
            .select_related("metrics").first())


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def activity_quality(request, pk: int):
    from .quality import BadChoice, hr_chart, quality_json, set_choices

    activity = _own(request, pk)
    if activity is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "PATCH":
        data = request.data if isinstance(request.data, dict) else {}
        changes = {k: data[k] for k in ("decision", "use") if k in data}
        if not changes:
            return Response({"detail": "Send decision and/or use."}, status=400)
        try:
            set_choices(activity, **changes)
        except BadChoice as exc:
            return Response({"detail": str(exc)}, status=400)
        activity = _own(request, pk)
        return Response({"activity_id": pk, "quality": quality_json(activity)})
    return Response({"activity_id": pk, "quality": quality_json(activity),
                     "series": hr_chart(activity)})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def activity_recovery(request, pk: int):
    from .recovery import payload

    activity = _own(request, pk)
    if activity is None:
        return Response({"detail": "Not found."}, status=404)
    return Response(payload(activity))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def activity_recovery_done(request, pk: int):
    from .recovery import is_run, mark_done

    activity = _own(request, pk)
    if activity is None:
        return Response({"detail": "Not found."}, status=404)
    if not is_run(activity):
        return Response({"detail": "The recovery routine is for runs."}, status=409)
    data = request.data if isinstance(request.data, dict) else {}
    skipped = data.get("skipped") or []
    if not isinstance(skipped, list) or not all(isinstance(s, str) for s in skipped):
        return Response({"detail": "skipped must be a list of step keys."}, status=400)
    return Response(mark_done(activity, [s[:40] for s in skipped]))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def recovery_today(request):
    from .recovery import today

    return Response({"routine": today(request.user.athlete)})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def deleted_activities(request):
    from .deletion import tombstone_json

    return Response([tombstone_json(t) for t in
                     ActivityTombstone.objects.filter(athlete=request.user.athlete)])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def deleted_reimport(request, pk: int):
    from .deletion import reimport

    athlete = request.user.athlete
    tomb = ActivityTombstone.objects.filter(athlete=athlete, pk=pk).first()
    if tomb is None:
        return Response({"detail": "Not found."}, status=404)
    result = reimport(athlete, tomb)
    if "error" in result:
        return Response({"detail": result["error"]}, status=503)
    return Response(result)
