"""R13 §1: auto-adjust the next sessions after each run (Django half).

The rules are in planning/adapt.py (pure). This gathers the facts (the run, its
check-in, this morning's wellness, habits, pain, injury risk), applies the decision to
the persisted PlannedWorkouts and records each change as a WorkoutAdjustment the athlete
can undo. Changed workouts already on the watch are re-sent (garmin_sync).

Runs only when the athlete has "Auto-adjust plan" on. Never touches completed, skipped,
past or RACE sessions, sessions the athlete edited (moved, check-in applied, an auto
change undone → `adjusted_by="kept"`, R16 edits → `edited_by="user"`), or sessions
already auto-adjusted — except that an
auto *extension* is reverted before easing that session, so a later strain signal always
wins over the +5 % rule.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.activities.models import Activity
from apps.athletes.models import Athlete
from nutrition.fueling import fueling_for
from nutrition.targets import FALLBACK_WEIGHT_KG
from planning import adapt
from planning.generator import Session
from planning.workouts import build_workout

from .models import INACTIVE_STATUSES, PlannedWorkout, TrainingPlan, WorkoutAdjustment

logger = logging.getLogger(__name__)

AUTO = "auto"
KEPT = "kept"
RECENT_RUNS = 5
RECENT_DAYS = 21
RECENT_ACTIVITY_DAYS = 2
RUN_WALK_RUN_SHARE = 0.6
FIELDS = ("title", "kind", "duration_s", "load", "steps", "target_zone", "description",
          "fueling")


class NotUndoable(Exception):
    pass


# --- facts ---------------------------------------------------------------------------

def _run_s(steps) -> int:
    return sum(int(s.get("duration_s") or 0) for s in steps or [] if s.get("intensity") != "walk")


def _walk_s(steps) -> int:
    return sum(int(s.get("duration_s") or 0) for s in steps or [] if s.get("intensity") == "walk")


def _zone_top(athlete, zone: str | None, zones=None) -> int | None:
    zones = zones if zones is not None else athlete.zones()
    name = zone if zone in ("Z1", "Z2", "Z3", "Z4", "Z5") else "Z2"
    if zones is not None:
        return zones.band(name).high
    return athlete.hr_easy_max if name in ("Z1", "Z2") else athlete.hr_ceiling


def run_facts(athlete, activity: Activity, zones=None) -> adapt.RunFacts:
    from .actuals import checkin_rpe

    metrics = getattr(activity, "metrics", None)
    workout = PlannedWorkout.objects.filter(athlete=athlete, completed_activity=activity).first()
    planned_steps = None
    if workout is not None:
        planned_steps = workout.original_steps if (workout.adjusted_by == "checkin"
                                                   and workout.original_steps) else workout.steps
    return adapt.RunFacts(
        date=activity.local_date,
        planned_kind=workout.kind if workout else None,
        planned_run_s=_run_s(planned_steps) if workout else None,
        actual_run_s=metrics.run_duration_s if metrics else None,
        rpe=checkin_rpe(activity),
        avg_hr=(metrics.avg_run_hr if metrics and metrics.avg_run_hr else activity.avg_hr),
        zone_top=_zone_top(athlete, workout.target_zone if workout else "Z2", zones),
        drift_pct=metrics.hr_drift_percent if metrics else None,
    )


def _recent_runs(athlete, today: dt.date, zones) -> list[adapt.RunFacts]:
    rows = list(Activity.objects.filter(
        athlete=athlete, sport__icontains="run",
        local_date__gte=today - dt.timedelta(days=RECENT_DAYS), local_date__lte=today,
    ).select_related("metrics").order_by("-started_at")[:RECENT_RUNS])
    return [run_facts(athlete, a, zones) for a in reversed(rows)]


def context_for(athlete, today: dt.date, zones=None) -> adapt.Context:
    from analysis.sleep import debt

    from apps.habits.models import HabitLog
    from apps.health.injury import assess
    from apps.ingest.models import DailyMetrics

    rows = list(DailyMetrics.objects.filter(
        athlete=athlete, metric_date__gt=today - dt.timedelta(days=8), metric_date__lte=today,
    ).order_by("metric_date"))
    todays = next((r for r in rows if r.metric_date == today), None)
    from apps.athletes.effective import night_need_s, sleep_need

    need_info = sleep_need(athlete)                  # R18: one helper everywhere
    sleep = debt([(r.sleep_seconds, night_need_s(need_info, r.sleep_need_seconds))
                  for r in rows])
    drinks = HabitLog.objects.filter(athlete=athlete, kind="alcohol",
                                     local_date=today - dt.timedelta(days=1)) \
        .aggregate(total=Sum("quantity"))["total"]
    injury = assess(athlete, today)
    signal = injury.get("pain_signal")
    pain_label = None
    if signal:
        pain_label = f"your {signal['label'].lower()}"
    return adapt.Context(
        readiness=todays.training_readiness if todays else None,
        sleep_debt_s=sleep["debt_s"], drinks_last_night=drinks,
        pain=signal["status"] if signal else None, pain_label=pain_label,
        injury_risk=injury["risk"], recent_runs=_recent_runs(athlete, today, zones))


def _plan_week_start(plan: TrainingPlan, day: dt.date) -> dt.date:
    first = plan.phases.order_by("start").values_list("start", flat=True).first()
    if first is None or day < first:
        return day - dt.timedelta(days=day.weekday())
    return first + dt.timedelta(days=((day - first).days // 7) * 7)


def _baseline_steps(workout: PlannedWorkout) -> list:
    """The prescription before any auto change (an applied auto adjustment's `before`)."""
    if workout.adjusted_by == AUTO:
        first = (workout.auto_adjustments.filter(status=WorkoutAdjustment.Status.APPLIED)
                 .order_by("created_at", "id").first())
        if first is not None:
            return first.before.get("steps") or []
    return workout.steps or []


def week_room(plan: TrainingPlan, day: dt.date) -> int:
    """This plan week's planned running (as the plan set it, before auto changes) minus
    what is prescribed now. Skipped sessions count on neither side."""
    start = _plan_week_start(plan, day)
    rows = plan.workouts.filter(date__gte=start, date__lt=start + dt.timedelta(days=7)) \
        .exclude(status__in=INACTIVE_STATUSES).exclude(kind="RACE")
    planned = sum(_run_s(_baseline_steps(w)) for w in rows)
    current = sum(_run_s(w.steps) for w in rows)
    return planned - current


def _latest_applied(workout: PlannedWorkout) -> WorkoutAdjustment | None:
    return (workout.auto_adjustments.filter(status=WorkoutAdjustment.Status.APPLIED)
            .order_by("-created_at", "-id").first())


def upcoming(athlete, plan: TrainingPlan, today: dt.date, for_easing: bool) -> list[adapt.Upcoming]:
    rows = list(plan.workouts.filter(
        date__gte=today, date__lte=today + dt.timedelta(days=adapt.LOOKAHEAD_DAYS + 2),
    ).order_by("date", "id"))
    out = []
    for w in rows:
        adjusted_by = w.adjusted_by or ""
        if w.edited_by == "user":
            adjusted_by = "user"          # R16: the athlete's own edit is never touched
        elif for_easing and adjusted_by == AUTO:
            latest = _latest_applied(w)
            if latest is not None and latest.action == "extend":
                adjusted_by = ""          # an extension never blocks easing
        out.append(adapt.Upcoming(
            id=w.pk, date=w.date, kind=w.kind, run_s=_run_s(w.steps), status=w.status,
            adjusted_by=adjusted_by, moved=w.moved_from is not None,
            completed=w.completed_activity_id is not None,
            room_s=week_room(plan, w.date) if w.kind in adapt.EXTENDABLE else 0))
    return out


# --- applying ------------------------------------------------------------------------

def snapshot(workout: PlannedWorkout) -> dict:
    return {**{f: getattr(workout, f) for f in FIELDS}, "date": workout.date.isoformat()}


def _restore(workout: PlannedWorkout, state: dict) -> None:
    for f in FIELDS:
        if f in state:
            setattr(workout, f, state[f])
    if state.get("date"):
        workout.date = dt.date.fromisoformat(state["date"])


def _longest_run(steps) -> int:
    return max((int(s.get("duration_s") or 0) for s in steps or [] if s.get("kind") == "run"),
               default=0)


def _rebuild(workout: PlannedWorkout, athlete, *, kind: str, run_s: float, walk_s: float,
             zone: str | None, effort: str | None = None, long_factor: float = 1.0) -> None:
    from .adaptation import _effort
    from .plan_store import bands_for

    longest = _longest_run(workout.steps)
    session = Session(
        date=workout.date, kind=kind, run_minutes=max(run_s, 0) / 60,
        walk_minutes=max(walk_s, 0) / 60, target_run_m=0.0, purpose=workout.purpose,
        effort=effort or _effort(workout.description),
        continuous_target_s=longest * long_factor if kind == "LONG" and longest else None,
        target_zone=zone)
    phase = workout.phase.generator_phase if workout.phase else "FOUNDATION"
    spec = build_workout(session, bands_for(athlete), phase)
    workout.title = spec.title[:120]
    workout.kind = spec.kind
    workout.duration_s = spec.duration_s
    workout.load = spec.load
    workout.steps = [s.as_dict() for s in spec.steps]
    workout.description = spec.description
    workout.target_zone = spec.target_zone
    workout.fueling = fueling_for(spec.kind, spec.duration_s,
                                  athlete.weight_kg or FALLBACK_WEIGHT_KG).as_dict()


def _make_rest(workout: PlannedWorkout) -> None:
    workout.title = "Rest day"
    workout.kind = "REST"
    workout.duration_s = 0
    workout.load = 0.0
    workout.steps = []
    workout.target_zone = None
    workout.description = ("Rest today — the plan eased off because of the pain you reported. "
                           "If it persists, see a physio.")
    workout.fueling = {}


def _minutes(workout: PlannedWorkout) -> int:
    return round(workout.duration_s / 60)


def _what(change: adapt.Change, workout: PlannedWorkout, partner_title: str | None = None) -> str:
    mins = _minutes(workout)
    if change.action == "shorten":
        return f"shortened to {mins} min"
    if change.action == "easier":
        return f"made an easy {mins}-min run"
    if change.action == "run_walk":
        return f"now a {mins}-min run/walk"
    if change.action == "rest":
        return "now a rest day"
    if change.action == "swap":
        return (f"moved to {workout.date:%a} (swapped with {partner_title})" if partner_title
                else f"moved to {workout.date:%a}")
    if change.action == "extend":
        return f"extended to {mins} min"
    return "adjusted"


def _reason(change: adapt.Change, before_title: str, what: str, why: str) -> str:
    if change.action == "extend":
        return (f"Because {why}, {before_title} is {what} — at most 5% more running, and "
                "still within this week's planned volume. Undo it if you'd rather not.")
    return (f"Because {why}, {before_title} was {what}. Auto-adjust only ever makes the "
            "plan easier; undo it if you feel fine.")


def _apply_change(athlete, workout: PlannedWorkout, change: adapt.Change) -> None:
    run_s, walk_s = _run_s(workout.steps), _walk_s(workout.steps)
    if change.action == "rest":
        _make_rest(workout)
    elif change.action == "shorten":
        _rebuild(workout, athlete, kind=workout.kind, run_s=run_s * change.factor,
                 walk_s=walk_s * change.factor, zone=workout.target_zone,
                 long_factor=change.factor)
    elif change.action == "easier":
        factor = change.factor or 1.0
        _rebuild(workout, athlete, kind="EASY", run_s=run_s * factor, walk_s=walk_s * factor,
                 zone="Z2", effort="easy")
    elif change.action == "run_walk":
        total = (run_s + walk_s) * (change.factor or 1.0)
        _rebuild(workout, athlete, kind="RUN_WALK", run_s=total * RUN_WALK_RUN_SHARE,
                 walk_s=total * (1 - RUN_WALK_RUN_SHARE), zone="Z2", effort="easy")
    elif change.action == "extend":
        _rebuild(workout, athlete, kind=workout.kind, run_s=run_s + change.extend_s,
                 walk_s=walk_s, zone=workout.target_zone)
        # build_workout rounds to whole minutes; never let rounding exceed the +5 % cap.
        if _run_s(workout.steps) > run_s + change.extend_s:
            raise ValueError("extension rounded past the cap")
    elif change.action == "swap":
        workout.date = change.new_date


def _eligible_now(workout: PlannedWorkout, today: dt.date, allow_extended: bool) -> bool:
    if workout.edited_by == "user":
        return False
    if workout.adjusted_by == AUTO and allow_extended:
        latest = _latest_applied(workout)
        if latest is None or latest.action != "extend":
            return False
    elif workout.adjusted_by:
        return False
    return (workout.status == PlannedWorkout.Status.PLANNED
            and workout.completed_activity_id is None and workout.date >= today
            and workout.kind in adapt.ADJUSTABLE and workout.moved_from is None)


def evaluate(athlete: Athlete, *, trigger: str, activity: Activity | None = None,
             today: dt.date | None = None) -> list[WorkoutAdjustment]:
    """Decide and apply. Returns the WorkoutAdjustment rows created (maybe none)."""
    if not athlete.auto_adjust_plan:
        return []
    from apps.health.illness import active as illness_active

    if illness_active(athlete) is not None:
        return []                # R17 §10: the plan is paused while unwell
    plan = TrainingPlan.objects.filter(athlete=athlete, status=TrainingPlan.Status.ACTIVE).first()
    if plan is None:
        return []
    today = today or athlete.local_today
    if activity is not None and activity.local_date < today - dt.timedelta(days=RECENT_ACTIVITY_DAYS):
        return []
    zones = athlete.zones()
    run = run_facts(athlete, activity, zones) if activity is not None else None
    ctx = context_for(athlete, today, zones)
    decision = adapt.decide(run, ctx, upcoming(athlete, plan, today, for_easing=True), today)
    if decision.severity == "extend":
        if trigger != "run":
            return []
        decision = adapt.decide(run, ctx, upcoming(athlete, plan, today, for_easing=False), today)
    if not decision.changed:
        return []
    if _already_handled(athlete, decision, activity, today):
        return []
    return _apply(athlete, plan, decision, trigger, activity, today)


def _already_handled(athlete, decision: adapt.Decision, activity, today) -> bool:
    """One signal is acted on once: re-evaluating the same run (its check-in, a re-derive)
    or the same pain only changes more sessions when a NEW signal has appeared."""
    keys = {s["key"] for s in decision.signals}
    if activity is not None:
        rows = WorkoutAdjustment.objects.filter(athlete=athlete, activity=activity)
    else:
        rows = WorkoutAdjustment.objects.filter(
            athlete=athlete, activity__isnull=True, trigger="pain",
            created_at__date__gte=today - dt.timedelta(days=2))
    seen: set[str] = set()
    for signals in rows.values_list("signals", flat=True):
        seen |= {s.get("key") for s in signals or []}
    return bool(seen) and keys <= seen


def _apply(athlete, plan, decision: adapt.Decision, trigger: str, activity, today) -> list:
    from .garmin_sync import resync_on_garmin

    created: list[WorkoutAdjustment] = []
    signals = [{"key": s["key"], "label": s["label"]} for s in decision.signals]
    with transaction.atomic():
        ids = [c.workout_id for c in decision.changes]
        locked = {w.pk: w for w in PlannedWorkout.objects.select_for_update()
                  .filter(athlete=athlete, pk__in=ids)}
        allow_extended = decision.severity != "extend"
        if any(w is None or not _eligible_now(w, today, allow_extended)
               for w in (locked.get(i) for i in ids)):
            logger.info("auto-adjust for %s skipped: a workout changed meanwhile", athlete.pk)
            return []
        titles = {w.pk: w.title for w in locked.values()}
        for change in decision.changes:
            workout = locked[change.workout_id]
            if workout.adjusted_by == AUTO:         # an extension being replaced
                previous = _latest_applied(workout)
                if previous is not None:
                    _restore(workout, previous.before)
                    previous.status = WorkoutAdjustment.Status.UNDONE
                    previous.undone_at = timezone.now()
                    previous.save(update_fields=["status", "undone_at"])
            before = snapshot(workout)
            try:
                _apply_change(athlete, workout, change)
            except ValueError:
                logger.info("auto-adjust extension for %s dropped (rounding)", workout.pk)
                _restore(workout, before)
                continue
            workout.adjusted_by = AUTO
            workout.save()
            what = _what(change, workout, titles.get(change.swap_with))
            chip = f"Adjusted: {what} — {decision.why}"[:200]
            created.append(WorkoutAdjustment.objects.create(
                athlete=athlete, plan=plan, workout=workout, activity=activity,
                trigger=trigger, action=change.action,
                reason=_reason(change, before["title"], what, decision.why),
                chip=chip, signals=signals, before=before, after=snapshot(workout),
                group=change.group or ""))
        if created:
            resync_on_garmin(athlete, [a.workout_id for a in created])
    if created:
        logger.info("auto-adjusted %d workout(s) for %s (%s)", len(created), athlete.pk,
                    decision.severity)
    return created


# --- undo / presentation ---------------------------------------------------------------

def undoable(adj: WorkoutAdjustment, today: dt.date | None = None) -> bool:
    if adj.status != WorkoutAdjustment.Status.APPLIED or adj.workout_id is None:
        return False
    workout = adj.workout
    today = today or adj.athlete.local_today
    if workout.status != PlannedWorkout.Status.PLANNED or workout.completed_activity_id:
        return False
    if workout.date < today or workout.adjusted_by != AUTO:
        return False
    current = snapshot(workout)
    return all(current.get(k) == adj.after.get(k) for k in ("title", "kind", "duration_s",
                                                             "steps", "date"))


def undo(athlete, adjustment_id: int) -> WorkoutAdjustment:
    from .garmin_sync import resync_on_garmin

    with transaction.atomic():
        adj = (WorkoutAdjustment.objects.select_for_update()
               .filter(athlete=athlete, pk=adjustment_id).first())
        if adj is None:
            raise WorkoutAdjustment.DoesNotExist
        rows = [adj]
        if adj.group:
            rows = list(WorkoutAdjustment.objects.select_for_update().filter(
                athlete=athlete, group=adj.group, status=WorkoutAdjustment.Status.APPLIED))
            if adj not in rows:
                rows.append(adj)
        today = athlete.local_today
        if not all(undoable(r, today) for r in rows):
            raise NotUndoable("This change can't be undone any more — the session has "
                              "changed, been done or is in the past.")
        now = timezone.now()
        for row in rows:
            workout = PlannedWorkout.objects.select_for_update().get(pk=row.workout_id)
            _restore(workout, row.before)
            workout.adjusted_by = KEPT
            workout.save()
            row.status = WorkoutAdjustment.Status.UNDONE
            row.undone_at = now
            row.save(update_fields=["status", "undone_at"])
        resync_on_garmin(athlete, [r.workout_id for r in rows])
    adj.refresh_from_db()
    return adj


def adjustment_json(adj: WorkoutAdjustment, today: dt.date | None = None) -> dict:
    def short(state: dict) -> dict:
        return {"title": state.get("title"), "kind": state.get("kind"),
                "duration_s": state.get("duration_s"), "date": state.get("date")}

    after = adj.after or {}
    return {
        "id": adj.pk, "workout_id": adj.workout_id,
        "workout_date": after.get("date") or (adj.before or {}).get("date"),
        "workout_title": after.get("title"), "activity_id": adj.activity_id,
        "trigger": adj.trigger, "action": adj.action, "reason": adj.reason,
        "chip": adj.chip, "signals": adj.signals or [], "before": short(adj.before or {}),
        "after": short(after), "group": adj.group or None, "status": adj.status,
        "undoable": undoable(adj, today), "created_at": adj.created_at,
        "undone_at": adj.undone_at,
    }


def current_for(workout: PlannedWorkout) -> dict | None:
    if workout.adjusted_by != AUTO:
        return None
    latest = _latest_applied(workout)
    return adjustment_json(latest) if latest else None
