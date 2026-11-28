"""R26 §2: the weekly mirror.

    GET /health/mirror/?week=YYYY-MM-DD    planned vs done, one row per domain

Every number here is read from somewhere that already computes it — the plan for
runs and strength, `nutrition.targets` for food, Garmin for sleep, the water log
for water. Nothing is recomputed and nothing is invented, so a row can never
disagree with the screen it came from.

The judging is all in `analysis/mirror.py`, which is pure and has no database. The
only decisions made here are which days count and what counts as a day of data,
and those are the decisions that make the difference between an honest mirror and
a discouraging one: a day he did not log food is a day with no food data, not a day
he ate nothing.
"""

from __future__ import annotations

import datetime as dt

from django.db.models import Sum
from rest_framework import status as http
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import mirror
from apps.diet.models import Meal, WaterLog
from apps.diet.services import targets_for
from apps.ingest.models import DailyMetrics
from apps.planning.models import PlannedWorkout, StrengthSession

#: A night this short is a bad read from the watch rather than a bad night, and
#: averaging it in drags the week down for a reason that is not his.
MIN_CREDIBLE_SLEEP_S = 2 * 3600
#: Sleep target when Garmin has no need figure of its own.
DEFAULT_SLEEP_NEED_S = 8 * 3600
#: Workout states that mean he did it.
DONE_STATES = ("completed",)
#: Only the plan he is actually following. A regenerated plan leaves the old one's
#: workouts on the same dates, and a pending proposal adds a second set — counting
#: those turned five planned runs into thirteen, which is the kind of number that
#: makes someone stop trusting the screen.
LIVE_PLAN_STATES = ("active",)

#: Profile fields a calorie target needs, said the way the Settings screen says them.
FIELD_SAID = {"weight_kg": "your weight", "height_cm": "your height",
              "sex": "your sex", "date_of_birth": "your date of birth"}


def _needs_profile(targets) -> str:
    """Why there is no usable target, or "" if there is one. Without his weight the
    calorie target falls back to a constant, and comparing what he ate against a
    constant and calling it his target would be the mirror's worst kind of lie."""
    gaps = [FIELD_SAID[k] for k in targets.missing if k in FIELD_SAID]
    if not gaps:
        return ""
    return f"No calorie target yet — add {' and '.join(gaps)} in Settings."


def monday(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def _runs(athlete, start: dt.date, end: dt.date) -> list[mirror.Row]:
    rows = list(PlannedWorkout.objects.filter(
        athlete=athlete, date__gte=start, date__lte=end,
        plan__status__in=LIVE_PLAN_STATES).select_related("completed_activity"))
    if not rows:
        return [mirror.Row(key="runs", label="Runs", planned=None, done=None, unit="runs"),
                mirror.Row(key="run_time", label="Time running", planned=None, done=None,
                           unit="min")]
    done = [w for w in rows if w.status in DONE_STATES]
    # Days gone by in the week, so a Wednesday mirror is not marked down for Friday.
    elapsed = _elapsed_days(athlete, start, end)
    return [
        mirror.Row(key="runs", label="Runs", planned=len(rows), done=len(done),
                   unit="runs", days=elapsed, of_days=7, needs_days=False),
        mirror.Row(key="run_time", label="Time running",
                   planned=round(sum(w.duration_s for w in rows) / 60),
                   done=round(sum(
                       (w.completed_activity.duration_s if w.completed_activity
                        and w.completed_activity.duration_s else w.duration_s)
                       for w in done) / 60) if done else 0,
                   unit="min", days=elapsed, of_days=7, needs_days=False),
    ]


def _strength(athlete, start: dt.date, end: dt.date) -> mirror.Row:
    rows = list(StrengthSession.objects.filter(
        athlete=athlete, date__gte=start, date__lte=end,
        plan__status__in=LIVE_PLAN_STATES))
    if not rows:
        return mirror.Row(key="strength", label="Strength", planned=None, done=None,
                          unit="sessions")
    done = sum(1 for s in rows if s.status == "completed")
    return mirror.Row(key="strength", label="Strength", planned=len(rows), done=done,
                      unit="sessions", days=_elapsed_days(athlete, start, end),
                      of_days=7, needs_days=False)


def _elapsed_days(athlete, start: dt.date, end: dt.date) -> int:
    """Days of the week that have actually happened. Mid-week, the rest are not
    missing data — they have not come round yet."""
    today = athlete.local_today
    last = min(end, today)
    return max(0, (last - start).days + 1) if last >= start else 0


def _food(athlete, start: dt.date, end: dt.date) -> list[mirror.Row]:
    """Average logged calories and protein against average target, over the days he
    actually logged on. Averaging over all seven would turn three unlogged days into
    a 40% shortfall that never happened."""
    per_day: dict[dt.date, dict[str, float]] = {}
    for meal in Meal.objects.filter(athlete=athlete, local_date__gte=start,
                                    local_date__lte=end):
        day = per_day.setdefault(meal.local_date, {"kcal": 0.0, "protein_g": 0.0})
        day["kcal"] += meal.kcal or 0
        day["protein_g"] += meal.protein_g or 0

    logged = sorted(per_day)
    if not logged:
        return [mirror.Row(key="kcal", label="Calories", planned=None, done=None, unit="kcal"),
                mirror.Row(key="protein", label="Protein", planned=None, done=None, unit="g")]

    # Target for the same days, so a week with a long run in it is compared against
    # the bigger target that long run earned.
    kcal_target = protein_target = 0.0
    reason = ""
    for day in logged:
        t = targets_for(athlete, day)
        kcal_target += t.kcal
        protein_target += t.protein_g
        reason = reason or _needs_profile(t)
    n = len(logged)
    elapsed = _elapsed_days(athlete, start, end)
    if reason:
        return [mirror.Row(key="kcal", label="Calories", planned=None, done=None,
                           unit="kcal", missing_reason=reason),
                mirror.Row(key="protein", label="Protein", planned=None, done=None,
                           unit="g", missing_reason=reason)]
    return [
        mirror.Row(key="kcal", label="Calories", planned=round(kcal_target / n),
                   done=round(sum(d["kcal"] for d in per_day.values()) / n),
                   unit="kcal", bad="both", days=n, of_days=elapsed),
        mirror.Row(key="protein", label="Protein", planned=round(protein_target / n),
                   done=round(sum(d["protein_g"] for d in per_day.values()) / n),
                   unit="g", bad="under", days=n, of_days=elapsed),
    ]


def _sleep(athlete, start: dt.date, end: dt.date) -> mirror.Row:
    rows = [r for r in DailyMetrics.objects.filter(
        athlete=athlete, metric_date__gte=start, metric_date__lte=end)
        if r.sleep_seconds and r.sleep_seconds >= MIN_CREDIBLE_SLEEP_S]
    if not rows:
        return mirror.Row(key="sleep", label="Sleep", planned=None, done=None, unit="h")
    needs = [r.sleep_need_seconds for r in rows if r.sleep_need_seconds]
    need = sum(needs) / len(needs) if needs else DEFAULT_SLEEP_NEED_S
    got = sum(r.sleep_seconds for r in rows) / len(rows)
    return mirror.Row(
        key="sleep", label="Sleep", planned=round(need / 3600, 1),
        done=round(got / 3600, 1), unit="h",
        # More sleep than he needs is not a problem worth a red row.
        bad="under", days=len(rows), of_days=_elapsed_days(athlete, start, end),
    )


def _water(athlete, start: dt.date, end: dt.date) -> mirror.Row:
    per_day = dict(
        WaterLog.objects.filter(athlete=athlete, local_date__gte=start, local_date__lte=end)
        .values_list("local_date").annotate(total=Sum("ml"))
    )
    if not per_day:
        return mirror.Row(key="water", label="Water", planned=None, done=None, unit="ml")
    days = sorted(per_day)
    target = sum(targets_for(athlete, d).water_ml for d in days) / len(days)
    return mirror.Row(
        key="water", label="Water", planned=round(target),
        done=round(sum(per_day.values()) / len(days)), unit="ml",
        bad="under", days=len(days), of_days=_elapsed_days(athlete, start, end),
    )


def _row_json(row: mirror.Row) -> dict:
    return {
        "key": row.key, "label": row.label, "planned": row.planned, "done": row.done,
        "unit": row.unit, "status": row.status, "gap": row.gap, "pct": row.pct,
        "note": row.note, "days": row.days, "of_days": row.of_days, "bad": row.bad,
        "needs_days": row.needs_days,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def weekly_mirror(request):
    athlete = request.user.athlete
    raw = request.query_params.get("week")
    if raw:
        try:
            start = monday(dt.date.fromisoformat(raw))
        except ValueError:
            return Response({"detail": "week must be YYYY-MM-DD."},
                            status=http.HTTP_400_BAD_REQUEST)
    else:
        start = monday(athlete.local_today)
    end = start + dt.timedelta(days=6)

    rows = [
        *_runs(athlete, start, end),
        _strength(athlete, start, end),
        *_food(athlete, start, end),
        _sleep(athlete, start, end),
        _water(athlete, start, end),
    ]
    out = mirror.build(rows)
    return Response({
        "week_start": start, "week_end": end,
        "in_progress": end >= athlete.local_today,
        "elapsed_days": _elapsed_days(athlete, start, end),
        "headline": out.headline,
        "missed": out.missed, "judged": out.judged, "worst": out.worst,
        "rows": [_row_json(r) for r in out.rows],
    })
