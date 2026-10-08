"""R13 §11 monthly health report: built once per calendar month (the 1st at 06:00 local,
or on first read), stored, and listed with the weekly reports. Deterministic; the AI
paragraph is optional and gets the report minus the private habit and mood notes."""

from __future__ import annotations

import datetime as dt
import json

from django.utils import timezone
from rest_framework import status as http
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import monthly_report as maths
from apps.activities.models import Activity
from apps.coaching.throttles import ChatThrottle

from .common import BadRequest
from .models import MonthlyReport, PainReport
from .reports import _habit_totals, _runs, _tracked_kinds, _wellness

REPORT_HOUR = 6
LIST_MAX = 24


def month_start(day: dt.date) -> dt.date:
    return day.replace(day=1)


def month_end(first: dt.date) -> dt.date:
    return (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)


def previous_month(first: dt.date) -> dt.date:
    return month_start(first - dt.timedelta(days=1))


def last_complete_month(athlete) -> dt.date:
    return previous_month(month_start(athlete.local_today))


def _fitness(athlete, start, end) -> dict:
    from apps.ingest.models import DailyMetrics

    out = {}
    for key, field in (("vo2max", "vo2max"), ("fitness_age", "fitness_age")):
        values = list(DailyMetrics.objects.filter(
            athlete=athlete, metric_date__gte=start, metric_date__lte=end,
            **{f"{field}__isnull": False}).order_by("metric_date").values_list(field, flat=True))
        out[key] = maths.change(values[0] if values else None, values[-1] if values else None)
    return out


def _weight(athlete, start, end) -> dict | None:
    from apps.athletes.models import MetricEntry

    rows = list(MetricEntry.objects.filter(
        athlete=athlete, kind="weight", recorded_at__date__gte=start,
        recorded_at__date__lte=end).order_by("recorded_at").values_list("value", flat=True))
    if len(rows) < 2:
        return None
    return maths.change(round(rows[0], 1), round(rows[-1], 1))


def _smoke_free_days(athlete, start, end) -> int | None:
    from apps.habits.services import _totals

    totals = _totals(athlete, "smoke")
    tracked = totals or athlete.smoke_quit_date or athlete.smoke_goal in ("quit", "reduce")
    if not tracked:
        return None
    starts = [d for d in (min(totals) if totals else None, athlete.smoke_quit_date) if d]
    first = max(start, min(starts)) if starts else start
    last = min(end, athlete.local_today - dt.timedelta(days=1))
    if first > last:
        return 0
    return sum(1 for i in range((last - first).days + 1)
               if totals.get(first + dt.timedelta(days=i), 0) <= 0)


def _injury(athlete, start, end) -> dict:
    rows = list(PainReport.objects.filter(athlete=athlete, date__gte=start, date__lte=end))
    spots: dict[tuple, set] = {}
    for r in rows:
        if r.severity >= 2:
            spots.setdefault((r.location, r.side), set()).add(r.date)
    return {"flags": sum(1 for days in spots.values() if len(days) >= 2),
            "pain_days": len({r.date for r in rows})}


def build_payload(athlete, first: dt.date) -> dict:
    from apps.habits.services import CAFFEINE, kinds_for

    from .garmin_views import records_list
    from .mood import block as mood_block

    end = month_end(first)
    prev_first = previous_month(first)
    prev_end = first - dt.timedelta(days=1)
    runs, _ = _runs(athlete, first, end)
    previous, _ = _runs(athlete, prev_first, prev_end)
    longest = max((a.total_distance_m or 0 for a in Activity.objects.filter(
        athlete=athlete, sport__icontains="run", local_date__gte=first, local_date__lte=end)),
        default=0)
    month_runs = {"count": runs["done"], "km": runs["km"], "run_km": runs["run_km"],
                  "time_s": runs["time_s"], "longest_km": round(longest / 1000, 1),
                  "previous_count": previous["done"], "previous_km": previous["km"],
                  "planned": runs["planned"], "planned_done": runs["planned_done"]}
    wellness = maths.wellness_rows(_wellness(athlete, first, end),
                                   _wellness(athlete, prev_first, prev_end))
    kinds = list(kinds_for(athlete)) + [CAFFEINE]
    this_h = _habit_totals(athlete, kinds, first, end)
    prev_h = _habit_totals(athlete, kinds, prev_first, prev_end)
    tracked = _tracked_kinds(athlete, this_h, prev_h)
    if this_h.get(CAFFEINE) or prev_h.get(CAFFEINE):
        tracked.append(CAFFEINE)
    habits = maths.habit_rows(this_h, prev_h, tracked)
    prs = [{"key": r["key"], "label": r["label"], "display": r["display"],
            "date": r["date"].isoformat()}
           for r in records_list(athlete) if r["date"] and first <= r["date"] <= end]
    fitness = _fitness(athlete, first, end)
    mood = mood_block(athlete, first, end, prev_first, prev_end)
    weight = _weight(athlete, first, end)
    injury = _injury(athlete, first, end)
    smoke_free = _smoke_free_days(athlete, first, end)
    return {"month": first.strftime("%Y-%m"), "start": first.isoformat(),
            "end": end.isoformat(), "runs": month_runs, "prs": prs, "fitness": fitness,
            "wellness": wellness, "habits": habits, "smoke_free_days": smoke_free,
            "mood": mood, "weight": weight, "injury": injury}


def _bullets(payload: dict, athlete, *, ai_safe: bool) -> tuple[list, list, str]:
    habits = [h for h in payload.get("habits", [])
              if h["habit"] != "private" or (athlete.private_habit_enabled and not ai_safe)]
    return maths.bullets(runs=payload["runs"], prs=payload.get("prs", []),
                         fitness=payload.get("fitness", {}),
                         wellness=payload.get("wellness", []), habits=habits,
                         smoke_free_days=payload.get("smoke_free_days"),
                         mood=payload.get("mood", {}), weight=payload.get("weight"),
                         diet_goal=athlete.diet_goal, injury=payload.get("injury", {}),
                         ai_safe=ai_safe)


def get_or_build(athlete, first: dt.date) -> MonthlyReport:
    report = MonthlyReport.objects.filter(athlete=athlete, month=first).first()
    if report is None:
        report, _ = MonthlyReport.objects.get_or_create(
            athlete=athlete, month=first, defaults={"payload": build_payload(athlete, first)})
    return report


def ai_state(report: MonthlyReport) -> dict:
    if report.ai_markdown:
        return {"status": "ready", "markdown": report.ai_markdown,
                "generated_at": report.ai_generated_at}
    return {"status": "none", "markdown": "", "generated_at": None}


def report_json(report: MonthlyReport) -> dict:
    p = report.payload
    athlete = report.athlete
    habits = [h for h in p.get("habits", [])
              if h["habit"] != "private" or athlete.private_habit_enabled]
    good, improve, goal = _bullets(p, athlete, ai_safe=False)
    from .reports import RESTED_LINE, illness_rows

    illness = illness_rows(athlete, dt.date.fromisoformat(str(p.get("start"))),
                           dt.date.fromisoformat(str(p.get("end"))), "days_in_month") \
        if p.get("start") and p.get("end") else []
    if illness:
        good = [RESTED_LINE] + [g for g in good if g != RESTED_LINE]
    return {"illness": illness, "id": report.pk, "month": p.get("month"), "start": p.get("start"),
            "end": p.get("end"), "generated_at": report.created_at, "runs": p.get("runs", {}),
            "prs": p.get("prs", []), "fitness": p.get("fitness", {}),
            "wellness": p.get("wellness", []), "habits": habits,
            "smoke_free_days": p.get("smoke_free_days"), "mood": p.get("mood", {}),
            "weight": p.get("weight"), "injury": p.get("injury", {}),
            "went_well": good, "to_improve": improve, "goal": goal, "ai": ai_state(report)}


MONTHLY_USER = """This is an athlete's monthly health report for {month}, calculated in \
Python: runs, distance, personal records, VO2max / fitness age change, HRV / resting HR / \
sleep against the month before, habits, average mood and energy (1-5), weight change, \
injury-watch counts, and the deterministic went-well / to-improve bullets and goal.

{payload}

Write 80-140 words of markdown: one encouraging paragraph that ties the month together \
and backs the goal. Use only numbers above with their units. Describe associations, never \
causes, and never diagnose. Never suggest training harder than the plan."""


def ai_payload(report: MonthlyReport) -> dict:
    p = report.payload
    good, improve, goal = _bullets(p, report.athlete, ai_safe=True)
    return {"month": p["month"], "runs": p["runs"], "prs": p.get("prs", []),
            "fitness": p.get("fitness", {}), "wellness": p.get("wellness", []),
            "habits": [h for h in p.get("habits", []) if h["habit"] != "private"],
            "smoke_free_days": p.get("smoke_free_days"),
            "mood": {k: v for k, v in (p.get("mood") or {}).items() if k != "days"},
            "weight": p.get("weight"), "injury": p.get("injury", {}),
            "went_well": good, "to_improve": improve, "goal": goal}


def generate_ai(report: MonthlyReport, refresh: bool = False) -> dict:
    from apps.coaching.models import AIAnalysis
    from apps.coaching.schemas import ShortParagraph
    from apps.coaching.services import _run

    if report.ai_markdown and not refresh:
        return ai_state(report)
    payload = ai_payload(report)
    if refresh:
        from apps.coaching.client import canonical_hash, model_for
        from apps.coaching.prompts import PROMPT_VERSION

        digest = canonical_hash(payload, PROMPT_VERSION, model_for("monthly_report"))
        AIAnalysis.objects.filter(athlete=report.athlete, kind=AIAnalysis.Kind.MONTHLY_CARD,
                                  input_hash=digest).delete()
    result, _ = _run(report.athlete, kind=AIAnalysis.Kind.MONTHLY_CARD,
                     operation="monthly_report", payload=payload,
                     user_prompt=MONTHLY_USER.format(
                         month=payload["month"],
                         payload=json.dumps(payload, indent=2, default=str)),
                     schema=ShortParagraph)
    report.ai_markdown = result.markdown
    report.ai_generated_at = timezone.now()
    report.save(update_fields=["ai_markdown", "ai_generated_at"])
    return ai_state(report)


def _month(request, athlete) -> dt.date:
    raw = request.query_params.get("month")
    if not raw:
        return last_complete_month(athlete)
    try:
        first = dt.datetime.strptime(raw, "%Y-%m").date()
    except ValueError as exc:
        raise BadRequest("month must be YYYY-MM.") from exc
    if first > last_complete_month(athlete):
        raise BadRequest("That month isn't over yet — reports cover complete months.")
    return first


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def monthly(request):
    athlete = request.user.athlete
    return Response(report_json(get_or_build(athlete, _month(request, athlete))))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def monthly_list(request):
    rows = MonthlyReport.objects.filter(athlete=request.user.athlete)[:LIST_MAX]
    return Response([{"id": r.pk, "month": r.month.strftime("%Y-%m"),
                      "runs_done": (r.payload.get("runs") or {}).get("count", 0),
                      "km": (r.payload.get("runs") or {}).get("km", 0.0),
                      "generated_at": r.created_at} for r in rows])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatThrottle])
def monthly_ai(request):
    from apps.coaching.client import AIUnavailable

    athlete = request.user.athlete
    report = get_or_build(athlete, _month(request, athlete))
    try:
        return Response(generate_ai(report, refresh=request.query_params.get("refresh") == "1"))
    except AIUnavailable as exc:
        return Response({"detail": str(exc) or "The coach is unavailable right now."},
                        status=http.HTTP_503_SERVICE_UNAVAILABLE)
