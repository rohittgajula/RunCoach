"""The tools the chat model can call. Every one is Python, scoped to one athlete.

The model proposes; these functions decide. `propose_plan` runs the deterministic
generator — the model may only name and describe phases. `move_workout`, `skip_workout`
and `clear_day` can only make the week easier or shift it, never add load.
"""

from __future__ import annotations

import datetime as dt

from apps.activities.models import Activity
from apps.athletes.models import Athlete
from apps.journal.models import JournalEntry
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
    _fn("add_memory", "Remember a durable fact about the athlete.",
        {"text": {"type": "string"}}, ["text"]),
]


def _date(raw) -> dt.date:
    return dt.date.fromisoformat(str(raw)[:10])


class ToolRunner:
    """Dispatches tool calls for one athlete and collects attachments to show."""

    def __init__(self, athlete: Athlete, chat_message=None):
        self.athlete = athlete
        self.chat_message = chat_message
        self.attachments: list[dict] = []

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
        workout.moved_from = workout.moved_from or workout.date
        workout.date = day
        workout.save(update_fields=["date", "moved_from"])
        self._attach("workout", workout.pk)
        return workout_json(workout)

    def t_skip_workout(self, id, reason=""):
        workout = self._workout(id)
        workout.status = PlannedWorkout.Status.SKIPPED
        workout.save(update_fields=["status"])
        self._attach("workout", workout.pk)
        return {"skipped": workout.pk, "reason": reason}

    def t_clear_day(self, date, reason=""):
        day = _date(date)
        skipped = list(PlannedWorkout.objects.filter(
            athlete=self.athlete, date=day, status=PlannedWorkout.Status.PLANNED,
        ).values_list("pk", flat=True))
        PlannedWorkout.objects.filter(pk__in=skipped).update(status=PlannedWorkout.Status.SKIPPED)
        JournalEntry.objects.create(
            athlete=self.athlete, text=reason or "Day cleared from chat.",
            written_on=self.athlete.local_today, applies_to_date=day,
            source=JournalEntry.Source.CHAT,
        )
        return {"date": day, "skipped_workout_ids": skipped}

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

    def t_add_memory(self, text):
        fact = add_fact(self.athlete, text, MemoryFact.Source.CHAT, self.chat_message)
        return {"saved": fact is not None}


def add_fact(athlete, text: str, source: str, message=None) -> MemoryFact | None:
    """De-duplicated on normalised text; returns None when already known."""
    clean = " ".join((text or "").split())[:300]
    if not clean:
        return None
    key = clean.lower().rstrip(".")
    for existing in MemoryFact.objects.filter(athlete=athlete).values_list("text", flat=True):
        if existing.lower().rstrip(".") == key:
            return None
    return MemoryFact.objects.create(
        athlete=athlete, text=clean, source=source, source_message=message
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
    for offset, distance in activity.records.order_by("offset_s").values_list(
            "offset_s", "distance_m"):
        if distance is not None and distance >= next_km:
            splits.append({"km": int(next_km // 1000), "seconds": round(offset - last_t)})
            last_t, next_km = offset, next_km + 1000
    return splits
