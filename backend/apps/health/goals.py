"""R14 §8: long-term goals. Values come from the athlete's own data; the maths
(progress, milestones, projection) is in analysis/goals.py."""

from __future__ import annotations

import datetime as dt
import statistics

from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import goals as maths

from .models import Achievement, Goal, GoalEntry

MAX_ACTIVE = 10
MAX_POINTS = 120
PRED_FIELD = {5.0: "race_pred_5k_s", 10.0: "race_pred_10k_s", 21.1: "race_pred_half_s",
              42.2: "race_pred_marathon_s"}
SOURCE = {"race_time": "garmin_prediction", "distance": "runs", "weight": "weight_log",
          "smoke_free_days": "habits", "vo2max": "garmin", "resting_hr": "garmin",
          "weekly_km": "runs", "custom": "manual"}


def _bad(message: str, code: int = 400) -> Response:
    return Response({"detail": message}, status=code)


# --- data -------------------------------------------------------------------------------

def _daily_metric(athlete, field: str, since: dt.date) -> list[tuple[dt.date, float]]:
    from apps.ingest.models import DailyMetrics

    return [(d, float(v)) for d, v in DailyMetrics.objects.filter(
        athlete=athlete, metric_date__gte=since, **{f"{field}__isnull": False})
        .order_by("metric_date").values_list("metric_date", field)]


def _weights(athlete, since: dt.date) -> list[tuple[dt.date, float]]:
    from apps.athletes.models import MetricEntry
    from apps.health.common import zone_of
    from apps.ingest.models import BodyComposition

    zone = zone_of(athlete)
    days: dict[dt.date, float] = {}
    for day, value in BodyComposition.objects.filter(
            athlete=athlete, measured_on__gte=since, weight_kg__isnull=False) \
            .order_by("measured_on").values_list("measured_on", "weight_kg"):
        days[day] = float(value)
    for at, value in MetricEntry.objects.filter(athlete=athlete, kind="weight") \
            .order_by("recorded_at").values_list("recorded_at", "value"):
        day = at.astimezone(zone).date()
        if day >= since:
            days[day] = float(value)
    return sorted(days.items())


def _run_days(athlete, since: dt.date) -> dict[dt.date, list[float]]:
    from apps.activities.models import Activity

    out: dict[dt.date, list[float]] = {}
    for day, metres in Activity.objects.filter(athlete=athlete, sport__icontains="run",
                                               local_date__gte=since) \
            .values_list("local_date", "total_distance_m"):
        out.setdefault(day, []).append((metres or 0) / 1000)
    return out


def series_for(goal: Goal, today: dt.date, since: dt.date | None = None) -> list[tuple[dt.date, float]]:
    athlete = goal.athlete
    since = since or goal.start_date
    kind = goal.kind
    if kind == "race_time":
        field = PRED_FIELD.get(goal.distance_km or 0)
        return _daily_metric(athlete, field, since) if field else []
    if kind == "vo2max":
        return _daily_metric(athlete, "vo2max", since)
    if kind == "resting_hr":
        raw = _daily_metric(athlete, "resting_hr", since - dt.timedelta(days=6))
        out = []
        for day, _ in raw:
            if day < since:
                continue
            window = [v for d, v in raw if day - dt.timedelta(days=6) <= d <= day]
            out.append((day, float(statistics.median(window))))
        return out
    if kind == "weight":
        return _weights(athlete, since)
    if kind == "distance":
        runs = _run_days(athlete, since)
        best, out = 0.0, []
        for day in sorted(runs):
            longest = max(runs[day])
            if longest > best:
                best = longest
                out.append((day, round(best, 2)))
        return out
    if kind == "weekly_km":
        runs = _run_days(athlete, since - dt.timedelta(days=6))
        out = []
        day = since
        while day <= today:
            total = sum(sum(v) for d, v in runs.items() if day - dt.timedelta(days=6) <= d <= day)
            out.append((day, round(total, 1)))
            day += dt.timedelta(days=1)
        return out
    if kind == "smoke_free_days":
        return _smoke_series(athlete, since, today)
    return [(e.date, e.value) for e in goal.entries.filter(date__gte=since)]


def _smoke_series(athlete, since: dt.date, today: dt.date) -> list[tuple[dt.date, float]]:
    from analysis import habits as habit_maths
    from apps.habits.models import HabitLog

    logs = list(HabitLog.objects.filter(athlete=athlete, kind="smoke")
                .values_list("local_date", "quantity"))
    totals = habit_maths.daily_totals(logs)
    starts = [d for d in (min(totals) if totals else None, athlete.smoke_quit_date) if d]
    if not starts:
        return []
    day, streak, out = min(starts), 0, []
    while day < today:                      # only finished days count
        streak = 0 if totals.get(day, 0) > 0 else streak + 1
        if day >= since:
            out.append((day, float(streak)))
        day += dt.timedelta(days=1)
    return out


def current_value(goal: Goal, today: dt.date) -> tuple[float | None, dt.date | None]:
    if goal.kind == "distance":
        series = series_for(goal, today)
        if series:
            return series[-1][1], series[-1][0]
        return goal.start_value, None
    if goal.kind == "weekly_km":
        series = series_for(goal, today, since=today)
        return (series[-1][1], today) if series else (None, None)
    lookback = today - dt.timedelta(days=400)
    series = series_for(goal, today, since=min(goal.start_date, lookback)
                        if goal.kind != "custom" else goal.start_date - dt.timedelta(days=3650))
    if not series:
        return None, None
    return series[-1][1], series[-1][0]


def initial_value(athlete, kind: str, distance_km: float | None, today: dt.date) -> float | None:
    probe = Goal(athlete=athlete, kind=kind, target=0, start_date=today, distance_km=distance_km)
    if kind == "distance":
        runs = _run_days(athlete, today - dt.timedelta(days=30))
        return round(max((max(v) for v in runs.values()), default=0.0), 2)
    if kind == "custom":
        return None
    value, _ = current_value(probe, today)
    return value


# --- presentation -----------------------------------------------------------------------

def _thin(series: list, limit: int = MAX_POINTS) -> list:
    if len(series) <= limit:
        return series
    step = len(series) / limit
    picked = [series[int(i * step)] for i in range(limit - 1)]
    return picked + [series[-1]]


def _award(goal: Goal, reached: dict) -> None:
    from .achievements import _store

    for pct, day in reached.items():
        if day is not None:
            _store(goal.athlete, f"goal_{goal.pk}_{pct}", Achievement.Kind.BADGE,
                   f"Goal {pct}%: {goal.title}"[:120], day)


def goal_json(goal: Goal, today: dt.date) -> dict:
    way = maths.direction(goal.start_value, goal.target, goal.kind)
    series = series_for(goal, today)
    if goal.start_value is not None:
        series = [(goal.start_date, goal.start_value)] + [p for p in series
                                                          if p[0] >= goal.start_date]
    current, as_of = current_value(goal, today)
    pct = maths.progress_pct(goal.start_value, current, goal.target, way)
    reached = maths.reached_on(series, goal.start_value, goal.target, way) \
        if goal.start_value is not None else {m: None for m in maths.MILESTONES}
    if goal.status == Goal.Status.ACTIVE:
        _award(goal, reached)
        if reached.get(100) is not None or pct == 100:
            goal.status = Goal.Status.ACHIEVED
            goal.achieved_on = reached.get(100) or today
            goal.save(update_fields=["status", "achieved_on"])
    projection = maths.project(series, goal.target, way, today, goal.target_date)
    start = goal.start_value
    milestones = [{"pct": m,
                   "value": round(maths.milestone_value(start, goal.target, m), 2)
                   if start is not None else goal.target if m == 100 else None,
                   "reached_on": reached.get(m)} for m in maths.MILESTONES]
    show = maths.display(goal.kind, current, goal.unit)
    chip = f"{goal.title}: {pct}%" if pct is not None else goal.title
    if show:
        chip += f" · now {show}"
    return {
        "id": goal.pk, "kind": goal.kind, "title": goal.title, "unit": goal.unit,
        "target": goal.target, "target_date": goal.target_date,
        "start_value": goal.start_value, "start_date": goal.start_date,
        "distance_km": goal.distance_km, "direction": way,
        "current": round(current, 2) if current is not None else None,
        "current_as_of": as_of, "current_source": SOURCE[goal.kind] if current is not None else None,
        "progress_pct": pct, "status": goal.status, "achieved_on": goal.achieved_on,
        "milestones": milestones,
        "projection": {"date": projection.date, "method": projection.method,
                       "label": "estimate", "on_track": projection.on_track,
                       "note": projection.note},
        "series": [{"date": d, "value": v} for d, v in _thin(series)],
        "display": {"target": maths.display(goal.kind, goal.target, goal.unit),
                    "current": show,
                    "start": maths.display(goal.kind, goal.start_value, goal.unit)},
        "chip": chip, "created_at": goal.created_at,
    }


def _default_title(kind: str, target: float, distance_km: float | None, unit: str) -> str:
    if kind == "race_time":
        name = maths.RACE_DISTANCES.get(distance_km or 0, f"{distance_km:g} km")
        return f"{name} in {maths.clock(target)}"
    template = maths.KINDS[kind][1]
    text = template.format(target=f"{target:g}", distance="")
    return f"{text} {unit}".strip() if kind == "custom" else text


def _number(value, name, lo, hi):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not lo <= value <= hi:
        raise ValueError(f"{name} must be a number {lo:g}–{hi:g}.")
    return float(value)


LIMITS = {"race_time": (300, 86400), "distance": (0.5, 400), "weight": (25, 300),
          "smoke_free_days": (1, 3650), "vo2max": (15, 95), "resting_hr": (25, 120),
          "weekly_km": (1, 400), "custom": (-1e9, 1e9)}


# --- views ------------------------------------------------------------------------------

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def goals(request):
    athlete = request.user.athlete
    today = athlete.local_today
    if request.method == "GET":
        which = request.query_params.get("status") or "active"
        if which not in ("all", *Goal.Status.values):
            return _bad("status must be active, achieved, abandoned or all.")
        rows = Goal.objects.filter(athlete=athlete)
        if which != "all":
            rows = rows.filter(status=which)
        out = [goal_json(g, today) for g in rows]
        if which != "all":
            out = [g for g in out if g["status"] == which]
        return Response(out)

    data = request.data
    kind = data.get("kind")
    if kind not in maths.KINDS:
        return _bad(f"kind must be one of {', '.join(maths.KINDS)}.")
    try:
        target = _number(data.get("target"), "target", *LIMITS[kind])
        distance = None
        if kind == "race_time":
            distance = _number(data.get("distance_km"), "distance_km", 1, 100)
            if distance not in PRED_FIELD:
                raise ValueError("distance_km must be 5, 10, 21.1 or 42.2.")
        start_value = data.get("start_value")
        if start_value is not None:
            start_value = _number(start_value, "start_value", *LIMITS[kind])
    except ValueError as exc:
        return _bad(str(exc))
    unit = maths.KINDS[kind][0]
    if kind == "custom":
        unit = data.get("unit") or ""
        if not isinstance(unit, str) or len(unit) > 12:
            return _bad("unit must be at most 12 characters.")
        if start_value is None:
            return _bad("start_value is required for a custom goal.")
    target_date = None
    if data.get("target_date"):
        try:
            target_date = dt.date.fromisoformat(str(data["target_date"]))
        except ValueError:
            return _bad("target_date must be a date (YYYY-MM-DD).")
        if target_date <= today:
            return _bad("target_date must be in the future.")
    if start_value is None:
        start_value = initial_value(athlete, kind, distance, today)
        if start_value is None:
            return _bad("There's no data for this yet — give start_value.")
    title = data.get("title") or _default_title(kind, target, distance, unit)
    if not isinstance(title, str) or len(title) > 80:
        return _bad("title must be at most 80 characters.")
    with transaction.atomic():
        if Goal.objects.filter(athlete=athlete, status=Goal.Status.ACTIVE).count() >= MAX_ACTIVE:
            return _bad(f"You can have at most {MAX_ACTIVE} active goals.", 409)
        goal = Goal.objects.create(athlete=athlete, kind=kind, title=title.strip(), unit=unit,
                                   target=target, target_date=target_date,
                                   start_value=start_value, start_date=today,
                                   distance_km=distance)
        if kind == "custom":
            GoalEntry.objects.create(goal=goal, date=today, value=start_value)
    return Response(goal_json(goal, today), status=201)


def _get(request, pk):
    return Goal.objects.filter(athlete=request.user.athlete, pk=pk).first()


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def goal_detail(request, pk: int):
    goal = _get(request, pk)
    if goal is None:
        return _bad("Not found.", 404)
    today = request.user.athlete.local_today
    if request.method == "DELETE":
        goal.delete()
        return Response(status=204)
    if request.method == "PATCH":
        data = request.data
        fields = []
        if "title" in data:
            if not isinstance(data["title"], str) or not data["title"].strip() \
                    or len(data["title"]) > 80:
                return _bad("title must be 1–80 characters.")
            goal.title = data["title"].strip()
            fields.append("title")
        if "target" in data:
            try:
                goal.target = _number(data["target"], "target", *LIMITS[goal.kind])
            except ValueError as exc:
                return _bad(str(exc))
            fields.append("target")
        if "target_date" in data:
            raw = data["target_date"]
            if raw is None:
                goal.target_date = None
            else:
                try:
                    goal.target_date = dt.date.fromisoformat(str(raw))
                except ValueError:
                    return _bad("target_date must be a date (YYYY-MM-DD).")
                if goal.target_date <= today:
                    return _bad("target_date must be in the future.")
            fields.append("target_date")
        if "status" in data:
            if data["status"] not in ("active", "abandoned"):
                return _bad("status must be active or abandoned.")
            goal.status = data["status"]
            if goal.status == "active":
                goal.achieved_on = None
                fields.append("achieved_on")
            fields.append("status")
        if fields:
            goal.save(update_fields=fields)
    return Response(goal_json(goal, today))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def goal_values(request, pk: int):
    goal = _get(request, pk)
    if goal is None:
        return _bad("Not found.", 404)
    if goal.kind != "custom":
        return _bad("Only custom goals take values by hand — the rest come from your data.")
    today = request.user.athlete.local_today
    try:
        value = _number(request.data.get("value"), "value", *LIMITS["custom"])
    except ValueError as exc:
        return _bad(str(exc))
    day = today
    if request.data.get("date"):
        try:
            day = dt.date.fromisoformat(str(request.data["date"]))
        except ValueError:
            return _bad("date must be a date (YYYY-MM-DD).")
        if day > today:
            return _bad("date can't be in the future.")
    GoalEntry.objects.create(goal=goal, date=day, value=value)
    return Response(goal_json(goal, today), status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def goal_chip(request):
    athlete = request.user.athlete
    today = athlete.local_today
    rows = [goal_json(g, today) for g in Goal.objects.filter(athlete=athlete,
                                                             status=Goal.Status.ACTIVE)]
    rows = [g for g in rows if g["status"] == "active"]
    if not rows:
        return Response({"goal": None, "text": None})
    best = max(rows, key=lambda g: (g["progress_pct"] or -1, -g["id"]))
    return Response({"goal": best, "text": best["chip"]})
