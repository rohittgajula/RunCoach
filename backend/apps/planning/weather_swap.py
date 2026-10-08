"""Weather-smart rescheduling (R14 §3), the Django half. The rules are in
analysis/weather_plan.py (pure).

`check()` looks at the next 3 days of planned runs in the active plan and stores a
WeatherSuggestion for each run on a bad-weather day that has a better day in the same
week. Nothing moves unless the athlete taps Move — or has "Auto-apply weather swaps" on.
`apply()` re-validates against the plan as it is NOW (a move suggested yesterday may no
longer fit), moves the session (and the optional walk it swaps with), keeps `moved_from`,
and re-sends the watch copy through garmin_sync. Today, the past, completed/skipped
sessions and races are never moved.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from analysis import weather_plan as wp

from .models import PlannedWorkout, TrainingPlan, WeatherSuggestion

logger = logging.getLogger(__name__)


class NotApplicable(Exception):
    """The suggestion no longer holds (409)."""


def _plan(athlete):
    return (TrainingPlan.objects.filter(athlete=athlete, status=TrainingPlan.Status.ACTIVE)
            .select_related("race").first())


def _sessions(plan, start: dt.date, end: dt.date) -> list[wp.Session]:
    rows = PlannedWorkout.objects.filter(plan=plan, date__gte=start, date__lte=end)
    return [wp.Session(w.pk, w.date, w.kind, w.status) for w in rows]


def _week(day: dt.date) -> tuple[dt.date, dt.date]:
    monday = day - dt.timedelta(days=day.weekday())
    return monday - dt.timedelta(days=1), monday + dt.timedelta(days=7)   # ±1 day for spacing


def _available(athlete) -> set[int]:
    return {int(d) for d, on in (athlete.available_days or {}).items() if on}


def _last_date(plan) -> dt.date | None:
    return plan.race.date - dt.timedelta(days=1) if plan.race else None


def expire_stale(athlete, today: dt.date) -> int:
    count = 0
    for s in WeatherSuggestion.objects.filter(athlete=athlete,
                                              status=WeatherSuggestion.Status.PENDING) \
            .select_related("workout"):
        w = s.workout
        if (s.from_date <= today or w is None or w.date != s.from_date
                or w.status != PlannedWorkout.Status.PLANNED or w.edited_by == "user"):
            s.status = WeatherSuggestion.Status.EXPIRED
            s.decided_at = timezone.now()
            s.save(update_fields=["status", "decided_at"])
            count += 1
    return count


def check(athlete, hourly: list[dict] | None = None) -> list[WeatherSuggestion]:
    """Create suggestions (idempotent). Returns the ones created now."""
    today = athlete.local_today
    expire_stale(athlete, today)
    plan = _plan(athlete)
    if plan is None:
        return []
    horizon = today + dt.timedelta(days=wp.LOOKAHEAD_DAYS)
    candidates = PlannedWorkout.objects.filter(
        plan=plan, status=PlannedWorkout.Status.PLANNED, date__gt=today, date__lte=horizon,
        kind__in=wp.RUN_KINDS).exclude(edited_by="user")
    if not candidates.exists():
        return []
    if hourly is None:
        from apps.ingest.weather_report import forecast_for

        found = forecast_for(athlete)
        if found is None:
            return []
        hourly = found[0]
    from apps.ingest.weather_report import day_checks

    checks = day_checks(hourly, today)
    first_week = _week(today + dt.timedelta(days=1))[0]
    last_week = _week(horizon)[1]
    sessions = _sessions(plan, first_week, last_week)
    skip = set(WeatherSuggestion.objects.filter(athlete=athlete, workout__isnull=False)
               .values_list("workout_id", "from_date"))
    # R16: sessions the athlete edited are never moved (nor swapped with).
    edited = set(PlannedWorkout.objects.filter(plan=plan, edited_by="user")
                 .values_list("pk", flat=True))
    skip |= {(s.id, s.date) for s in sessions if s.id in edited}
    proposals = [p for p in wp.propose(sessions, checks, today=today,
                                       available=_available(athlete),
                                       last_date=_last_date(plan), skip=skip)
                 if p.swap_with not in edited]
    created = []
    workouts = {w.pk: w for w in PlannedWorkout.objects.filter(
        pk__in=[p.workout_id for p in proposals])}
    for p in proposals:
        w = workouts[p.workout_id]
        from_check, to_check = checks[p.from_date], checks.get(p.to_date)
        try:
            with transaction.atomic():
                s = WeatherSuggestion.objects.create(
                    athlete=athlete, workout=w, swap_workout_id=p.swap_with,
                    workout_title=w.title[:120], workout_kind=w.kind, duration_s=w.duration_s,
                    from_date=p.from_date, to_date=p.to_date, action=p.action,
                    text=wp.text_for(w.kind, p.from_date, p.to_date)[:120],
                    reason=wp.reason_for(from_check, to_check, p.from_date, p.to_date)[:300],
                    reasons=list(p.reasons), from_weather=from_check.brief(hourly),
                    to_weather=to_check.brief(hourly) if to_check else {})
        except IntegrityError:
            continue
        created.append(s)
        if athlete.weather_auto_apply:
            try:
                apply(athlete, s, auto=True)
            except NotApplicable as exc:
                logger.info("weather auto-apply skipped for %s: %s", s.pk, exc)
    return created


def pending(athlete) -> list[WeatherSuggestion]:
    return list(WeatherSuggestion.objects.filter(athlete=athlete,
                                                 status=WeatherSuggestion.Status.PENDING)
                .select_related("workout", "swap_workout"))


def apply(athlete, suggestion: WeatherSuggestion, auto: bool = False) -> WeatherSuggestion:
    from .garmin_sync import resync_on_garmin
    from .reflow import _phase_for

    today = athlete.local_today
    with transaction.atomic():
        s = WeatherSuggestion.objects.select_for_update().get(pk=suggestion.pk)
        if s.status != WeatherSuggestion.Status.PENDING:
            raise NotApplicable("This suggestion was already handled.")
        plan = _plan(athlete)
        ids = [i for i in (s.workout_id, s.swap_workout_id) if i]
        locked = {w.pk: w for w in PlannedWorkout.objects.select_for_update()
                  .filter(athlete=athlete, pk__in=ids)}
        w = locked.get(s.workout_id)
        if (plan is None or w is None or w.plan_id != plan.pk or w.date != s.from_date
                or w.status != PlannedWorkout.Status.PLANNED or w.completed_activity_id
                or w.date <= today or s.to_date <= today or w.kind not in wp.RUN_KINDS
                or w.edited_by == "user"):
            raise NotApplicable("The session has changed since — nothing was moved.")
        walk = locked.get(s.swap_workout_id) if s.swap_workout_id else None
        if s.swap_workout_id and (walk is None or walk.date != s.to_date
                                  or walk.status != PlannedWorkout.Status.PLANNED
                                  or walk.edited_by == "user"):
            raise NotApplicable("The day it would swap with has changed — nothing was moved.")
        start, end = _week(s.from_date)
        sessions = _sessions(plan, start, end)
        session = wp.Session(w.pk, w.date, w.kind, w.status)
        ok, walk_id = wp.target_ok(session, s.to_date, sessions, today=today,
                                   available=_available(athlete), last_date=_last_date(plan))
        if not ok or walk_id != (walk.pk if walk else None):
            raise NotApplicable("That day no longer fits the plan — nothing was moved.")
        phases = list(plan.phases.all())
        for row, new_date in ((w, s.to_date), (walk, s.from_date)):
            if row is None:
                continue
            row.moved_from = row.moved_from or row.date
            row.date = new_date
            row.phase = _phase_for(phases, new_date) or row.phase
            row.save(update_fields=["date", "moved_from", "phase"])
        s.status = WeatherSuggestion.Status.APPLIED
        s.auto_applied = auto
        s.decided_at = timezone.now()
        s.save(update_fields=["status", "auto_applied", "decided_at"])
        resync_on_garmin(athlete, ids)
    return s


def dismiss(athlete, suggestion: WeatherSuggestion) -> WeatherSuggestion:
    if suggestion.status != WeatherSuggestion.Status.PENDING:
        raise NotApplicable("This suggestion was already handled.")
    suggestion.status = WeatherSuggestion.Status.DISMISSED
    suggestion.decided_at = timezone.now()
    suggestion.save(update_fields=["status", "decided_at"])
    return suggestion


def suggestion_json(s: WeatherSuggestion) -> dict:
    swap = s.swap_workout
    return {"id": s.pk, "workout_id": s.workout_id, "workout_title": s.workout_title,
            "workout_kind": s.workout_kind, "duration_s": s.duration_s,
            "from_date": s.from_date, "to_date": s.to_date, "action": s.action,
            "swap_with": ({"workout_id": swap.pk, "title": swap.title, "kind": swap.kind}
                          if swap is not None else None),
            "text": s.text, "reason": s.reason, "reasons": s.reasons,
            "from_weather": s.from_weather, "to_weather": s.to_weather,
            "status": s.status, "auto_applied": s.auto_applied,
            "created_at": s.created_at, "decided_at": s.decided_at}


def runs_vs_weather(athlete, checks: dict, pending_rows: list) -> list[dict]:
    plan = _plan(athlete)
    if plan is None:
        return []
    today = athlete.local_today
    by_workout = {s.workout_id: s.pk for s in pending_rows}
    out = []
    for w in PlannedWorkout.objects.filter(plan=plan, date__gte=today,
                                           date__lte=today + dt.timedelta(days=6),
                                           kind__in=wp.RUN_KINDS | {"RACE"}) \
            .exclude(status=PlannedWorkout.Status.SKIPPED).order_by("date", "id"):
        check_ = checks.get(w.date)
        best = None
        if check_ is not None and check_.best is not None and check_.verdict != "bad":
            start = dt.datetime.fromisoformat(check_.best["time"])
            feels = check_.best.get("feels_like")
            best = {"start": start.isoformat(timespec="minutes"),
                    "end": (start + dt.timedelta(hours=1)).isoformat(timespec="minutes"),
                    "reason": (f"Feels like {feels:.0f}°C" if feels is not None
                               else "Best slot")}
        out.append({"date": w.date, "workout_id": w.pk, "title": w.title, "kind": w.kind,
                    "duration_s": w.duration_s,
                    "verdict": check_.verdict if check_ else None,
                    "reasons": wp.day_reasons(check_) if check_ else [],
                    "best_window": best, "suggestion_id": by_workout.get(w.pk)})
    return out
