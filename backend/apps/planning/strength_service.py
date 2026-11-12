"""R13 §4: strength sessions in the calendar (Django half; rules in planning/strength.py).

`place_for(athlete)` (re)places the future strength sessions of the active plan for the
next 8 weeks: kept where they still fit, moved/created where needed, removed when the
athlete turns them off. Past, completed and skipped sessions are never touched. Called
when `strength_per_week` changes, when a plan is accepted or rebuilt, after the training
days change, and by a nightly top-up (so the 8-week horizon keeps moving).
"""

from __future__ import annotations

import datetime as dt
import logging

from django.db import transaction

from planning import strength as rules
from planning.garmin_strength import build_payload, payload_hash

from .models import INACTIVE_STATUSES, PlannedWorkout, StrengthSession, TrainingPlan

logger = logging.getLogger(__name__)

HORIZON_DAYS = 56
STRENGTH_SPORTS = ("strength", "training")   # Garmin: strength_training / training


def can_send(athlete) -> bool:
    """garminconnect 0.3.10 has upload_strength_workout (see planning/garmin_strength.py)."""
    return bool(athlete.garmin_connected)


def garmin_status(session: StrengthSession) -> str:
    if not session.garmin_workout_id:
        return "none"
    current = payload_hash(build_payload(_source(session)), session.date.isoformat())
    return "synced" if current == session.garmin_payload_hash else "changed"


def _source(session: StrengthSession) -> dict:
    return {"title": session.title, "duration_s": session.duration_s,
            "exercises": session.exercises or []}


def strength_json(session: StrengthSession, can_send_to_watch: bool | None = None) -> dict:
    if can_send_to_watch is None:
        can_send_to_watch = can_send(session.athlete)
    return {"id": session.pk, "date": session.date, "title": session.title,
            "duration_s": session.duration_s, "level": session.level,
            "exercises": session.exercises or [], "status": session.status,
            "completed_activity_id": session.completed_activity_id,
            "auto_completed": session.auto_completed, "after_run": session.after_run,
            "garmin_status": garmin_status(session),
            "garmin_workout_id": session.garmin_workout_id,
            "can_send_to_watch": can_send_to_watch}


def _level_start(plan: TrainingPlan, athlete) -> dt.date:
    first_phase = plan.phases.order_by("start").values_list("start", flat=True).first()
    first_session = (StrengthSession.objects.filter(athlete=athlete, plan=plan)
                     .order_by("date").values_list("date", flat=True).first())
    starts = [d for d in (first_phase, first_session) if d]
    return min(starts) if starts else athlete.local_today


def place_for(athlete) -> dict:
    """Returns {created, removed}."""
    from .garmin_sync import _queue

    today = athlete.local_today
    first, last = today + dt.timedelta(days=1), today + dt.timedelta(days=HORIZON_DAYS)
    plan = TrainingPlan.objects.filter(athlete=athlete, status=TrainingPlan.Status.ACTIVE) \
        .select_related("race").first()
    with transaction.atomic():
        future = list(StrengthSession.objects.select_for_update().filter(
            athlete=athlete, date__gte=first, status=StrengthSession.Status.PLANNED))
        wanted: list[tuple[dt.date, bool]] = []
        if plan is not None and athlete.strength_per_week:
            phases_end = plan.phases.order_by("-end").values_list("end", flat=True).first()
            if phases_end:
                last = min(last, phases_end)
            rows = (PlannedWorkout.objects.filter(athlete=athlete, plan=plan, date__gte=first,
                                                  date__lte=last + dt.timedelta(days=1))
                    .exclude(status__in=INACTIVE_STATUSES).values_list("date", "kind"))
            kinds: dict[dt.date, list[str]] = {}
            for day, kind in rows:
                kinds.setdefault(day, []).append(kind)
            # The week may have started before tomorrow: count what is already placed.
            days = [rules.Day(d, tuple(k)) for d, k in kinds.items()]
            race_date = plan.race.date if plan.race else None
            gym_days = {
                int(key) for key, on in (athlete.gym_days or {}).items() if on
            }
            wanted = rules.place(days, athlete.strength_per_week, first, last, race_date,
                                 gym_days=gym_days)
            wanted = _minus_existing_this_week(athlete, wanted, first)
        wanted_dates = {d: after for d, after in wanted}
        removed = [s for s in future if s.date not in wanted_dates]
        refs = [[s.garmin_workout_id, s.garmin_schedule_id] for s in removed if s.garmin_workout_id]
        StrengthSession.objects.filter(pk__in=[s.pk for s in removed]).delete()
        kept = {s.date: s for s in future if s.date in wanted_dates}
        start = _level_start(plan, athlete) if plan else today
        created = 0
        for day, after in sorted(wanted_dates.items()):
            level = rules.level_for(start, day)
            # Per-pattern rungs override the programme clock: somebody doing
            # bodyweight squats comfortably may still be on wall push-ups, and
            # one number for the whole session cannot say both.
            fields = {"title": rules.title_for(level), "level": level,
                      "exercises": rules.exercises(
                          level, athlete.strength_levels or {},
                          equipment=athlete.gym_equipment,
                      ),
                      "after_run": after,
                      "duration_s": rules.DURATION_S, "plan": plan}
            session = kept.get(day)
            if session is None:
                StrengthSession.objects.create(athlete=athlete, date=day, **fields)
                created += 1
            else:
                for key, value in fields.items():
                    setattr(session, key, value)
                session.save()
        if refs:
            from .tasks import garmin_forget_task

            _queue(garmin_forget_task, athlete.pk, refs)
    return {"created": created, "removed": len(removed)}


def _minus_existing_this_week(athlete, wanted, first):
    """Sessions already done / kept earlier in the current week count toward its quota."""
    if not wanted:
        return wanted
    week_start = first - dt.timedelta(days=first.weekday())
    already = StrengthSession.objects.filter(
        athlete=athlete, date__gte=week_start, date__lt=first).exclude(
        status=StrengthSession.Status.SKIPPED).count()
    if not already:
        return wanted
    this_week = [w for w in wanted if w[0] < week_start + dt.timedelta(days=7)]
    rest = [w for w in wanted if w[0] >= week_start + dt.timedelta(days=7)]
    keep = max(0, athlete.strength_per_week - already)
    return this_week[:keep] + rest


def complete_from_activity(activity) -> StrengthSession | None:
    """A Garmin strength activity completes that day's planned strength session."""
    sport = (activity.sport or "").lower()
    if not any(word in sport for word in STRENGTH_SPORTS) or "run" in sport:
        return None
    with transaction.atomic():
        session = (StrengthSession.objects.select_for_update()
                   .filter(athlete_id=activity.athlete_id, date=activity.local_date,
                           status=StrengthSession.Status.PLANNED).order_by("id").first())
        if session is None:
            return None
        session.status = StrengthSession.Status.COMPLETED
        session.completed_activity = activity
        session.auto_completed = True
        session.save(update_fields=["status", "completed_activity", "auto_completed"])
    return session


def sessions_between(athlete, start: dt.date, end: dt.date) -> list[StrengthSession]:
    return list(StrengthSession.objects.filter(athlete=athlete, date__gte=start, date__lte=end)
                .exclude(plan__status__in=[TrainingPlan.Status.PROPOSED,
                                           TrainingPlan.Status.DECLINED]))
