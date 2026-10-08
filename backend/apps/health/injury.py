"""R13 §3 injury watch: GET /health/injury/ and the pain reports ("Anything hurting?").

The flags are computed in analysis/injury.py; this gathers the athlete's runs, load
ratio, pain reports and shoe. A pain report can only ever make the plan easier: it
feeds the morning check-in (`pain` signal) and auto-adjust (apps.planning.auto_adjust).
Never sent to the AI.
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import injury as maths
from apps.activities.models import Activity

from .models import PainReport

RUN_DAYS = 42
PAIN_LIST_DAYS = 14
BACKDATE_DAYS = 14
SIDES = ("left", "right", "both", "center")


def pain_json(p: PainReport) -> dict:
    return {"id": p.pk, "date": p.date, "location": p.location, "side": p.side,
            "severity": p.severity, "activity_id": p.activity_id, "note": p.note,
            "created_at": p.created_at}


def _runs(athlete, today: dt.date) -> list[maths.Run]:
    rows = (Activity.objects.filter(athlete=athlete, sport__icontains="run",
                                    local_date__gte=today - dt.timedelta(days=RUN_DAYS),
                                    local_date__lte=today)
            .select_related("metrics").order_by("local_date", "id"))
    out = []
    for a in rows:
        m = getattr(a, "metrics", None)
        km = (m.run_distance_m if m else a.total_distance_m or 0) / 1000
        out.append(maths.Run(date=a.local_date, km=round(km, 2),
                             cadence=m.avg_run_cadence_spm if m else None,
                             gct_balance=m.gct_balance_left_pct if m else None))
    return out


def acwr(athlete, day: dt.date) -> float | None:
    """The check-in's acute:chronic ratio of the custom load (7 / 28 days)."""
    from apps.athletes.profile_views import daily_loads

    loads = daily_loads(athlete)
    if not loads or min(loads) > day - dt.timedelta(days=21):
        return None
    acute = sum(loads.get(day - dt.timedelta(days=i), 0.0) for i in range(7)) / 7
    chronic = sum(loads.get(day - dt.timedelta(days=i), 0.0) for i in range(28)) / 28
    return round(acute / chronic, 2) if chronic > 0 else None


def current_shoe(athlete) -> dict | None:
    """The default active shoe, else the most recently used one."""
    from apps.gear.models import Shoe
    from apps.gear.views import _usage, shoe_json

    shoes = list(Shoe.objects.filter(athlete=athlete, retired=False))
    if not shoes:
        return None
    usage = _usage(athlete)
    rows = [shoe_json(s, usage) for s in shoes]
    default = next((r for r in rows if r["is_default"]), None)
    if default:
        return default
    used = [r for r in rows if r["last_used"]]
    return max(used, key=lambda r: r["last_used"]) if used else rows[0]


def pains(athlete, today: dt.date, days: int = PAIN_LIST_DAYS) -> list[PainReport]:
    return list(PainReport.objects.filter(athlete=athlete,
                                          date__gte=today - dt.timedelta(days=days - 1),
                                          date__lte=today))


def assess(athlete, today: dt.date | None = None) -> dict:
    today = today or athlete.local_today
    reports = pains(athlete, today)
    result = maths.assess(
        _runs(athlete, today), acwr(athlete, today),
        [maths.Pain(p.date, p.location, p.side, p.severity) for p in reports],
        current_shoe(athlete), today)
    result["pains"] = [pain_json(p) for p in reports]
    return result


def injury_payload(athlete) -> dict:
    result = assess(athlete)
    result.pop("pain_signal", None)
    return result


def pain_signal(athlete, day: dt.date | None = None) -> dict | None:
    day = day or athlete.local_today
    reports = PainReport.objects.filter(
        athlete=athlete, date__gte=day - dt.timedelta(days=maths.PAIN_WINDOW_DAYS - 1),
        date__lte=day)
    return maths.pain_signal([maths.Pain(p.date, p.location, p.side, p.severity)
                              for p in reports], day)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def injury(request):
    athlete = request.user.athlete
    return Response({**injury_payload(athlete), "athlete_note": athlete.injury_note or ""})


def _bad(message: str) -> Response:
    return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)


def _int(value, low, high):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if str(number) != str(value).strip() and number != value:
        return None
    return number if low <= number <= high else None


def _queue_adjust(athlete_id: int) -> None:
    def send():
        try:
            from apps.planning.tasks import after_pain_task

            after_pain_task.delay(athlete_id)
        except Exception:  # noqa: BLE001 — broker down must not lose the report
            pass

    transaction.on_commit(send)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def pain(request):
    athlete = request.user.athlete
    today = athlete.local_today
    if request.method == "GET":
        days = _int(request.query_params.get("days", "30"), 1, 365)
        if days is None:
            return _bad("days must be a whole number 1–365.")
        return Response([pain_json(p) for p in pains(athlete, today, days)])
    data = request.data if isinstance(request.data, dict) else {}
    location = data.get("location")
    if location not in maths.LOCATIONS:
        return _bad(f"location must be one of {', '.join(maths.LOCATIONS)}.")
    side = data.get("side")
    if side not in SIDES:
        return _bad(f"side must be one of {', '.join(SIDES)}.")
    severity = _int(data.get("severity"), 1, 3)
    if severity is None:
        return _bad("severity must be 1, 2 or 3.")
    day = today
    if data.get("date"):
        try:
            day = dt.date.fromisoformat(str(data["date"]))
        except ValueError:
            return _bad("date must be YYYY-MM-DD.")
        if day > today or day < today - dt.timedelta(days=BACKDATE_DAYS):
            return _bad("date must be within the last 14 days.")
    activity = None
    if data.get("activity_id") is not None:
        activity = Activity.objects.filter(athlete=athlete, pk=data.get("activity_id")).first()
        if activity is None:
            return _bad("activity_id is not one of your activities.")
    note = str(data.get("note") or "").strip()
    if len(note) > 200:
        return _bad("note must be under 200 characters.")
    with transaction.atomic():
        report, created = PainReport.objects.update_or_create(
            athlete=athlete, date=day, location=location, side=side,
            defaults={"severity": severity, "activity": activity, "note": note})
        if athlete.auto_adjust_plan:
            _queue_adjust(athlete.pk)
    return Response(pain_json(report), status=status.HTTP_201_CREATED if created else 200)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def pain_detail(request, pk: int):
    deleted, _ = PainReport.objects.filter(athlete=request.user.athlete, pk=pk).delete()
    if not deleted:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(status=status.HTTP_204_NO_CONTENT)
