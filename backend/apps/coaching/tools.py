"""The tools the chat model can call. Every one is Python, scoped to one athlete.

The model proposes; these functions decide. `propose_plan` runs the deterministic
generator — the model may only name and describe phases. `move_workout`, `skip_workout`
and `clear_day` can only make the week easier or shift it, never add load.
`edit_workout` / `edit_week` (R16) call the same edit service as the app: same
validation, warnings and watch re-send; more than +20 % running on a session comes back
`needs_confirmation` until the athlete has said yes (`confirmed: true`).
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction

from apps.activities.models import Activity
from apps.athletes.models import Athlete
from apps.journal.models import JournalEntry
from apps.planning.garmin_sync import remove_from_garmin, resync_on_garmin
from apps.planning.models import PlannedWorkout, TrainingPlan
from apps.planning.plan_store import PlanError, propose_plan
from apps.planning.presenters import workout_json

from .models import MemoryFact


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}


DATE = {"type": "string", "description": "YYYY-MM-DD"}
EDIT_STEP = {"type": "object", "properties": {
    "kind": {"type": "string",
             "enum": ["warmup", "run", "walk", "recovery", "cooldown", "strides", "other"]},
    "duration_s": {"type": "integer", "minimum": 10, "maximum": 5400},
    "intensity": {"type": "string", "enum": ["walk", "easy", "moderate", "hard"]},
    "target": {"type": "string", "enum": ["hr", "pace", "none", "auto"]},
    "hr_low": {"type": "integer"}, "hr_high": {"type": "integer"},
    "pace_low": {"type": "integer", "description": "s/km, the fast end"},
    "pace_high": {"type": "integer", "description": "s/km, the slow end"},
    "note": {"type": "string"},
    "repeat": {"type": "integer", "minimum": 2, "maximum": 30,
               "description": "Only on a repeat block: how many times `steps` repeat"},
    "steps": {"type": "array", "description": "Only on a repeat block",
              "items": {"type": "object", "properties": {
                  "kind": {"type": "string"}, "duration_s": {"type": "integer"},
                  "intensity": {"type": "string"}, "target": {"type": "string"},
                  "hr_low": {"type": "integer"}, "hr_high": {"type": "integer"},
                  "pace_low": {"type": "integer"}, "pace_high": {"type": "integer"},
                  "note": {"type": "string"}}}},
}}


def upcoming_races(athlete: Athlete) -> list[dict]:
    """Saved races from today on — what the coach must plan against before inventing one."""
    from apps.planning.models import Race

    return [
        {"id": r.pk, "name": r.name, "date": r.date, "distance_km": r.distance_km,
         "is_target": r.is_target}
        for r in Race.objects.filter(athlete=athlete, date__gte=athlete.local_today).order_by("date")
    ]
TOOLS = [
    _fn("get_training_summary", "Weekly minutes, load, run km and longest continuous run.",
        {"weeks": {"type": "integer", "minimum": 1, "maximum": 26}}, ["weeks"]),
    _fn("get_activity", "One recorded activity: segmented run/walk metrics, km splits, HR, journal.",
        {"id": {"type": "integer"}}, ["id"]),
    _fn("get_workout", "One planned workout with its steps.", {"id": {"type": "integer"}}, ["id"]),
    _fn("get_workouts", "Planned workouts between two dates (inclusive).",
        {"start": DATE, "end": DATE}, ["start", "end"]),
    _fn("propose_plan",
        "Build a training plan with the deterministic generator and save it as a PROPOSAL "
        "the athlete must accept. Plan for a SAVED race by passing its race_id (see "
        "`races` in the context) — that is the normal case. Only pass race_name/race_date/"
        "distance_km for a race the athlete explicitly named in this chat that is not "
        "saved, and then set confirmed_new_race=true. Never guess a race date. You may only "
        "supply phase names/descriptions; dates and volumes are the generator's. If you pass "
        "phase_names_and_descriptions and the count does not match, default names are used "
        "— read the returned phases.",
        {"race_id": {"type": "integer", "description": "id of a saved race from context.races"},
         "race_name": {"type": "string"}, "race_date": DATE,
         "distance_km": {"type": "number"}, "is_target": {"type": "boolean"},
         "confirmed_new_race": {"type": "boolean",
                                "description": "true only when the athlete stated this new race's date themselves"},
         "available_days": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 6},
                            "description": "Weekdays, 0 = Monday."},
         "long_run_day": {"type": "integer", "minimum": 0, "maximum": 6},
         "phase_names_and_descriptions": {"type": "array", "items": {
             "type": "object", "properties": {"name": {"type": "string"},
                                              "description": {"type": "string"}}}}},
        []),
    _fn("move_workout", "Move a planned workout to another date (today or later).",
        {"id": {"type": "integer"}, "new_date": DATE}, ["id", "new_date"]),
    _fn("edit_workout",
        "Change one planned workout (today or later, not done) when the athlete asks: a new "
        "total, ± minutes on the run or walk parts, walk breaks, an HR range, a full new step "
        "list, or notes. Validated and sent to the watch if it was there. More than +20 % "
        "running returns status needs_confirmation (nothing saved) — ask the athlete, then call "
        "again with confirmed=true. Only status \"updated\" means it changed.",
        {"id": {"type": "integer"},
         "total_minutes": {"type": "number", "minimum": 5, "maximum": 240},
         "add_minutes": {"type": "number", "minimum": -120, "maximum": 120},
         "apply_to": {"type": "string", "enum": ["run", "walk", "both"]},
         "add_walk_breaks": {"type": "integer", "minimum": 1, "maximum": 30,
                             "description": "run minutes between 1-minute walk breaks"},
         "hr_low": {"type": "integer"}, "hr_high": {"type": "integer"},
         "steps": {"type": "array", "items": EDIT_STEP,
                   "description": "Replaces every step. Durations in seconds."},
         "notes": {"type": "string"},
         "confirmed": {"type": "boolean",
                       "description": "true only after the athlete agreed to a needs_confirmation change"}},
        ["id"]),
    _fn("edit_week",
        "Apply one change to every planned workout (today or later) in a plan week: "
        "add_minutes (value = ± minutes per session), scale (value = factor 0.5–1.5), "
        "add_walk_breaks (value = run minutes between 1-minute walks) or set_hr_range "
        "(hr_low + hr_high). Same rules as edit_workout, incl. needs_confirmation.",
        {"week_start": DATE,
         "action": {"type": "string",
                    "enum": ["add_minutes", "scale", "add_walk_breaks", "set_hr_range"]},
         "value": {"type": "number"},
         "hr_low": {"type": "integer"}, "hr_high": {"type": "integer"},
         "apply_to": {"type": "string", "enum": ["run", "walk", "both"]},
         "kinds": {"type": "array", "items": {"type": "string"},
                   "description": "Only these kinds, e.g. [\"EASY\", \"LONG\"]"},
         "confirmed": {"type": "boolean"}},
        ["week_start", "action"]),
    _fn("skip_workout", "Skip a planned workout.",
        {"id": {"type": "integer"}, "reason": {"type": "string"}}, ["id", "reason"]),
    _fn("clear_day", "Skip every planned workout on a date and log the reason in the journal.",
        {"date": DATE, "reason": {"type": "string"}}, ["date", "reason"]),
    _fn("log_journal", "Record how the athlete feels (pain, illness, sleep, effort). Feeds readiness.",
        {"text": {"type": "string"}, "applies_to_date": DATE}, ["text", "applies_to_date"]),
    _fn("get_diet_day", "Calorie/macro targets, what was eaten, and run fueling for a date.",
        {"date": DATE}, ["date"]),
    _fn("log_meal", "Estimate a meal from its description and save it to the food log.",
        {"description": {"type": "string"},
         "meal_type": {"type": "string", "enum": ["breakfast", "lunch", "dinner", "snack"]},
         "eaten_at": {"type": "string", "description": "ISO datetime, athlete local time"}},
        ["description", "meal_type"]),
    _fn("log_habit",
        "Log cigarettes (smoke), standard drinks (alcohol) or sugar servings (sugar) the "
        "athlete says they had, e.g. 'had 2 beers at 9' -> alcohol 2 at 21:00 today. "
        "Only log what they actually said; never guess a quantity.",
        {"kind": {"type": "string", "enum": ["smoke", "alcohol", "sugar"]},
         "quantity": {"type": "number", "minimum": 0.1, "maximum": 100},
         "at": {"type": "string", "description": "ISO datetime, athlete local time; "
                "omit for now"}},
        ["kind", "quantity"]),
    _fn("add_memory", "Remember a durable fact about the athlete.",
        {"text": {"type": "string"}}, ["text"]),
    # R17 §10: illness mode.
    _fn("set_illness",
        "Mark the athlete as sick or injured when they tell you so. Pauses every upcoming "
        "planned workout (removed from the watch) until they are better. Only when the "
        "athlete says they are unwell; never guess.",
        {"type": {"type": "string", "enum": ["cold", "flu", "stomach", "injury", "other"],
                  "description": "flu = fever / flu"},
         "symptoms": {"type": "string", "enum": ["above_neck", "below_neck"]},
         "fever": {"type": "boolean"},
         "start_date": {**DATE, "description": "YYYY-MM-DD, default today (≤ 14 days ago)"},
         "expected_days": {"type": "integer", "minimum": 1, "maximum": 60},
         "note": {"type": "string"}},
        ["type"]),
    _fn("recover_illness",
        "The athlete says they are better: end illness mode and build the easy "
        "return-to-run block (then the plan resumes).",
        {"date": {**DATE, "description": "YYYY-MM-DD the athlete felt better, default today"}},
        []),
]


def _date(raw) -> dt.date:
    return dt.date.fromisoformat(str(raw)[:10])


def _day(day) -> str:
    return f"{day:%a} {day.day} {day:%b}"


def _minutes(brief: dict) -> dict:
    return {"total_min": round(brief["duration_s"] / 60, 1),
            "run_min": round(brief["run_s"] / 60, 1)}


class ToolRunner:
    """Dispatches tool calls for one athlete and collects attachments to show."""

    def __init__(self, athlete: Athlete, chat_message=None):
        self.athlete = athlete
        self.chat_message = chat_message
        self.attachments: list[dict] = []
        # R16 §B: [{workout_id, date, summary}] for the "Plan updated" chip.
        self.plan_changed: list[dict] = []
        # R16 §B: the last edit that is waiting for the athlete's yes (or None).
        self.needs_confirmation: dict | None = None

    def _changed(self, workout_id: int, day, summary: str) -> None:
        self.plan_changed = [c for c in self.plan_changed if c["workout_id"] != workout_id]
        self.plan_changed.append({"workout_id": workout_id, "date": str(day),
                                  "summary": summary[:200]})

    def __call__(self, name: str, args: dict):
        handler = getattr(self, f"t_{name}", None)
        if handler is None:
            return {"error": f"Unknown tool {name}."}
        return handler(**args)

    def _attach(self, kind: str, pk: int):
        ref = {"type": kind, "id": pk}
        if ref not in self.attachments:
            self.attachments.append(ref)

    def _workout(self, pk) -> PlannedWorkout:
        workout = PlannedWorkout.objects.filter(athlete=self.athlete, pk=int(pk)).first()
        if workout is None:
            raise ValueError("No such workout.")
        return workout

    # --- read -----------------------------------------------------------------
    def t_get_training_summary(self, weeks=6):
        return training_summary(self.athlete, int(weeks))

    def t_get_activity(self, id):
        from .context import run_summary

        activity = Activity.objects.filter(athlete=self.athlete, pk=int(id)).select_related(
            "metrics").first()
        if activity is None:
            return {"error": "No such activity."}
        notes = JournalEntry.objects.filter(athlete=self.athlete, applies_to_date=activity.local_date)
        return {
            "id": activity.pk, "sport": activity.sport, "date": activity.local_date,
            "duration_min": round((activity.total_timer_s or 0) / 60, 1),
            "avg_hr": activity.avg_hr, "max_hr": activity.max_hr,
            "metrics": run_summary(activity), "km_splits": km_splits(activity),
            "journal": [e.text[:300] for e in notes[:3]],
        }

    def t_get_workout(self, id):
        return workout_json(self._workout(id))

    def t_get_workouts(self, start, end):
        rows = PlannedWorkout.objects.filter(
            athlete=self.athlete, date__gte=_date(start), date__lte=_date(end),
            plan__status=TrainingPlan.Status.ACTIVE,
        ).select_related("phase")[:40]
        return [workout_json(w) for w in rows]

    def t_get_diet_day(self, date):
        from apps.diet.services import diet_day

        return diet_day(self.athlete, _date(date))

    # --- write ----------------------------------------------------------------
    def t_propose_plan(self, race_id=None, race_name=None, race_date=None, distance_km=None,
                       is_target=True, confirmed_new_race=False, available_days=None,
                       long_run_day=None, phase_names_and_descriptions=None):
        from apps.planning.models import Race

        today = self.athlete.local_today
        if race_id is not None:
            race = Race.objects.filter(athlete=self.athlete, pk=int(race_id)).first()
            if race is None:
                return {"error": f"No saved race with id {race_id}.", "races": upcoming_races(self.athlete)}
            race_name, race_date, distance_km = race.name, race.date, race.distance_km
            is_target = race.is_target or not Race.objects.filter(
                athlete=self.athlete, is_target=True, date__gte=today).exists()
        else:
            if not (race_name and race_date and distance_km):
                return {"error": "Pass race_id for a saved race, or race_name, race_date and "
                                 "distance_km for a new one the athlete named.",
                        "races": upcoming_races(self.athlete)}
            race_date = _date(race_date)
            saved = upcoming_races(self.athlete)
            # The model once planned for an invented date while the athlete's own race sat
            # in their profile, and the tool quietly saved the invented one as a new race.
            # A new date while saved races exist needs the athlete's explicit word.
            if saved and not any(r["date"] == race_date for r in saved) and not confirmed_new_race:
                return {"error": "The athlete already has saved races and this date matches none "
                                 "of them. Use race_id, or ask the athlete to confirm the new "
                                 "race's date and then call again with confirmed_new_race=true.",
                        "races": saved}
        try:
            plan = propose_plan(
                self.athlete, race_name=race_name, race_date=race_date if isinstance(race_date, dt.date) else _date(race_date),
                distance_km=float(distance_km), is_target=bool(is_target),
                available_days=available_days, long_run_day=long_run_day,
                phase_names_and_descriptions=phase_names_and_descriptions,
                chat_message=self.chat_message,
            )
        except PlanError as exc:
            return {"error": str(exc)}
        self._attach("plan_proposal", plan.pk)
        return {
            "plan_id": plan.pk, "status": plan.status, "name": plan.name, "goal": plan.goal,
            "phases": [{"name": p.name, "kind": p.kind, "start": p.start, "end": p.end,
                        "description": p.description} for p in plan.phases.all()],
            "warnings": plan.summary.get("warnings", []),
            "peak_run_km": plan.summary.get("peak_run_km"),
            "note": "Shown to the athlete as a proposal card. Not active until they accept.",
        }

    def t_move_workout(self, id, new_date):
        workout = self._workout(id)
        day = _date(new_date)
        if day < self.athlete.local_today:
            return {"error": "Cannot move a workout into the past."}
        old = workout.date
        workout.moved_from = workout.moved_from or workout.date
        workout.date = day
        with transaction.atomic():
            workout.save(update_fields=["date", "moved_from"])
            resync_on_garmin(self.athlete, [workout.pk])
        self._attach("workout", workout.pk)
        if old != day:
            self._changed(workout.pk, day, f"{workout.title}: moved {_day(old)} → {_day(day)}")
        return workout_json(workout)

    def t_skip_workout(self, id, reason=""):
        workout = self._workout(id)
        workout.status = PlannedWorkout.Status.SKIPPED
        with transaction.atomic():
            workout.save(update_fields=["status"])
            remove_from_garmin(self.athlete, [workout.pk])
        self._attach("workout", workout.pk)
        self._changed(workout.pk, workout.date, f"{_day(workout.date)}: {workout.title} skipped")
        return {"skipped": workout.pk, "reason": reason}

    def t_clear_day(self, date, reason=""):
        day = _date(date)
        rows = list(PlannedWorkout.objects.filter(
            athlete=self.athlete, date=day, status=PlannedWorkout.Status.PLANNED,
        ).values_list("pk", "title"))
        skipped = [pk for pk, _ in rows]
        with transaction.atomic():
            PlannedWorkout.objects.filter(pk__in=skipped).update(
                status=PlannedWorkout.Status.SKIPPED)
            remove_from_garmin(self.athlete, skipped)
        JournalEntry.objects.create(
            athlete=self.athlete, text=reason or "Day cleared from chat.",
            written_on=self.athlete.local_today, applies_to_date=day,
            source=JournalEntry.Source.CHAT,
        )
        for pk, title in rows:
            self._changed(pk, day, f"{_day(day)}: {title} skipped")
        return {"date": day, "skipped_workout_ids": skipped}

    def t_edit_workout(self, id, total_minutes=None, add_minutes=None, apply_to=None,
                       add_walk_breaks=None, hr_low=None, hr_high=None, steps=None,
                       notes=None, confirmed=False):
        from apps.planning import edit_service as service

        data = {k: v for k, v in {
            "total_minutes": total_minutes, "add_minutes": add_minutes, "apply_to": apply_to,
            "add_walk_breaks": add_walk_breaks, "hr_low": hr_low, "hr_high": hr_high,
            "steps": steps, "notes": notes}.items() if v is not None}
        try:
            outcome = service.edit_workout(self.athlete, int(id), data, via="chat",
                                           cap=service.CHAT_CAP, confirmed=bool(confirmed))
        except PlannedWorkout.DoesNotExist:
            return {"error": "No such workout."}
        except (service.NotEditable, service.EditError) as exc:
            return {"error": str(exc)}
        workout = outcome.workout
        brief = {"workout_id": workout.pk, "date": workout.date, "title": workout.title,
                 "before": _minutes(outcome.before), "after": _minutes(outcome.after),
                 "summary": outcome.summary,
                 "warnings": [w["text"] for w in outcome.warnings]}
        if outcome.needs_confirmation:
            self.needs_confirmation = {
                "workout_id": workout.pk, "date": str(workout.date),
                "summary": f"{outcome.summary} (+{outcome.increase_pct}%)",
                "increase_pct": outcome.increase_pct}
            return {"status": "needs_confirmation", **brief,
                    "increase_pct": outcome.increase_pct,
                    "message": f"This adds {outcome.increase_pct} % to the session — more than "
                               "the 20 % allowed without asking. NOTHING WAS SAVED. Tell the "
                               "athlete exactly what would change and ask; only if they agree, "
                               "call edit_workout again with the same arguments and "
                               "confirmed=true."}
        if not outcome.changed:
            return {"status": "unchanged", **brief,
                    "message": "Nothing changed — the session already looks like that."}
        self._attach("workout", workout.pk)
        self._changed(workout.pk, workout.date, outcome.summary)
        if (self.needs_confirmation or {}).get("workout_id") == workout.pk:
            self.needs_confirmation = None
        return {"status": "updated", **brief, "watch_status": outcome.watch.get("status")}

    def t_edit_week(self, week_start, action, value=None, hr_low=None, hr_high=None,
                    apply_to=None, kinds=None, confirmed=False):
        from apps.planning import edit_service as service

        if action == "set_hr_range" and hr_low is not None:
            value = {"hr_low": hr_low, "hr_high": hr_high}
        try:
            result = service.edit_week(self.athlete, _date(week_start), action, value,
                                       kinds=kinds, apply_to=apply_to, via="chat",
                                       cap=service.CHAT_CAP, confirmed=bool(confirmed))
        except service.NoActivePlan:
            return {"error": "There is no active plan."}
        except (ValueError, service.EditError) as exc:
            return {"error": str(exc)}
        changed = [{"workout_id": o.workout.pk, "date": o.workout.date,
                    "title": o.workout.title, "summary": o.summary,
                    "increase_pct": o.increase_pct} for o in result.outcomes]
        warnings = [f"{w['date']}: {w['text']}" for w in result.warnings]
        if result.needs_confirmation:
            top = max((o.increase_pct or 0 for o in result.outcomes), default=0)
            self.needs_confirmation = {
                "week_start": str(result.week_start),
                "summary": "; ".join(o.summary for o in result.outcomes)[:300]
                           + f" (up to +{top}%)",
                "increase_pct": top}
            return {"status": "needs_confirmation", "would_change": changed,
                    "warnings": warnings,
                    "message": "At least one session would get more than 20 % harder. NOTHING "
                               "WAS SAVED. Tell the athlete what would change and ask; only if "
                               "they agree, call edit_week again with confirmed=true."}
        if not result.outcomes:
            return {"status": "unchanged", "skipped": result.skipped,
                    "message": "No session in that week could be changed."}
        for o in result.outcomes:
            self._attach("workout", o.workout.pk)
            self._changed(o.workout.pk, o.workout.date, o.summary)
        if (self.needs_confirmation or {}).get("week_start") == str(result.week_start):
            self.needs_confirmation = None
        return {"status": "updated", "changed": changed, "skipped": result.skipped,
                "warnings": warnings, "watch": result.watch}

    def t_log_journal(self, text, applies_to_date):
        from .client import AIUnavailable
        from .services import extract_journal

        entry = JournalEntry(
            athlete=self.athlete, text=text[:4000], written_on=self.athlete.local_today,
            applies_to_date=_date(applies_to_date), source=JournalEntry.Source.CHAT,
        )
        try:
            facts, _ = extract_journal(self.athlete, text, self.athlete.local_today)
            entry.extracted = facts.model_dump(mode="json")
            entry.pain_reported = facts.pain_reported
            entry.illness_reported = facts.illness_reported
            entry.rpe = facts.rpe
        except AIUnavailable:
            entry.extraction_failed = True
        entry.save()
        return {"journal_id": entry.pk, "pain_reported": entry.pain_reported,
                "illness_reported": entry.illness_reported}

    def t_log_meal(self, description, meal_type="snack", eaten_at=None):
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime

        from apps.diet.estimate import estimate_meal
        from apps.diet.models import Meal
        from apps.diet.services import meal_json

        estimate = estimate_meal(self.athlete, text=description, meal_type=meal_type)
        when = parse_datetime(eaten_at) if eaten_at else None
        if when is not None and timezone.is_naive(when):
            from zoneinfo import ZoneInfo

            when = when.replace(tzinfo=ZoneInfo(self.athlete.timezone or "UTC"))
        meal = Meal.objects.create(
            athlete=self.athlete, eaten_at=when or timezone.now(),
            meal_type=meal_type if meal_type in Meal.MealType.values else "snack",
            description=estimate["description"], items=estimate["items"],
            source=Meal.Source.AI_TEXT, ai_confidence=estimate["confidence"],
        )
        self._attach("meal", meal.pk)
        return meal_json(meal)

    def t_log_habit(self, kind, quantity=1, at=None):
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime

        from apps.habits.models import HabitLog
        from apps.habits.services import KINDS, counts_on, log_json

        # KINDS, not HabitLog.Kind: the private habit is never loggable through chat.
        if kind not in KINDS:
            return {"error": "kind must be smoke, alcohol or sugar."}
        try:
            quantity = float(quantity)
        except (TypeError, ValueError):
            return {"error": "quantity must be a number."}
        if not 0 < quantity <= 100:
            return {"error": "quantity must be between 0.1 and 100."}
        when = parse_datetime(str(at)) if at else None
        if when is not None and timezone.is_naive(when):
            from zoneinfo import ZoneInfo

            when = when.replace(tzinfo=ZoneInfo(self.athlete.timezone or "UTC"))
        now = timezone.now()
        if when is None or when > now:
            when = now                     # never in the future
        log = HabitLog.objects.create(athlete=self.athlete, kind=kind, quantity=quantity,
                                      at=when, note="via chat")
        return {"logged": log_json(log), "today": counts_on(self.athlete, log.local_date)}

    def t_set_illness(self, type, symptoms=None, fever=None, start_date=None,
                      expected_days=None, note=None):
        from apps.health.illness import IllnessError, start
        from apps.planning.models import PlannedWorkout

        data = {"type": type, "symptoms": symptoms, "fever": fever,
                "start_date": start_date, "note": note}
        if expected_days is not None:
            data["expected_days"] = expected_days
        try:
            ill = start(self.athlete, data)
        except IllnessError as exc:
            return {"error": exc.detail}
        first = (PlannedWorkout.objects.filter(athlete=self.athlete, paused_by_illness=ill.pk)
                 .order_by("date", "id").first())
        if first is not None:
            self._changed(first.pk, first.date,
                          f"Plan paused while you're unwell ({ill.paused_count} sessions)")
        return {"status": "started", "illness": {"id": ill.pk, "type": ill.type,
                                                 "start_date": str(ill.start_date)},
                "paused": ill.paused_count}

    def t_recover_illness(self, date=None):
        from apps.health.illness import IllnessError, active, recover

        ill = active(self.athlete)
        if ill is None:
            return {"error": "The athlete is not marked as unwell."}
        try:
            body = recover(ill, _date(date) if date else None)
        except (IllnessError, ValueError) as exc:
            return {"error": getattr(exc, "detail", str(exc))}
        block = body["return_block"] or {}
        for s in block.get("sessions", []):
            if s.get("workout_id"):
                self._changed(s["workout_id"], s["date"], f"{s['title']} (return block)")
        return {"status": "recovered",
                "return_block": {"label": block.get("label"), "start": block.get("start"),
                                 "resumes_on": block.get("resumes_on"),
                                 "sessions": [{"date": s["date"], "title": s["title"],
                                               "minutes": s["duration_s"] // 60,
                                               "hr_cap": s["hr_cap"]}
                                              for s in block.get("sessions", [])]},
                "race_warning": (body.get("race_warning") or {}).get("text")}

    def t_add_memory(self, text):
        fact = add_fact(self.athlete, text, MemoryFact.Source.CHAT, self.chat_message)
        return {"saved": fact is not None}


def add_fact(athlete, text: str, source: str, message=None, *, category: str | None = None,
             pinned: bool = False) -> MemoryFact | None:
    """De-duplicated on normalised text; returns None when already known — or when it
    mentions the private habit (R17: never stored, whatever the source)."""
    from analysis.memory_facts import guess_category, mentions_private_habit

    clean = " ".join((text or "").split())[:300]
    if not clean or mentions_private_habit(clean):
        return None
    key = clean.lower().rstrip(".")
    for existing in MemoryFact.objects.filter(athlete=athlete).values_list("text", flat=True):
        if existing.lower().rstrip(".") == key:
            return None
    return MemoryFact.objects.create(
        athlete=athlete, text=clean, source=source, source_message=message,
        category=category or guess_category(clean), pinned=pinned,
    )


def training_summary(athlete: Athlete, weeks: int = 6) -> list[dict]:
    today = athlete.local_today
    monday = today - dt.timedelta(days=today.weekday())
    start = monday - dt.timedelta(weeks=weeks - 1)
    rows = []
    activities = list(Activity.objects.filter(athlete=athlete, local_date__gte=start)
                      .select_related("metrics"))
    for index in range(weeks):
        week_start = start + dt.timedelta(weeks=index)
        week = [a for a in activities
                if week_start <= a.local_date < week_start + dt.timedelta(days=7)]
        metrics = [a.metrics for a in week if getattr(a, "metrics", None)]
        rows.append({
            "week_start": week_start,
            "sessions": len(week),
            "minutes": round(sum(a.total_timer_s or 0 for a in week) / 60),
            "load": round(sum(m.custom_load or 0 for m in metrics), 1),
            "run_km": round(sum(m.run_distance_m for m in metrics) / 1000, 2),
            "longest_continuous_run_min": round(
                max((m.longest_run_s for m in metrics), default=0) / 60, 1),
        })
    return rows


def km_splits(activity: Activity) -> list[dict]:
    """Seconds per whole kilometre from the per-second records."""
    splits, next_km, last_t = [], 1000.0, 0.0
    from apps.activities.quality import series

    for offset, distance in ((r["offset_s"], r["distance_m"])
                             for r in series(activity, ("distance_m",))):
        if distance is not None and distance >= next_km:
            splits.append({"km": int(next_km // 1000), "seconds": round(offset - last_t)})
            last_t, next_km = offset, next_km + 1000
    return splits
