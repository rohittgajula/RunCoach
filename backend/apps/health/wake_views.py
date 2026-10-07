"""R12 §B: the wake planner, "My alarm" and the read-only watch-alarm check."""

from __future__ import annotations

import datetime as dt

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import wake as maths
from analysis.sleep import median, minutes_of_day
from apps.activities.models import Activity
from apps.ingest.models import DailyMetrics, GarminProfile

from .common import BadRequest, zone_of

PLAN_DAYS_AHEAD = 7
NOTE = ("A web app can't set your phone's alarm or your watch's alarms. Use “Set alarm on "
        "phone” (Android), set it in the Clock app (iPhone), or turn on the push notification "
        "— a notification, not a real alarm.")


def alarm_for(athlete):
    from apps.reminders.models import Alarm

    row, _ = Alarm.objects.get_or_create(athlete=athlete)
    return row


def _t(value: dt.time | None) -> str | None:
    return value.strftime("%H:%M") if value else None


def alarm_json(row) -> dict:
    from apps.reminders.push import available

    return {"time": _t(row.time), "days": list(row.days or []), "enabled": row.enabled,
            "push": row.push, "run_time": _t(row.run_time),
            "bedtime_reminder": row.bedtime_reminder, "bedtime_lead_min": row.bedtime_lead_min,
            "push_available": available(), "note": NOTE}


def watch_json(athlete) -> dict:
    profile = GarminProfile.objects.filter(athlete=athlete).first()
    alarms = list((profile.watch_alarms or []) if profile else [])
    available = bool(profile and profile.watch_alarms_available)
    return {"available": available,
            "checked_on": profile.watch_alarms_checked_on if profile else None,
            "alarms": alarms if available else [],
            "summary": maths.summary(alarms) if available else None}


def _planned(athlete, day: dt.date):
    from apps.planning.models import PlannedWorkout, TrainingPlan

    return (PlannedWorkout.objects.filter(
        athlete=athlete, date=day, plan__status=TrainingPlan.Status.ACTIVE)
        .exclude(kind="REST").order_by("id").first())


def _run_time(athlete, row) -> tuple[int | None, str | None]:
    if row.run_time:
        return maths.minutes(row.run_time), "setting"
    zone = zone_of(athlete)
    starts = [a.astimezone(zone) for a in Activity.objects.filter(
        athlete=athlete, sport__icontains="run").order_by("-started_at")
        .values_list("started_at", flat=True)[:maths.RECENT_RUNS]]
    minute = maths.typical_run_time([s.hour * 60 + s.minute for s in reversed(starts)])
    return (minute, "history") if minute is not None else (None, None)


def wake_plan(athlete, day: dt.date) -> dict:
    row = alarm_for(athlete)
    today = athlete.local_today
    recent = list(DailyMetrics.objects.filter(
        athlete=athlete, metric_date__gt=today - dt.timedelta(days=7), metric_date__lte=today))
    habit = median([minutes_of_day(r.sleep_end_local) for r in recent if r.sleep_end_local])
    need = median([r.sleep_need_seconds for r in recent if r.sleep_need_seconds])
    workout = _planned(athlete, day)
    run_time, run_source = _run_time(athlete, row)
    planned = maths.plan(run_planned=workout is not None, run_time=run_time,
                         habit_wake=round(habit) if habit is not None else None,
                         need_s=round(need) if need else None, lead_min=row.bedtime_lead_min)
    weekday = day.weekday()
    my_alarm = (maths.minutes(row.time) if row.enabled and row.time and weekday in (row.days or [])
                else None)
    watch = watch_json(athlete)
    watch_times = maths.alarms_on(watch["alarms"], weekday) if watch["available"] else []
    return {
        "date": day, "weekday": weekday,
        "run": {"planned": workout is not None,
                "workout_id": workout.pk if workout else None,
                "title": workout.title if workout else None,
                "kind": workout.kind if workout else None,
                "run_time": maths.clock(run_time), "run_time_source": run_source},
        "need_s": planned["need_s"], "need_source": planned["need_source"],
        "wake_time": maths.clock(planned["wake"]), "wake_source": planned["wake_source"],
        "bedtime": maths.clock(planned["bedtime"]),
        "bedtime_reminder_at": maths.clock(planned["reminder"]),
        "my_alarm": alarm_json(row), "my_alarm_on_date": maths.clock(my_alarm),
        "watch": watch,
        "flags": maths.flags(run_planned=workout is not None, run_time=run_time,
                             watch_available=watch["available"], watch_times=watch_times,
                             my_alarm=my_alarm),
        "android_intent": maths.android_intent(planned["wake"]),
        "sentence": maths.sentence(planned["wake_source"], planned["wake"], planned["bedtime"],
                                   run_time),
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def wake_plan_view(request):
    athlete = request.user.athlete
    today = athlete.local_today
    raw = request.query_params.get("date")
    if raw:
        try:
            day = dt.date.fromisoformat(raw)
        except ValueError as exc:
            raise BadRequest("date must be a date (YYYY-MM-DD).") from exc
        if not today <= day <= today + dt.timedelta(days=PLAN_DAYS_AHEAD):
            raise BadRequest("date must be between today and 7 days ahead.")
    else:
        day = today + dt.timedelta(days=1)
    return Response(wake_plan(athlete, day))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def watch_alarms_view(request):
    return Response(watch_json(request.user.athlete))


ALARM_KEYS = {"time", "days", "enabled", "push", "run_time", "bedtime_reminder",
              "bedtime_lead_min"}


def _time_or_none(key, value):
    if value is None:
        return None
    try:
        return dt.datetime.strptime(str(value), "%H:%M").time()
    except ValueError as exc:
        raise BadRequest(f"{key} must be HH:MM (24 h) or null.") from exc


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def alarm_view(request):
    athlete = request.user.athlete
    row = alarm_for(athlete)
    if request.method == "PATCH":
        data = request.data
        if not isinstance(data, dict):
            raise BadRequest("Send an object.")
        unknown = set(data) - ALARM_KEYS
        if unknown:
            raise BadRequest(f"Unknown field: {', '.join(sorted(unknown))}.")
        for key in ("time", "run_time"):
            if key in data:
                setattr(row, key, _time_or_none(key, data[key]))
        for key in ("enabled", "push", "bedtime_reminder"):
            if key in data:
                if not isinstance(data[key], bool):
                    raise BadRequest(f"{key} must be true or false.")
                setattr(row, key, data[key])
        if "days" in data:
            days = data["days"]
            if not isinstance(days, list) or any(
                    isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in days) \
                    or len(set(days)) != len(days):
                raise BadRequest("days must be a list of distinct weekdays 0 (Mon) to 6 (Sun).")
            row.days = sorted(days)
        if "bedtime_lead_min" in data:
            lead = data["bedtime_lead_min"]
            if isinstance(lead, bool) or not isinstance(lead, int) or not 15 <= lead <= 120:
                raise BadRequest("bedtime_lead_min must be a whole number from 15 to 120.")
            row.bedtime_lead_min = lead
        if row.enabled and (row.time is None or not row.days):
            raise BadRequest("An enabled alarm needs a time and at least one day.")
        row.save()
    return Response(alarm_json(row))
