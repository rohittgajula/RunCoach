"""R17 §10: illness mode — pause the plan, rest messaging, the return-to-run block.

planning/illness.py holds the rules (pure). This module pauses / un-pauses workouts,
creates the return sessions and serves /illness/.

Safety only ever makes training easier: paused workouts keep their content (edited ones
too), RACE workouts are never paused, and return sessions are shorter and lower-capped
than the plan's own sessions on the same dates.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from planning import illness as rules

from .models import Illness

logger = logging.getLogger(__name__)

MAX_BACKDATE_DAYS = 14
RUN_KINDS_EXCLUDED = ("REST", "WALK", "RACE")


class IllnessError(Exception):
    def __init__(self, detail: str, status: int = 400):
        super().__init__(detail)
        self.detail, self.status = detail, status


# --- shared helpers ------------------------------------------------------------------

def active(athlete) -> Illness | None:
    return Illness.objects.filter(athlete=athlete, status=Illness.Status.ACTIVE).first()


def periods(athlete) -> list[tuple[dt.date, dt.date, Illness]]:
    today = athlete.local_today
    out = []
    for ill in Illness.objects.filter(athlete=athlete).order_by("start_date"):
        end = ill.recovered_on or today
        if end >= ill.start_date:
            out.append((ill.start_date, end, ill))
    return out


def illness_days(athlete) -> set[dt.date]:
    return rules.neutral_days([(s, e) for s, e, _ in periods(athlete)])


def illness_on(athlete, day: dt.date) -> Illness | None:
    for start, end, ill in periods(athlete):
        if start <= day <= end:
            return ill
    return None


def brief(ill: Illness, today: dt.date) -> dict:
    tips, _ = rules.advice(ill.type, ill.symptoms, ill.fever)
    return {"id": ill.pk, "type": ill.type, "type_label": rules.label_for(ill.type),
            "start_date": ill.start_date, "days_so_far": _days_so_far(ill, today),
            "advice": tips}


def _days_so_far(ill: Illness, today: dt.date) -> int:
    end = ill.recovered_on or today
    return max(1, (end - ill.start_date).days + 1)


def illness_json(ill: Illness, today: dt.date, block: dict | None = None,
                 warning: dict | None = None) -> dict:
    tips, doctor = rules.advice(ill.type, ill.symptoms, ill.fever)
    return {
        "id": ill.pk, "type": ill.type, "type_label": rules.label_for(ill.type),
        "symptoms": ill.symptoms, "fever": ill.fever, "start_date": ill.start_date,
        "expected_days": ill.expected_days, "note": ill.note, "status": ill.status,
        "recovered_on": ill.recovered_on,
        "days_off": (ill.recovered_on - ill.start_date).days if ill.recovered_on else None,
        "days_so_far": _days_so_far(ill, today), "paused_workouts": ill.paused_count,
        "advice": tips, "see_doctor": doctor,
        "return_block": block if block is not None else ill.return_block,
        "race_warning": warning if block is not None else ill.race_warning,
        "created_at": ill.created_at, "updated_at": ill.updated_at,
    }


# --- validation -----------------------------------------------------------------------

def _clean(data: dict, athlete, partial: bool) -> dict:
    out: dict = {}
    if "type" in data or not partial:
        kind = data.get("type")
        if kind not in rules.TYPES:
            raise IllnessError("type must be one of: " + ", ".join(rules.TYPES) + ".")
        out["type"] = kind
    if "symptoms" in data and data["symptoms"] is not None:
        if data["symptoms"] not in rules.SYMPTOMS:
            raise IllnessError("symptoms must be above_neck or below_neck.")
        out["symptoms"] = data["symptoms"]
    if "fever" in data and data["fever"] is not None:
        if not isinstance(data["fever"], bool):
            raise IllnessError("fever must be true or false.")
        out["fever"] = data["fever"]
    if "expected_days" in data:
        value = data["expected_days"]
        if value is not None:
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise IllnessError("expected_days must be a whole number (1–60).") from None
            if not 1 <= value <= 60:
                raise IllnessError("expected_days must be between 1 and 60.")
        out["expected_days"] = value
    if "note" in data:
        note = str(data.get("note") or "").strip()
        if len(note) > 200:
            raise IllnessError("note must be at most 200 characters.")
        out["note"] = note
    if not partial:
        today = athlete.local_today
        raw = data.get("start_date")
        try:
            start = dt.date.fromisoformat(str(raw)) if raw else today
        except ValueError:
            raise IllnessError("start_date must be YYYY-MM-DD.") from None
        if start > today or start < today - dt.timedelta(days=MAX_BACKDATE_DAYS):
            raise IllnessError("start_date must be within the last 14 days.")
        out["start_date"] = start
        out.setdefault("symptoms", "below_neck" if out["type"] == "flu" else "above_neck")
        out.setdefault("fever", out["type"] == "flu")
    return out


# --- pause / resume -----------------------------------------------------------------

def _plan_workouts(athlete):
    from apps.planning.models import PlannedWorkout, TrainingPlan

    return PlannedWorkout.objects.filter(athlete=athlete, plan__status=TrainingPlan.Status.ACTIVE)


def pause(athlete, ill: Illness) -> int:
    from apps.planning.garmin_sync import _queue, remove_from_garmin
    from apps.planning.models import PlannedWorkout, StrengthSession

    first = max(athlete.local_today, ill.start_date)
    workouts = list(_plan_workouts(athlete).filter(
        status=PlannedWorkout.Status.PLANNED, date__gte=first).exclude(kind="RACE"))
    ids = [w.pk for w in workouts]
    PlannedWorkout.objects.filter(pk__in=ids).update(status=PlannedWorkout.Status.PAUSED,
                                                     paused_by_illness=ill.pk)
    remove_from_garmin(athlete, ids)
    sessions = list(StrengthSession.objects.filter(
        athlete=athlete, status=StrengthSession.Status.PLANNED, date__gte=first))
    StrengthSession.objects.filter(pk__in=[s.pk for s in sessions]).update(
        status=StrengthSession.Status.PAUSED, paused_by_illness=ill.pk)
    on_watch = [s.pk for s in sessions if s.garmin_workout_id]
    if on_watch:
        from apps.planning.tasks import garmin_strength_push_task

        _queue(garmin_strength_push_task, athlete.pk, on_watch, "delete")
    return len(ids)


def _unpause(athlete, ill: Illness, from_date: dt.date) -> int:
    from apps.planning.models import PlannedWorkout, StrengthSession

    n = PlannedWorkout.objects.filter(
        athlete=athlete, paused_by_illness=ill.pk, status=PlannedWorkout.Status.PAUSED,
        date__gte=from_date).update(status=PlannedWorkout.Status.PLANNED,
                                    paused_by_illness=None)
    StrengthSession.objects.filter(
        athlete=athlete, paused_by_illness=ill.pk, status=StrengthSession.Status.PAUSED,
        date__gte=from_date).update(status=StrengthSession.Status.PLANNED,
                                    paused_by_illness=None)
    return n


def start(athlete, data: dict) -> Illness:
    fields = _clean(data, athlete, partial=False)
    with transaction.atomic():
        if active(athlete) is not None:
            raise IllnessError("You're already marked as unwell — tap \"I'm better\" first.",
                               409)
        ill = Illness.objects.create(athlete=athlete, **fields)
        ill.paused_count = pause(athlete, ill)
        ill.save(update_fields=["paused_count", "updated_at"])
    return ill


def update(ill: Illness, data: dict) -> Illness:
    if ill.status != Illness.Status.ACTIVE:
        raise IllnessError("Only an active illness can be changed.", 409)
    fields = _clean(data, ill.athlete, partial=True)
    for key, value in fields.items():
        setattr(ill, key, value)
    ill.save()
    return ill


def cancel(ill: Illness) -> None:
    if ill.status != Illness.Status.ACTIVE:
        raise IllnessError("Only an active illness can be removed.", 409)
    athlete = ill.athlete
    with transaction.atomic():
        _unpause(athlete, ill, athlete.local_today)
        ill.delete()


# --- recovery -------------------------------------------------------------------------

def _hr_cap(steps: list) -> int | None:
    tops = [s.get("hr_max") for s in steps or []
            if s.get("intensity") != "walk" and s.get("hr_max")]
    return min(tops) if tops else None


def _plan_block(athlete, ill: Illness, recovered_on: dt.date):
    from apps.activities.models import Activity
    from apps.planning.models import PlannedWorkout, TrainingPlan
    from apps.planning.plan_store import bands_for

    plan = TrainingPlan.objects.filter(athlete=athlete, status=TrainingPlan.Status.ACTIVE).first()
    paused = list(PlannedWorkout.objects.filter(
        athlete=athlete, paused_by_illness=ill.pk, status=PlannedWorkout.Status.PAUSED)
        .exclude(kind__in=RUN_KINDS_EXCLUDED).order_by("date", "id"))
    recent = list(Activity.objects.filter(
        athlete=athlete, sport__icontains="run",
        local_date__gte=ill.start_date - dt.timedelta(days=28),
        local_date__lt=ill.start_date).values_list("total_timer_s", flat=True))
    usual = rules.usual_duration(recent, [w.duration_s for w in paused])
    bands = bands_for(athlete)
    plan_days = None
    free = None
    if plan is not None:
        by_date: dict[dt.date, rules.PlanDay] = {}
        for w in paused:
            if w.date <= recovered_on or w.date in by_date:
                continue
            by_date[w.date] = rules.PlanDay(date=w.date, duration_s=w.duration_s,
                                            workout_id=w.pk, hr_cap=_hr_cap(w.steps))
        plan_days = list(by_date.values())
    else:
        free = [recovered_on + dt.timedelta(days=i) for i in range(1, 22)
                if athlete.is_available((recovered_on + dt.timedelta(days=i)).weekday())]
    hr_easy = bands.hr_easy or (None, None)
    block = rules.return_block(
        kind=ill.type, symptoms=ill.symptoms, fever=ill.fever, start_date=ill.start_date,
        recovered_on=recovered_on, usual_s=usual, plan_days=plan_days, free_dates=free,
        easy_low=hr_easy[0], easy_top=hr_easy[1] or athlete.hr_ceiling,
        easy_pace=bands.easy_pace)
    return plan, block, {w.pk: w for w in paused}


def _races(athlete, plan) -> list[tuple[int, str, dt.date]]:
    from apps.planning.models import Race

    qs = Race.objects.filter(athlete=athlete, date__gte=athlete.local_today)
    return [(r.pk, r.name, r.date) for r in qs]


def recover(ill: Illness, day: dt.date | None, dry_run: bool = False) -> dict:
    athlete = ill.athlete
    today = athlete.local_today
    if ill.status != Illness.Status.ACTIVE:
        raise IllnessError("You're not marked as unwell.", 409)
    day = day or today
    if day < ill.start_date or day > today:
        raise IllnessError("date must be between the start date and today.")
    plan, block, paused = _plan_block(athlete, ill, day)
    warning = rules.race_warning(_races(athlete, plan), block)
    if dry_run:
        preview = Illness(pk=ill.pk, athlete=athlete, type=ill.type, symptoms=ill.symptoms,
                          fever=ill.fever, start_date=ill.start_date,
                          expected_days=ill.expected_days, note=ill.note,
                          status=Illness.Status.RECOVERED, recovered_on=day,
                          paused_count=ill.paused_count, created_at=ill.created_at,
                          updated_at=ill.updated_at)
        return illness_json(preview, today, rules.block_dict(block), warning)

    from apps.planning.models import PlannedWorkout

    with transaction.atomic():
        ids: dict[dt.date, int] = {}
        if plan is not None:
            for s in block.sessions:
                original = paused.get(s.replaces)
                w = PlannedWorkout.objects.create(
                    athlete=athlete, plan=plan, phase=original.phase if original else None,
                    date=s.date, title=s.title[:120], kind=s.kind, duration_s=s.duration_s,
                    load=s.load, steps=s.steps, description=s.description,
                    purpose="Return to running after being unwell.", target_zone="Z1",
                    fueling={}, status=PlannedWorkout.Status.PLANNED,
                    illness_return=ill.pk)
                ids[s.date] = w.pk
        _unpause(athlete, ill, block.resumes_on)
        statuses = dict(PlannedWorkout.objects.filter(pk__in=list(ids.values()))
                        .values_list("pk", "status"))
        ill.status = Illness.Status.RECOVERED
        ill.recovered_on = day
        ill.return_block = _jsonable(rules.block_dict(block, statuses, ids))
        ill.race_warning = _jsonable(warning)
        ill.save()
    return illness_json(ill, today)


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


# --- views ------------------------------------------------------------------------------

def _error(exc: IllnessError) -> Response:
    return Response({"detail": exc.detail}, status=exc.status)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def illness_view(request):
    athlete = request.user.athlete
    today = athlete.local_today
    if request.method == "POST":
        try:
            ill = start(athlete, request.data if isinstance(request.data, dict) else {})
        except IllnessError as exc:
            return _error(exc)
        return Response(illness_json(ill, today), status=201)
    current = active(athlete)
    history = Illness.objects.filter(athlete=athlete, status=Illness.Status.RECOVERED)[:20]
    return Response({"active": illness_json(current, today) if current else None,
                     "history": [illness_json(i, today) for i in history]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def illness_history(request):
    athlete = request.user.athlete
    return Response([illness_json(i, athlete.local_today)
                     for i in Illness.objects.filter(athlete=athlete)])


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def illness_detail(request, pk: int):
    athlete = request.user.athlete
    ill = Illness.objects.filter(athlete=athlete, pk=pk).first()
    if ill is None:
        return Response({"detail": "Not found."}, status=404)
    try:
        if request.method == "DELETE":
            cancel(ill)
            return Response(status=204)
        ill = update(ill, request.data if isinstance(request.data, dict) else {})
    except IllnessError as exc:
        return _error(exc)
    return Response(illness_json(ill, athlete.local_today))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def illness_recover(request, pk: int):
    athlete = request.user.athlete
    ill = Illness.objects.filter(athlete=athlete, pk=pk).first()
    if ill is None:
        return Response({"detail": "Not found."}, status=404)
    data = request.data if isinstance(request.data, dict) else {}
    raw = data.get("date")
    try:
        day = dt.date.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return Response({"detail": "date must be YYYY-MM-DD."}, status=400)
    try:
        return Response(recover(ill, day, dry_run=bool(data.get("dry_run"))))
    except IllnessError as exc:
        return _error(exc)
