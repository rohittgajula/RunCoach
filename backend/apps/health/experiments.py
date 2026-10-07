"""R14 §7: self-experiments — endpoints and the data they read.

Adherence and the before/during comparison are computed in analysis/experiments.py
(pure); this file gathers the logs (habits, caffeine times, Garmin sleep start, steps,
nightly HRV/RHR/sleep score, stress, mood, easy-run HR) and stores the experiment.
No AI is involved anywhere, so the private habit is allowed (labelled "Private").
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import experiments as maths

from .common import zone_of
from .models import Experiment

START_AHEAD_DAYS = 14
OPEN = (Experiment.Status.SCHEDULED, Experiment.Status.ACTIVE)


def _bad(message: str, code: int = 400) -> Response:
    return Response({"detail": message}, status=code)


def refresh_status(exp: Experiment, today: dt.date) -> Experiment:
    """Scheduled → active → completed by the calendar (stopped stays stopped)."""
    if exp.status == Experiment.Status.STOPPED:
        return exp
    want = (Experiment.Status.SCHEDULED if today < exp.start else
            Experiment.Status.ACTIVE if today <= exp.end else Experiment.Status.COMPLETED)
    if want != exp.status:
        exp.status = want
        fields = ["status"]
        if want == Experiment.Status.COMPLETED and exp.ended_at is None:
            exp.ended_at = timezone.now()
            fields.append("ended_at")
        exp.save(update_fields=fields)
    return exp


# --- data -------------------------------------------------------------------------------

def day_logs(athlete, rule: dict, start: dt.date, end: dt.date) -> dict[dt.date, maths.DayLog]:
    from apps.habits.models import HabitLog
    from apps.ingest.models import DailyMetrics, IntradayDay

    logs: dict[dt.date, dict] = {}

    def slot(day):
        return logs.setdefault(day, {"habit": 0.0, "habit_late": 0.0, "bedtime": None,
                                     "steps": None})

    habit = rule.get("habit")
    if habit:
        zone = zone_of(athlete)
        after = maths.clock_minutes(rule["after"]) if rule.get("after") else None
        for day, at, quantity in HabitLog.objects.filter(
                athlete=athlete, kind=habit, local_date__gte=start, local_date__lte=end) \
                .values_list("local_date", "at", "quantity"):
            row = slot(day)
            row["habit"] += quantity or 0
            if after is not None:
                local = at.astimezone(zone)
                if local.hour * 60 + local.minute >= after:
                    row["habit_late"] += quantity or 0
    if "bedtime" in rule:
        for start_local in DailyMetrics.objects.filter(
                athlete=athlete, sleep_start_local__isnull=False,
                metric_date__gte=start, metric_date__lte=end + dt.timedelta(days=1)) \
                .values_list("sleep_start_local", flat=True):
            # Stored as local wall-clock time in a UTC-aware field (see the ingest).
            local = start_local
            day = maths.bed_date(local.replace(tzinfo=None))
            if start <= day <= end:
                slot(day)["bedtime"] = local.replace(tzinfo=None)
    if "min_steps" in rule:
        steps = dict(DailyMetrics.objects.filter(
            athlete=athlete, metric_date__gte=start, metric_date__lte=end,
            steps__isnull=False).values_list("metric_date", "steps"))
        for day, total in IntradayDay.objects.filter(
                athlete=athlete, day__gte=start, day__lte=end, steps_total__isnull=False) \
                .values_list("day", "steps_total"):
            steps[day] = max(total, steps.get(day) or 0)
        for day, total in steps.items():
            slot(day)["steps"] = int(total)
    return {day: maths.DayLog(**row) for day, row in logs.items()}


def metric_series(athlete, start: dt.date, end: dt.date) -> dict[str, dict[dt.date, float]]:
    """Each value keyed by the day it describes: nightly numbers (measured the next
    morning) are moved back one day, so "during" means the nights after rule days."""
    from apps.activities.models import Activity
    from apps.ingest.models import DailyMetrics

    from .models import MoodLog

    out: dict[str, dict] = {k: {} for k in maths.METRICS}
    for row in DailyMetrics.objects.filter(athlete=athlete, metric_date__gte=start,
                                           metric_date__lte=end + dt.timedelta(days=1)):
        night = row.metric_date - dt.timedelta(days=1)
        if row.hrv_overnight_avg is not None:
            out["hrv"][night] = row.hrv_overnight_avg
        if row.resting_hr is not None:
            out["rhr"][night] = row.resting_hr
        if row.sleep_score is not None:
            out["sleep_score"][night] = row.sleep_score
        if row.stress_avg is not None and row.stress_avg >= 0:
            out["stress"][row.metric_date] = row.stress_avg
    for mood in MoodLog.objects.filter(athlete=athlete, date__gte=start, date__lte=end):
        out["mood"][mood.date] = mood.mood
        out["energy"][mood.date] = mood.energy
    fast, slow = athlete.easy_pace_min - 20, athlete.easy_pace_max + 60
    runs: dict[dt.date, list] = {}
    for day, hr, pace in Activity.objects.filter(
            athlete=athlete, sport__icontains="run", local_date__gte=start, local_date__lte=end,
            metrics__avg_run_hr__isnull=False, metrics__run_pace_s_per_km__gte=fast,
            metrics__run_pace_s_per_km__lte=slow, metrics__run_duration_s__gte=600) \
            .values_list("local_date", "metrics__avg_run_hr", "metrics__run_pace_s_per_km"):
        runs.setdefault(day, []).append(hr)
    # One value per run day (the mean), but n counts runs: kept simple — one per day.
    out["easy_hr"] = {day: sum(v) / len(v) for day, v in runs.items()}
    return out


# --- presentation -----------------------------------------------------------------------

def _label(exp: Experiment) -> str:
    return exp.title


def experiment_json(exp: Experiment, today: dt.date, with_result: bool = False) -> dict:
    athlete = exp.athlete
    days = (exp.end - exp.start).days + 1
    day = 0 if today < exp.start else min((today - exp.start).days + 1, days)
    last = exp.end if exp.status != Experiment.Status.STOPPED else min(
        exp.end, (exp.ended_at.astimezone(zone_of(athlete)).date() - dt.timedelta(days=1))
        if exp.ended_at else exp.end)
    last = max(last, exp.start)
    logs = day_logs(athlete, exp.rule, exp.start, last)
    adh = maths.adherence(exp.kind, exp.rule, exp.start, last, today, logs)
    chip = f"{exp.title} · day {day}/{days}"
    if adh["days_counted"]:
        chip += f" · {adh['days_kept']} of {adh['days_counted']} days kept"
    body = {"id": exp.pk, "kind": exp.kind, "title": exp.title, "start": exp.start,
            "end": exp.end, "days": days, "rule": exp.rule, "status": exp.status,
            "decision": exp.decision or None, "created_at": exp.created_at,
            "ended_at": exp.ended_at,
            "progress": {"day": day, "days": days, "pct": round(day / days * 100)},
            "adherence": adh, "chip": chip}
    if with_result:
        body["result"] = result(exp, today, last, adh)
    return body


def result(exp: Experiment, today: dt.date, last: dt.date, adh: dict) -> dict:
    length = (last - exp.start).days + 1
    b_end = exp.start - dt.timedelta(days=1)
    b_start = exp.start - dt.timedelta(days=length)
    d_end = min(last, today - dt.timedelta(days=1)) if today <= last else last
    final = exp.status in (Experiment.Status.COMPLETED, Experiment.Status.STOPPED)
    series = metric_series(exp.athlete, b_start, max(d_end, exp.start))
    metrics = maths.compare(series, (b_start, b_end), (exp.start, d_end)) \
        if d_end >= exp.start else maths.compare({}, (b_start, b_end), (exp.start, exp.start))
    title = "Private habit limit" if exp.rule.get("habit") == "private" else exp.title
    return {"final": final, "baseline": {"start": b_start, "end": b_end},
            "during": {"start": exp.start, "end": d_end},
            "adherence_pct": adh["pct"], "metrics": metrics,
            "summary": maths.summary(exp.title, adh["pct"], metrics, final),
            "caveat": maths.CAVEAT,
            "share": {"title": title,
                      "lines": maths.share_lines(title, length, adh["pct"], metrics)}}


# --- validation --------------------------------------------------------------------------

def _rule_for(athlete, kind: str, raw) -> dict | str:
    template = maths.TEMPLATES[kind]
    rule = dict(template["rule"])
    raw = raw if isinstance(raw, dict) else {}
    if kind == "custom":
        habit = raw.get("habit")
        if habit not in maths.HABITS:
            return f"rule.habit must be one of {', '.join(maths.HABITS)}."
        if habit == "private" and not athlete.private_habit_enabled:
            return "Turn on the private habit first."
        limit = raw.get("max_per_day", 0)
        if not isinstance(limit, (int, float)) or isinstance(limit, bool) or not 0 <= limit <= 50:
            return "rule.max_per_day must be a number 0–50."
        rule = {"habit": habit, "max_per_day": limit}
        if habit == "caffeine" and raw.get("after"):
            try:
                dt.time.fromisoformat(raw["after"])
            except (TypeError, ValueError):
                return "rule.after must be HH:MM."
            rule["after"] = raw["after"][:5]
    elif kind == "bed_by" and "bedtime" in raw:
        try:
            dt.time.fromisoformat(str(raw["bedtime"]))
        except ValueError:
            return "rule.bedtime must be HH:MM."
        rule["bedtime"] = str(raw["bedtime"])[:5]
    elif kind == "steps" and "min_steps" in raw:
        steps = raw["min_steps"]
        if not isinstance(steps, int) or isinstance(steps, bool) or not 1000 <= steps <= 50000:
            return "rule.min_steps must be a whole number 1000–50000."
        rule["min_steps"] = steps
    return rule


def _default_title(kind: str, rule: dict) -> str:
    if kind == "bed_by":
        return f"In bed by {rule['bedtime']}"
    if kind == "steps":
        return f"{rule['min_steps'] // 1000}k steps a day" if rule["min_steps"] % 1000 == 0 \
            else f"{rule['min_steps']:,} steps a day"
    if kind == "custom":
        word = "Private" if rule["habit"] == "private" else rule["habit"].title()
        limit = rule["max_per_day"]
        return f"{word}: none" if limit == 0 else f"{word}: at most {limit:g} a day"
    return maths.TEMPLATES[kind]["title"]


# --- views ------------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def templates(request):
    return Response([{"kind": kind, "title": t["title"], "description": t["description"],
                      "rule": t["rule"], "default_days": t["default_days"],
                      "source": t["source"]} for kind, t in maths.TEMPLATES.items()])


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def experiments(request):
    athlete = request.user.athlete
    today = athlete.local_today
    if request.method == "GET":
        which = request.query_params.get("status") or "all"
        if which not in ("all", *Experiment.Status.values):
            return _bad("status must be active, scheduled, completed, stopped or all.")
        rows = [refresh_status(e, today) for e in Experiment.objects.filter(athlete=athlete)]
        if which != "all":
            rows = [e for e in rows if e.status == which]
        return Response([experiment_json(e, today) for e in rows])

    data = request.data
    kind = data.get("kind")
    if kind not in maths.TEMPLATES:
        return _bad(f"kind must be one of {', '.join(maths.TEMPLATES)}.")
    days = data.get("days", maths.TEMPLATES[kind]["default_days"])
    if not isinstance(days, int) or isinstance(days, bool) or \
            not maths.MIN_DAYS <= days <= maths.MAX_DAYS:
        return _bad(f"days must be {maths.MIN_DAYS}–{maths.MAX_DAYS}.")
    start = today
    if data.get("start"):
        try:
            start = dt.date.fromisoformat(str(data["start"]))
        except ValueError:
            return _bad("start must be a date (YYYY-MM-DD).")
        if not today <= start <= today + dt.timedelta(days=START_AHEAD_DAYS):
            return _bad(f"start must be between today and {START_AHEAD_DAYS} days ahead.")
    rule = _rule_for(athlete, kind, data.get("rule"))
    if isinstance(rule, str):
        return _bad(rule)
    title = data.get("title") or _default_title(kind, rule)
    if not isinstance(title, str) or len(title) > 80:
        return _bad("title must be at most 80 characters.")
    with transaction.atomic():
        for e in Experiment.objects.select_for_update().filter(athlete=athlete,
                                                                status__in=OPEN):
            refresh_status(e, today)
        if Experiment.objects.filter(athlete=athlete, status__in=OPEN).exists():
            return _bad("You already have an experiment running — stop it first.", 409)
        exp = Experiment.objects.create(
            athlete=athlete, kind=kind, title=title.strip(), start=start,
            end=start + dt.timedelta(days=days - 1), rule=rule,
            status=Experiment.Status.SCHEDULED if start > today else Experiment.Status.ACTIVE)
    return Response(experiment_json(exp, today, with_result=True), status=201)


def _get(request, pk) -> Experiment | None:
    return Experiment.objects.filter(athlete=request.user.athlete, pk=pk).first()


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def experiment_detail(request, pk: int):
    exp = _get(request, pk)
    if exp is None:
        return _bad("Not found.", 404)
    today = request.user.athlete.local_today
    if request.method == "DELETE":
        exp.delete()
        return Response(status=204)
    refresh_status(exp, today)
    if request.method == "PATCH":
        data = request.data
        fields = []
        if "title" in data:
            title = data["title"]
            if not isinstance(title, str) or not title.strip() or len(title) > 80:
                return _bad("title must be 1–80 characters.")
            exp.title = title.strip()
            fields.append("title")
        if "decision" in data:
            decision = data["decision"]
            if decision not in ("keep", "stop", None):
                return _bad("decision must be keep, stop or null.")
            exp.decision = decision or ""
            fields.append("decision")
        if fields:
            exp.save(update_fields=fields)
    return Response(experiment_json(exp, today, with_result=True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def experiment_stop(request, pk: int):
    exp = _get(request, pk)
    if exp is None:
        return _bad("Not found.", 404)
    today = request.user.athlete.local_today
    refresh_status(exp, today)
    if exp.status not in OPEN:
        return _bad("This experiment has already ended.", 409)
    if exp.status == Experiment.Status.SCHEDULED:
        exp.end = exp.start
    else:
        exp.end = max(exp.start, today - dt.timedelta(days=1))
    exp.status = Experiment.Status.STOPPED
    exp.ended_at = timezone.now()
    exp.save(update_fields=["end", "status", "ended_at"])
    return Response(experiment_json(exp, today, with_result=True))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def experiment_active(request):
    athlete = request.user.athlete
    today = athlete.local_today
    rows = [refresh_status(e, today) for e in Experiment.objects.filter(
        athlete=athlete, status__in=[*OPEN, Experiment.Status.COMPLETED])]
    active = next((e for e in rows if e.status == Experiment.Status.ACTIVE), None)
    if active is None:
        active = next((e for e in rows if e.status == Experiment.Status.COMPLETED
                       and not e.decision and e.end >= today - dt.timedelta(days=7)), None)
    return Response({"experiment": experiment_json(active, today) if active else None})
