"""R10 §C10 weekly report card: built once per Monday–Sunday week, stored, and shown on
Today on Mondays and in Health. Deterministic; the AI paragraph is optional and gets the
report minus the private habit."""

from __future__ import annotations

import datetime as dt
import json

from django.utils import timezone
from rest_framework import status as http
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import weekly_report as maths
from apps.activities.models import Activity
from apps.coaching.throttles import ChatThrottle
from apps.ingest.models import DailyMetrics

from .common import BadRequest
from .models import WeeklyReport

REPORT_HOUR = 6
LIST_MAX = 52


def monday(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def last_complete_week(athlete) -> dt.date:
    return monday(athlete.local_today) - dt.timedelta(days=7)


def _runs(athlete, start: dt.date, end: dt.date) -> tuple[dict, dict]:
    from apps.planning.models import PlannedWorkout, TrainingPlan

    acts = list(Activity.objects.filter(athlete=athlete, sport__icontains="run",
                                        local_date__gte=start, local_date__lte=end)
                .select_related("metrics"))
    zones: dict[str, int] = {}
    for a in acts:
        for key, seconds in ((getattr(a, "metrics", None) and a.metrics.time_in_zone) or {}).items():
            zones[key] = zones.get(key, 0) + round(seconds or 0)
    planned = (PlannedWorkout.objects.filter(athlete=athlete, date__gte=start, date__lte=end)
               .exclude(kind__in=["REST", "WALK"])
               .exclude(plan__status__in=[TrainingPlan.Status.PROPOSED,
                                          TrainingPlan.Status.DECLINED]))
    runs = {
        "done": len(acts),
        "planned": planned.count(),
        "planned_done": planned.filter(status=PlannedWorkout.Status.COMPLETED).count(),
        "km": round(sum(a.total_distance_m or 0 for a in acts) / 1000, 1),
        "run_km": round(sum(a.metrics.run_distance_m for a in acts
                            if getattr(a, "metrics", None)) / 1000, 1),
        "time_s": round(sum(a.total_timer_s or 0 for a in acts)),
    }
    return runs, zones


def _wellness(athlete, start: dt.date, end: dt.date) -> dict[str, list]:
    rows = DailyMetrics.objects.filter(athlete=athlete, metric_date__gte=start,
                                       metric_date__lte=end)
    return {"hrv": [r.hrv_overnight_avg for r in rows],
            "rhr": [r.resting_hr for r in rows],
            "sleep": [r.sleep_seconds / 3600 if r.sleep_seconds else None for r in rows],
            "sleep_score": [r.sleep_score for r in rows]}


def _habit_totals(athlete, kinds, start, end) -> dict[str, float]:
    from django.db.models import Sum

    from apps.habits.models import HabitLog

    rows = (HabitLog.objects.filter(athlete=athlete, kind__in=kinds, local_date__gte=start,
                                    local_date__lte=end)
            .values("kind").annotate(total=Sum("quantity")))
    return {r["kind"]: r["total"] or 0.0 for r in rows}


def _tracked_kinds(athlete, this_week, previous_week) -> list[str]:
    from apps.habits.services import kinds_for

    goals = {"smoke": athlete.smoke_goal, "alcohol": athlete.alcohol_goal,
             "sugar": athlete.sugar_goal, "private": athlete.private_goal}
    out = []
    for kind in kinds_for(athlete):
        if (this_week.get(kind) or previous_week.get(kind)
                or goals[kind] not in ("none", "")
                or (kind == "smoke" and athlete.smoke_quit_date)):
            out.append(kind)
    return out


def build_payload(athlete, week_start: dt.date) -> dict:
    from .garmin_views import records_list

    end = week_start + dt.timedelta(days=6)
    prev_start, prev_end = week_start - dt.timedelta(days=7), week_start - dt.timedelta(days=1)
    runs, zones = _runs(athlete, week_start, end)
    previous, _ = _runs(athlete, prev_start, prev_end)
    runs["previous_done"] = previous["done"]
    runs["previous_km"] = previous["km"]
    wellness = maths.wellness_rows(_wellness(athlete, week_start, end),
                                   _wellness(athlete, prev_start, prev_end))
    from apps.habits.services import kinds_for

    kinds = list(kinds_for(athlete))
    this_h = _habit_totals(athlete, kinds, week_start, end)
    prev_h = _habit_totals(athlete, kinds, prev_start, prev_end)
    habits = maths.habit_rows(this_h, prev_h, _tracked_kinds(athlete, this_h, prev_h))
    prs = [{"key": r["key"], "label": r["label"], "display": r["display"],
            "date": r["date"].isoformat()}
           for r in records_list(athlete) if r["date"] and week_start <= r["date"] <= end]
    good, improve, goal = maths.bullets(runs=runs, wellness=wellness, habits=habits, prs=prs,
                                        zones=zones)
    zones_total = sum(v for k, v in zones.items() if k != "below")
    return {"week_start": week_start.isoformat(), "week_end": end.isoformat(), "runs": runs,
            "zones": zones, "zones_total_s": zones_total, "prs": prs, "wellness": wellness,
            "habits": habits, "went_well": good, "to_improve": improve, "goal": goal}


def get_or_build(athlete, week_start: dt.date) -> WeeklyReport:
    report = WeeklyReport.objects.filter(athlete=athlete, week_start=week_start).first()
    if report is None:
        report, _ = WeeklyReport.objects.get_or_create(
            athlete=athlete, week_start=week_start,
            defaults={"payload": build_payload(athlete, week_start)})
    return report


def report_json(report: WeeklyReport) -> dict:
    p = report.payload
    habits = [h for h in p.get("habits", [])
              if h["habit"] != "private" or report.athlete.private_habit_enabled]
    # Bullets re-derived on read, so turning the private habit off also drops its lines.
    good, improve, goal = maths.bullets(runs=p["runs"], wellness=p.get("wellness", []),
                                        habits=habits, prs=p.get("prs", []),
                                        zones=p.get("zones", {}))
    return {
        "id": report.pk, "week_start": report.week_start,
        "week_end": report.week_start + dt.timedelta(days=6),
        "generated_at": report.created_at,
        "runs": p.get("runs", {}), "zones": p.get("zones", {}),
        "zones_total_s": p.get("zones_total_s", 0), "prs": p.get("prs", []),
        "wellness": p.get("wellness", []), "habits": habits,
        "went_well": good, "to_improve": improve, "goal": goal,
        "ai": ai_state(report),
    }


def ai_state(report: WeeklyReport) -> dict:
    if report.ai_markdown:
        return {"status": "ready", "markdown": report.ai_markdown,
                "generated_at": report.ai_generated_at}
    return {"status": "none", "markdown": "", "generated_at": None}


# --- AI paragraph -----------------------------------------------------------------------

WEEKLY_USER = """This is an athlete's weekly report card for {week_start} to {week_end}, \
calculated in Python: runs done against the plan, distance, time in heart-rate zones, \
personal records, HRV / resting HR / sleep against the week before, habits against the week \
before, and the deterministic went-well / to-improve bullets and goal.

{payload}

Write 60-120 words of markdown: one encouraging paragraph that ties these together and \
backs the goal. Use only numbers above with their units. Describe associations, never \
causes. Never suggest training harder than the plan."""


def ai_payload(report: WeeklyReport) -> dict:
    """The report without the private habit (no row, bullet or goal mentions it), and
    with the bullets recomputed so not even a count hints at it."""
    p = report.payload
    habits = [h for h in p.get("habits", []) if h["habit"] != "private"]
    good, improve, goal = maths.bullets(runs=p["runs"], wellness=p["wellness"], habits=habits,
                                        prs=p.get("prs", []), zones=p.get("zones", {}),
                                        ai_safe=True)
    return {"week_start": p["week_start"], "week_end": p["week_end"], "runs": p["runs"],
            "zones_seconds": p.get("zones", {}), "prs": p.get("prs", []),
            "wellness": p["wellness"], "habits": habits, "went_well": good,
            "to_improve": improve, "goal": goal}


def generate_ai(report: WeeklyReport, refresh: bool = False) -> dict:
    """Raises AIUnavailable (incl. BudgetExceeded). Coach tier; cached on the report
    and by input hash in AIAnalysis."""
    from apps.coaching.models import AIAnalysis
    from apps.coaching.schemas import WeeklyReportSummary
    from apps.coaching.services import _run

    if report.ai_markdown and not refresh:
        return ai_state(report)
    payload = ai_payload(report)
    if refresh:
        from apps.coaching.client import canonical_hash, model_for
        from apps.coaching.prompts import PROMPT_VERSION

        digest = canonical_hash(payload, PROMPT_VERSION, model_for("weekly_report"))
        AIAnalysis.objects.filter(athlete=report.athlete, kind=AIAnalysis.Kind.WEEKLY_CARD,
                                  input_hash=digest).delete()
    result, _ = _run(report.athlete, kind=AIAnalysis.Kind.WEEKLY_CARD,
                     operation="weekly_report", payload=payload,
                     user_prompt=WEEKLY_USER.format(
                         week_start=payload["week_start"], week_end=payload["week_end"],
                         payload=json.dumps(payload, indent=2, default=str)),
                     schema=WeeklyReportSummary)
    report.ai_markdown = result.markdown
    report.ai_generated_at = timezone.now()
    report.save(update_fields=["ai_markdown", "ai_generated_at"])
    return ai_state(report)


# --- views ------------------------------------------------------------------------------

def _week(request, athlete) -> dt.date:
    raw = request.query_params.get("week")
    if not raw:
        return last_complete_week(athlete)
    try:
        day = dt.date.fromisoformat(raw)
    except ValueError as exc:
        raise BadRequest("week must be a date (YYYY-MM-DD).") from exc
    start = monday(day)
    if start > last_complete_week(athlete):
        raise BadRequest("That week isn't over yet — reports cover complete weeks.")
    return start


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def weekly(request):
    athlete = request.user.athlete
    return Response(report_json(get_or_build(athlete, _week(request, athlete))))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def weekly_list(request):
    rows = WeeklyReport.objects.filter(athlete=request.user.athlete)[:LIST_MAX]
    return Response([{"id": r.pk, "week_start": r.week_start,
                      "week_end": r.week_start + dt.timedelta(days=6),
                      "runs_done": (r.payload.get("runs") or {}).get("done", 0),
                      "km": (r.payload.get("runs") or {}).get("km", 0.0),
                      "generated_at": r.created_at} for r in rows])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatThrottle])
def weekly_ai(request):
    from apps.coaching.client import AIUnavailable

    athlete = request.user.athlete
    report = get_or_build(athlete, _week(request, athlete))
    try:
        return Response(generate_ai(report, refresh=request.query_params.get("refresh") == "1"))
    except AIUnavailable as exc:
        return Response({"detail": str(exc) or "The coach is unavailable right now."},
                        status=http.HTTP_503_SERVICE_UNAVAILABLE)
