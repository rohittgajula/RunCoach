"""Runs per week (R8 §A), the Django half. Rules: planning/relayout.py.

`runs_per_week_*` numbers for the athlete API, and `relayout_active_plan`, which
re-splits every fully-future week of the active plan whose run count differs from the
athlete's effective choice. Week volume (prescribed run seconds — adaptation already
included, because it was applied to these rows) and phase are kept; today, past,
completed, skipped and the race week are untouched, and so is a week holding a session
the athlete edited (R16). Rows are rewritten in place where possible so a workout that
is on the watch is re-sent rather than orphaned.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from nutrition.fueling import fueling_for
from nutrition.targets import FALLBACK_WEIGHT_KG
from planning.baseline import BEGINNER_RUN_KM_PER_WEEK
from planning.generator import effective_run_days, run_day_limit
from planning.relayout import RUN_KINDS, WeekVolume, relayout_week
from planning.workouts import build_workout

from .adaptation import _walk_seconds, run_seconds
from .garmin_sync import forget_on_garmin, resync_on_garmin
from .models import INACTIVE_STATUSES, PlannedWorkout, TrainingPlan
from .plan_services import config_from_settings

REASON = "runs per week changed"
KEEP_RECORDS = 20


def _active(athlete):
    return TrainingPlan.objects.filter(athlete=athlete,
                                       status=TrainingPlan.Status.ACTIVE).first()


def recommended_runs(athlete, plan=None) -> int:
    """The coach default: run_day_limit on the active plan's baseline, else the profile's."""
    config = config_from_settings()
    plan = plan if plan is not None else _active(athlete)
    km = (((plan.summary or {}).get("baseline") or {}).get("run_km_per_week")
          if plan is not None else None)
    if km is None:
        from .plan_services import history_baseline

        history = history_baseline(athlete)
        km = (history.run_km_per_week if history.source == "history"
              else BEGINNER_RUN_KM_PER_WEEK)
    return run_day_limit(float(km), config)


def effective_runs(athlete, plan=None) -> int:
    return effective_run_days(athlete.runs_per_week, recommended_runs(athlete, plan),
                              athlete.training_days_per_week)


def _longest_run(workout) -> float | None:
    return max((float(s.get("duration_s") or 0) for s in workout.steps or []
                if s.get("kind") == "run"), default=None) or None


def _pair(sessions, rows):
    """Match new sessions to old rows so a row keeps its identity where it can.

    Kind is matched across the WHOLE week before any row is reused for a different
    kind: a greedy single pass let an earlier easy session take the long run's row,
    so the (unchanged) long run lost its watch copy and a different session was sent
    under its id. Passes: same kind and date, then same kind (nearest date), then any
    leftover row (nearest date). Returns ([(session, row | None)], spare rows).
    """
    free = list(rows)
    matched: dict[int, PlannedWorkout] = {}

    def assign(fits):
        for i, session in enumerate(sessions):
            if i in matched:
                continue
            candidates = [r for r in free if fits(r, session)]
            if candidates:
                row = min(candidates, key=lambda r: (abs((r.date - session.date).days), r.pk))
                free.remove(row)
                matched[i] = row

    assign(lambda r, s: r.kind == s.kind and r.date == s.date)
    assign(lambda r, s: r.kind == s.kind)
    assign(lambda r, s: True)
    return [(s, matched.get(i)) for i, s in enumerate(sessions)], free


def _write(athlete, plan, row, session, gphase, phase, bands):
    spec = build_workout(session, bands, gphase)
    row = row or PlannedWorkout(athlete=athlete, plan=plan)
    row.date, row.phase, row.moved_from = session.date, phase, None
    row.title, row.kind, row.duration_s = spec.title[:120], spec.kind, spec.duration_s
    row.load, row.steps = spec.load, [s.as_dict() for s in spec.steps]
    row.description, row.purpose, row.target_zone = spec.description, spec.purpose, \
        spec.target_zone
    row.fueling = fueling_for(spec.kind, spec.duration_s,
                              athlete.weight_kg or FALLBACK_WEIGHT_KG).as_dict()
    row.adjusted_by, row.original_steps, row.original = "", None, None
    row.save()
    return row


def _phase_for(phases, day: dt.date):
    return next((p for p in phases if p.start <= day <= p.end), None)


@transaction.atomic
def relayout_active_plan(athlete) -> dict | None:
    """Re-split future weeks whose run count differs from the effective runs per week.

    Returns {moved, dropped, watch_updated, watch_removed, regenerated, notes} or None
    when there is no active plan or no week had to change.
    """
    from .plan_store import bands_for

    plan = (TrainingPlan.objects.select_for_update(of=("self",))
            .filter(athlete=athlete, status=TrainingPlan.Status.ACTIVE)
            .select_related("race").first())
    phases = list(plan.phases.all()) if plan else []
    if plan is None or not phases:
        return None
    today, start = athlete.local_today, phases[0].start
    last_date = plan.race.date - dt.timedelta(days=1) if plan.race else None
    runs = effective_runs(athlete, plan)
    config, bands = config_from_settings(), bands_for(athlete)

    weeks = defaultdict(list)
    for w in plan.workouts.exclude(status__in=INACTIVE_STATUSES).select_related("phase"):
        weeks[(w.date - start).days // 7].append(w)

    regenerated, notes, changed, doomed = 0, [], [], []
    for index in sorted(weeks):
        rows, week_start = weeks[index], start + dt.timedelta(days=7 * index)
        if week_start <= today or any(
                w.kind == "RACE" or w.status != PlannedWorkout.Status.PLANNED for w in rows):
            continue
        run_rows = sorted((w for w in rows if w.kind in RUN_KINDS), key=lambda w: (w.date, w.pk))
        if not run_rows:
            continue
        if any(w.edited_by == "user" for w in rows):
            # R16: a week holding a session the athlete edited keeps its layout — the
            # edited session's content and date stay exactly as they made them.
            if len(run_rows) != runs:
                notes.append(f"The week of {week_start:%-d %b} kept its sessions: it has "
                             "a session you edited.")
            continue
        long_row = next((w for w in run_rows if w.kind == "LONG"), None)
        phase_obj = next((w.phase for w in run_rows if w.phase), None)
        gphase = phase_obj.generator_phase if phase_obj else "FOUNDATION"
        volume = WeekVolume(
            start=week_start, phase=gphase, run_s=sum(run_seconds(w) for w in run_rows),
            walk_s=sum(_walk_seconds(w) for w in run_rows),
            long_continuous_s=_longest_run(long_row) if long_row else None,
        )
        sessions, week_notes = relayout_week(
            volume, available_days=athlete.available_days or {},
            long_run_day=athlete.long_run_day, runs=runs, config=config, last_date=last_date)
        notes += week_notes
        if not sessions or len(sessions) == len(run_rows):
            continue
        pairs, spare = _pair(sessions, run_rows)
        new_dates = {s.date for s in sessions}
        doomed += spare + [w for w in rows if w.kind not in RUN_KINDS and w.date in new_dates]
        for session, row in pairs:
            kept = _write(athlete, plan, row, session, gphase,
                          _phase_for(phases, session.date) or phase_obj, bands)
            changed.append(kept.pk)
        regenerated += len(sessions)

    if not regenerated and not notes:
        return None
    watch_removed = forget_on_garmin(athlete, doomed)
    PlannedWorkout.objects.filter(athlete=athlete, pk__in=[w.pk for w in doomed]).delete()
    watch_updated = resync_on_garmin(athlete, changed)
    record = {"moved": 0, "dropped": len(doomed), "watch_updated": watch_updated,
              "watch_removed": watch_removed, "regenerated": regenerated, "notes": notes}
    summary = dict(plan.summary or {})
    summary["runs_per_week"] = runs
    summary["reflows"] = [*summary.get("reflows", []), {
        **record, "reason": REASON, "at": timezone.now().isoformat(),
        "runs_per_week": athlete.runs_per_week, "effective": runs,
    }][-KEEP_RECORDS:]
    plan.summary = summary
    plan.save(update_fields=["summary"])
    return record
