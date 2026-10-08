"""R16 §A/§B: edit a planned workout (or a week of them) — the Django half.

The rules (validation, transforms, warnings) are in planning/edit.py (pure). This module
loads and locks the rows, works out the context the warnings need (the generated
version, the neighbouring days, the week), saves, keeps the generated version for
"Undo my edits", and re-sends the watch copy when the workout was on the watch.

Used by both the app endpoints (plan_views / edit_views) and the coach's chat tools
(apps/coaching/tools.py), so a chat edit and an app edit are the same edit: the same
validation, the same warnings, the same watch re-send. The chat tools pass `cap=0.20`:
a bigger increase is not saved and comes back `needs_confirmation`.

An edited workout is marked `edited_by="user"`; auto-adjust, the weekly adaptation,
weather swaps and re-layout leave its content alone (see those modules).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from nutrition.fueling import fueling_for
from nutrition.targets import FALLBACK_WEIGHT_KG
from planning import edit as rules

from .models import PlannedWorkout, TrainingPlan

logger = logging.getLogger(__name__)

USER = "user"
SNAPSHOT_FIELDS = ("title", "kind", "duration_s", "load", "steps", "target_zone",
                   "description", "fueling", "notes")
EDIT_PUSH_WAIT_S = 20
CHAT_CAP = 0.20
NOT_EDITABLE_TEXT = {
    "completed": "This session is already done — completed sessions can't be edited.",
    "skipped": "This session was skipped — move it back to planned first.",
    "past": "This session is in the past.",
    "notes_only": "Only notes can be changed on race day (and on a rest day).",
}


class NotEditable(Exception):
    """409: the workout can't be edited (done, skipped, past, race)."""


EditError = rules.EditError


# --- helpers -----------------------------------------------------------------------------

def editable_reason(workout: PlannedWorkout, today: dt.date | None = None) -> str | None:
    """None = fully editable; "notes_only" for a race / rest day; else why not."""
    today = today or workout.athlete.local_today
    if workout.status == PlannedWorkout.Status.COMPLETED or workout.completed_activity_id:
        return "completed"
    if workout.status == PlannedWorkout.Status.SKIPPED:
        return "skipped"
    if workout.date < today:
        return "past"
    if workout.kind in ("RACE", "REST") or not workout.steps:
        return "notes_only"
    return None


def limits_for(athlete) -> rules.Limits:
    return rules.limits_for(athlete.resting_hr, athlete.max_hr, athlete.age)


def easy_top(athlete) -> int | None:
    zones = athlete.zones()
    return zones.band("Z2").high if zones else athlete.hr_easy_max


def snapshot(workout: PlannedWorkout) -> dict:
    return {f: getattr(workout, f) for f in SNAPSHOT_FIELDS}


def base_steps(workout: PlannedWorkout) -> list[dict]:
    """The generated version's steps: the baseline for warnings and the chat cap."""
    if workout.edited_by == USER and workout.pre_edit:
        return workout.pre_edit.get("steps") or []
    return workout.steps or []


def brief(title, steps) -> dict:
    return {"title": title, "duration_s": rules.total_s(steps), "run_s": rules.run_s(steps),
            "walk_s": rules.walk_s(steps)}


def day_label(day: dt.date) -> str:
    return f"{day:%a} {day.day} {day:%b}"


def summary_text(day: dt.date, before: dict, after: dict, changes: dict) -> str:
    parts = []
    a, b = round(before["duration_s"] / 60), round(after["duration_s"] / 60)
    if a != b:
        parts.append(f"{a} → {b} min")
    elif before["run_s"] != after["run_s"]:
        parts.append(f"running {round(before['run_s'] / 60)} → {round(after['run_s'] / 60)} min")
    if "add_walk_breaks" in changes:
        parts.append(f"walk breaks every {changes['add_walk_breaks']} min")
    if "hr_low" in changes:
        parts.append(f"HR {changes['hr_low']}–{changes['hr_high']} bpm")
    if "steps" in changes and not parts:
        parts.append("steps changed")
    if "notes" in changes and not parts:
        parts.append("notes updated")
    return f"{day_label(day)}: " + (", ".join(parts) if parts else "no change")


def _week_bounds(day: dt.date) -> tuple[dt.date, dt.date]:
    monday = day - dt.timedelta(days=day.weekday())
    return monday, monday + dt.timedelta(days=6)


def _context(athlete, workout: PlannedWorkout, top: int | None, overrides: dict) -> tuple:
    """(neighbour_hard, week_other_runs) for the warnings. `overrides` = {id: steps} of
    workouts being changed in the same request (a week edit)."""
    monday, sunday = _week_bounds(workout.date)
    lo = min(monday, workout.date - dt.timedelta(days=1))
    hi = max(sunday, workout.date + dt.timedelta(days=1))
    rows = PlannedWorkout.objects.filter(athlete=athlete, plan_id=workout.plan_id,
                                         date__gte=lo, date__lte=hi) \
        .exclude(status=PlannedWorkout.Status.SKIPPED).exclude(pk=workout.pk)
    neighbour_hard, others = False, []
    for row in rows:
        steps = overrides.get(row.pk, row.steps or [])
        if abs((row.date - workout.date).days) == 1 and rules.is_hard(row.kind, steps, top):
            neighbour_hard = True
        if monday <= row.date <= sunday and rules.run_s(steps) > 0:
            others.append(rules.run_s(steps))
    return neighbour_hard, others


def _apply_fields(athlete, workout: PlannedWorkout, steps, notes, via: str) -> None:
    if steps is not None:
        total = rules.total_s(steps)
        workout.title = rules.retitle(workout.title, total)[:120]
        workout.steps = steps
        workout.duration_s = total
        workout.load = rules.load_for(steps)
        workout.fueling = fueling_for(workout.kind, total,
                                      athlete.weight_kg or FALLBACK_WEIGHT_KG).as_dict()
    if notes is not None:
        workout.notes = notes
    if workout.edited_by != USER or not workout.pre_edit:
        workout.pre_edit = None        # set by the caller from the pre-change snapshot
    workout.edited_by = USER
    workout.edited_at = timezone.now()
    workout.edited_via = via


@dataclass
class Outcome:
    workout: PlannedWorkout
    changes: dict
    before: dict
    after: dict
    summary: str
    warnings: list[dict] = field(default_factory=list)
    changed: bool = False
    dry_run: bool = False
    was_on_watch: bool = False
    needs_confirmation: bool = False
    increase_pct: int | None = None
    watch: dict = field(default_factory=dict)
    pending: dict = field(default_factory=dict)      # {steps, notes} to write

    def brief_json(self) -> dict:
        return {"workout_id": self.workout.pk, "date": self.workout.date,
                "title": self.workout.title, "before": self.before, "after": self.after,
                "summary": self.summary}


def _plan_one(athlete, workout: PlannedWorkout, changes: dict, *, today, limits, top,
              overrides: dict) -> Outcome:
    """Compute (not save) one workout's edit. Raises NotEditable / EditError."""
    reason = editable_reason(workout, today)
    if reason == "notes_only" and rules.touches_steps(changes):
        raise NotEditable(NOT_EDITABLE_TEXT["notes_only"])
    if reason not in (None, "notes_only"):
        raise NotEditable(NOT_EDITABLE_TEXT[reason])
    steps = None
    if rules.touches_steps(changes):
        steps = rules.apply(workout.steps or [], rules.scaled_changes(changes, workout.steps),
                            limits)
    new_steps = steps if steps is not None else (workout.steps or [])
    base = base_steps(workout)
    before = brief(workout.title, workout.steps or [])
    after = brief(rules.retitle(workout.title, rules.total_s(new_steps)), new_steps)
    warnings: list[dict] = []
    if steps is not None:
        neighbour_hard, others = _context(athlete, workout, top, overrides)
        warnings = rules.warnings_for(
            kind=workout.kind, base_steps=base, new_steps=new_steps,
            hr_ceiling=athlete.hr_ceiling, easy_top=top, neighbour_hard=neighbour_hard,
            week_other_runs=others)
    changed = (steps is not None and steps != (workout.steps or [])) or (
        "notes" in changes and changes["notes"] != (workout.notes or ""))
    return Outcome(workout=workout, changes=changes, before=before, after=after,
                   summary=summary_text(workout.date, before, after, changes),
                   warnings=warnings, changed=changed,
                   was_on_watch=bool(workout.garmin_workout_id),
                   increase_pct=round(rules.increase_ratio(base, new_steps) * 100)
                   if steps is not None else 0,
                   pending={"steps": steps, "notes": changes.get("notes")})


def _save(athlete, outcome: Outcome, via: str) -> None:
    workout = outcome.workout
    pending = outcome.pending
    first = workout.edited_by != USER or not workout.pre_edit
    pre = snapshot(workout) if first else workout.pre_edit
    _apply_fields(athlete, workout, pending["steps"], pending["notes"], via)
    workout.pre_edit = pre
    workout.save()


def _preview_instance(athlete, outcome: Outcome, via: str) -> None:
    """dry_run: show the edited workout without saving it."""
    workout = outcome.workout
    pending = outcome.pending
    pre = workout.pre_edit if workout.edited_by == USER and workout.pre_edit \
        else snapshot(workout)
    _apply_fields(athlete, workout, pending["steps"], pending["notes"], via)
    workout.pre_edit = pre


# --- watch ---------------------------------------------------------------------------------

def push_now(athlete, ids: list[int]) -> dict[int, dict]:
    """Re-send workouts that are on the watch, through the normal garmin-queue send job
    (registry sweep, old copy deleted, new upload). Waits up to EDIT_PUSH_WAIT_S.
    Returns {workout_id: {status, detail}}. Never raises."""
    from .tasks import run_garmin_push

    if not ids:
        return {}
    try:
        job = run_garmin_push(athlete.pk, ids, "send", wait_s=EDIT_PUSH_WAIT_S)
    except Exception as exc:  # noqa: BLE001 — the save stands whatever Garmin does
        logger.warning("edit re-send failed for %s: %s", ids, exc)
        job = {"ok": False, "code": "error", "detail": str(exc)[:200], "results": []}
    code = job.get("code")
    if code == "queue":
        return {i: {"status": "pending",
                    "detail": "Sending to your watch in the background."} for i in ids}
    if code in ("rate_limited", "auth", "gone", "error"):
        return {i: {"status": "failed", "detail": job.get("detail") or
                    "Garmin is unavailable — use “Update on watch” later."} for i in ids}
    out = {}
    by_id = {r["workout_id"]: r for r in job.get("results") or []}
    for i in ids:
        result = by_id.get(i)
        status = (result or {}).get("status")
        if status in ("uploaded", "updated", "removed"):
            out[i] = {"status": "updated", "detail": "Updated on your watch."}
        elif status == "unchanged":
            out[i] = {"status": "unchanged", "detail": "Your watch already has this version."}
        else:
            out[i] = {"status": "failed",
                      "detail": (result or {}).get("detail") or "Garmin refused the update."}
    return out


def _watch_json(outcome: Outcome, pushed: dict[int, dict]) -> dict:
    if not outcome.was_on_watch:
        return {"was_on_watch": False, "status": "not_on_watch", "detail": ""}
    if outcome.dry_run or outcome.needs_confirmation:
        return {"was_on_watch": True, "status": "pending",
                "detail": "Saving will update the copy on your watch."}
    got = pushed.get(outcome.workout.pk) or {"status": "unchanged", "detail": ""}
    return {"was_on_watch": True, **got}


# --- public API ------------------------------------------------------------------------------

def _locked(athlete, workout_id) -> PlannedWorkout:
    workout = (PlannedWorkout.objects.select_for_update()
               .filter(athlete=athlete, pk=int(workout_id)).first())
    if workout is None:
        raise PlannedWorkout.DoesNotExist
    return workout


def edit_workout(athlete, workout_id, data: dict, *, via: str = "app", dry_run: bool = False,
                 cap: float | None = None, confirmed: bool = False) -> Outcome:
    """Edit one workout. Raises PlannedWorkout.DoesNotExist, NotEditable, EditError."""
    changes = rules.parse_changes(data)
    today = athlete.local_today
    limits, top = limits_for(athlete), easy_top(athlete)
    with transaction.atomic():
        workout = _locked(athlete, workout_id)
        outcome = _plan_one(athlete, workout, changes, today=today, limits=limits, top=top,
                            overrides={})
        if cap is not None and not confirmed and outcome.increase_pct is not None \
                and outcome.increase_pct > round(cap * 100):
            outcome.needs_confirmation = True
        elif dry_run:
            outcome.dry_run = True
            _preview_instance(athlete, outcome, via)
        elif outcome.changed:
            _save(athlete, outcome, via)
    pushed = {}
    if outcome.changed and outcome.was_on_watch and not outcome.dry_run \
            and not outcome.needs_confirmation:
        pushed = push_now(athlete, [outcome.workout.pk])
        outcome.workout.refresh_from_db()
    outcome.watch = _watch_json(outcome, pushed)
    if outcome.changed and not outcome.dry_run and not outcome.needs_confirmation:
        logger.info("athlete %s edited workout %s via %s: %s", athlete.pk,
                    outcome.workout.pk, via, outcome.summary)
    return outcome


def undo_edit(athlete, workout_id) -> Outcome:
    """Restore the generated version. Raises DoesNotExist / NotEditable."""
    today = athlete.local_today
    with transaction.atomic():
        workout = _locked(athlete, workout_id)
        reason = editable_reason(workout, today)
        if workout.edited_by != USER or not workout.pre_edit:
            raise NotEditable("This session has no edits to undo.")
        if reason not in (None, "notes_only"):
            raise NotEditable(NOT_EDITABLE_TEXT[reason])
        before = brief(workout.title, workout.steps or [])
        for f in SNAPSHOT_FIELDS:
            if f in workout.pre_edit:
                setattr(workout, f, workout.pre_edit[f])
        workout.edited_by, workout.edited_via = "", ""
        workout.edited_at, workout.pre_edit = None, None
        workout.save()
        after = brief(workout.title, workout.steps or [])
        outcome = Outcome(workout=workout, changes={}, before=before, after=after,
                          summary=f"{day_label(workout.date)}: back to the plan "
                                  f"({round(after['duration_s'] / 60)} min)",
                          changed=True, was_on_watch=bool(workout.garmin_workout_id))
    pushed = push_now(athlete, [workout.pk]) if outcome.was_on_watch else {}
    if pushed:
        outcome.workout.refresh_from_db()
    outcome.watch = _watch_json(outcome, pushed)
    return outcome


RUN_KINDS_FOR_WEEK = frozenset({"EASY", "RUN_WALK", "LONG", "TEMPO", "INTERVALS", "WALK"})


@dataclass
class WeekOutcome:
    week_start: dt.date
    week_end: dt.date
    action: str
    dry_run: bool
    outcomes: list[Outcome]
    skipped: list[dict]
    needs_confirmation: bool = False
    watch: dict = field(default_factory=dict)

    @property
    def warnings(self) -> list[dict]:
        return [{"workout_id": o.workout.pk, "date": o.workout.date, **w}
                for o in self.outcomes for w in o.warnings]

    def as_json(self) -> dict:
        return {"week_start": self.week_start, "week_end": self.week_end,
                "action": self.action, "dry_run": self.dry_run,
                "changed": [o.brief_json() for o in self.outcomes],
                "skipped": self.skipped, "warnings": self.warnings, "watch": self.watch}


class NoActivePlan(Exception):
    pass


def edit_week(athlete, week_start: dt.date, action: str, value, *, kinds=None,
              apply_to: str | None = None, via: str = "app", dry_run: bool = False,
              cap: float | None = None, confirmed: bool = False) -> WeekOutcome:
    """Apply one change to every matching future workout of a 7-day plan week."""
    changes = rules.week_changes(action, value, apply_to)
    if kinds is not None:
        if not isinstance(kinds, list) or not all(isinstance(k, str) for k in kinds):
            raise EditError("kinds must be a list of workout kinds.")
        kinds = {k.upper() for k in kinds}
    plan = TrainingPlan.objects.filter(athlete=athlete,
                                       status=TrainingPlan.Status.ACTIVE).first()
    if plan is None:
        raise NoActivePlan("No active plan.")
    today = athlete.local_today
    week_end = week_start + dt.timedelta(days=6)
    limits, top = limits_for(athlete), easy_top(athlete)
    outcomes: list[Outcome] = []
    skipped: list[dict] = []
    with transaction.atomic():
        rows = list(PlannedWorkout.objects.select_for_update().filter(
            athlete=athlete, plan=plan, date__gte=max(week_start, today), date__lte=week_end,
            status=PlannedWorkout.Status.PLANNED, completed_activity__isnull=True,
        ).order_by("date", "id"))
        rows = [w for w in rows if w.kind in RUN_KINDS_FOR_WEEK and w.steps
                and (kinds is None or w.kind in kinds)]
        overrides: dict[int, list] = {}
        for workout in rows:
            try:
                outcome = _plan_one(athlete, workout, changes, today=today, limits=limits,
                                    top=top, overrides=overrides)
            except (EditError, NotEditable) as exc:
                skipped.append({"workout_id": workout.pk, "date": workout.date,
                                "title": workout.title, "reason": str(exc)})
                continue
            if not outcome.changed:
                skipped.append({"workout_id": workout.pk, "date": workout.date,
                                "title": workout.title, "reason": "Nothing to change."})
                continue
            overrides[workout.pk] = outcome.pending["steps"]
            outcomes.append(outcome)
        # Warnings again, now that every changed session of the week is known.
        for outcome in outcomes:
            neighbour_hard, others = _context(athlete, outcome.workout, top, overrides)
            outcome.warnings = rules.warnings_for(
                kind=outcome.workout.kind, base_steps=base_steps(outcome.workout),
                new_steps=outcome.pending["steps"], hr_ceiling=athlete.hr_ceiling,
                easy_top=top, neighbour_hard=neighbour_hard, week_other_runs=others)
        result = WeekOutcome(week_start=week_start, week_end=week_end, action=action,
                             dry_run=dry_run, outcomes=outcomes, skipped=skipped)
        over = [o for o in outcomes if cap is not None and (o.increase_pct or 0) > round(cap * 100)]
        if over and not confirmed:
            result.needs_confirmation = True
            for o in outcomes:
                o.needs_confirmation = True
        elif dry_run:
            for o in outcomes:
                o.dry_run = True
                _preview_instance(athlete, o, via)
        else:
            for o in outcomes:
                _save(athlete, o, via)
    pushed: dict[int, dict] = {}
    if not dry_run and not result.needs_confirmation:
        on_watch = [o.workout.pk for o in outcomes if o.was_on_watch]
        pushed = push_now(athlete, on_watch)
        for o in outcomes:
            if o.workout.pk in pushed:
                o.workout.refresh_from_db()
    counts = {"updated": 0, "unchanged": 0, "pending": 0, "failed": 0, "not_on_watch": 0}
    for o in outcomes:
        o.watch = _watch_json(o, pushed)
        counts[o.watch["status"]] = counts.get(o.watch["status"], 0) + 1
    result.watch = counts
    return result

