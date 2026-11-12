"""Persisted plans: propose, accept, decline, and link what was actually done.

The generator stays the only thing that decides dates and volumes. This module turns
its output into rows — merging its weeks into phases and its sessions into structured
workouts — and owns the one invariant that matters at accept time: **at most one
active plan per athlete**, with the previous plan's future workouts removed so the
calendar never shows two prescriptions for one day.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging

from django.db import transaction
from django.utils import timezone

from apps.athletes.models import Athlete
from nutrition.fueling import fueling_for
from nutrition.targets import FALLBACK_WEIGHT_KG
from planning.generator import generate_plan
from planning.workouts import Bands, build_workout

from .models import PlannedWorkout, PlanPhase, Race, TrainingPlan
from .plan_services import baseline_for, config_from_settings, history_baseline

logger = logging.getLogger(__name__)

# Bump when the materialisation (not the generator) changes shape, so stored plans
# can be told apart from ones built by newer code.
GENERATOR_VERSION = "g1"

# Generator phase -> PlanPhase.kind (the colour on the pill). Coarser on purpose:
# the athlete sees Base / Build / Peak / Taper, not the generator's internal labels.
PHASE_KIND = {
    "BASE": "base",
    "FOUNDATION": "base",
    "AEROBIC": "build",
    "SPECIFIC": "build",
    "PEAK": "peak",
    "TAPER": "taper",
    "RACE": "race",
}

# Deterministic fallback names and descriptions, used whenever the model does not
# supply valid ones. A plan must never depend on a model being available.
PHASE_TEXT = {
    "BASE": ("Steady base", "Hold your current volume steady. The ramp starts later — "
             "there is more runway than this distance needs."),
    "FOUNDATION": ("Foundation", "Easy run/walk sessions that build the habit and the "
                   "tendons before the running gets longer."),
    "AEROBIC": ("Aerobic build", "More continuous running at an easy effort, plus one "
                "short controlled hard session a week."),
    "SPECIFIC": ("Race-specific build", "The long run grows towards race distance; the "
                 "hard sessions get more specific to race effort."),
    "PEAK": ("Peak", "The highest-volume weeks. Sleep and fuel matter most here."),
    "TAPER": ("Taper", "Less volume, same rhythm. You keep the fitness and shed the "
              "fatigue."),
    "RACE": ("Race week", "Short and easy until race day. Nothing new."),
}

# Starting weekly RUNNING distance for an athlete with no history at all. Roughly a
# couch-to-5K first week once the walking that rides along is added. Lives in the pure
# planning.baseline module so the detraining floor and this default are one number.
from planning.baseline import BEGINNER_RUN_KM_PER_WEEK  # noqa: E402


class PlanError(ValueError):
    """The request cannot produce a plan (race in the past, bad inputs)."""


def bands_for(athlete: Athlete) -> Bands:
    """Pace and heart-rate bands for each intensity.

    Easy pace is the athlete's own stored band. Harder paces come from threshold pace
    when it is known; otherwise they are offsets from the easy band — deliberately
    modest ones, because a beginner's prescribed "hard" pace being too fast is the
    more harmful error. HR bands come from Karvonen zones when the data supports
    them; without zones there is no hard HR band at all rather than a formula guess.
    """
    easy = (athlete.easy_pace_min, athlete.easy_pace_max)
    threshold = athlete.threshold_pace_s
    if threshold:
        moderate = (threshold + 5, threshold + 20)
        hard = (threshold - 15, threshold)
    else:
        moderate = (athlete.easy_pace_min - 75, athlete.easy_pace_min - 45)
        hard = (athlete.easy_pace_min - 120, athlete.easy_pace_min - 90)

    zones = athlete.zones()
    if zones:
        z2, z3, z4 = zones.band("Z2"), zones.band("Z3"), zones.band("Z4")
        hr_easy, hr_moderate, hr_hard = (z2.low, z2.high), (z3.low, z3.high), (z4.low, z4.high)
    else:
        hr_easy = (athlete.hr_easy_min, athlete.hr_easy_max)
        hr_moderate = (athlete.hr_easy_max, athlete.hr_ceiling)
        hr_hard = None
    return Bands(
        easy_pace=easy, moderate_pace=moderate, hard_pace=hard,
        hr_easy=hr_easy, hr_moderate=hr_moderate, hr_hard=hr_hard,
    )


def _normalise_days(available_days) -> dict | None:
    """Accept {"0": bool..} or a list of weekday ints (what a model naturally sends)."""
    if available_days is None:
        return None
    if isinstance(available_days, dict):
        days = {str(d): bool(available_days.get(str(d), False)) for d in range(7)}
    else:
        chosen = {int(d) for d in available_days if 0 <= int(d) <= 6}
        days = {str(d): d in chosen for d in range(7)}
    if not any(days.values()):
        raise PlanError("Pick at least one day you can train.")
    return days


def _merge_phases(plan, race_date: dt.date) -> list[dict]:
    """Consecutive weeks with the same generator phase become one phase."""
    merged: list[dict] = []
    for week in plan.weeks:
        week_end = min(week.start_date + dt.timedelta(days=6), race_date)
        if merged and merged[-1]["generator_phase"] == week.phase:
            merged[-1]["end"] = week_end
            merged[-1]["weeks"] += 1
        else:
            merged.append({
                "generator_phase": week.phase, "start": week.start_date,
                "end": week_end, "weeks": 1,
            })
    return merged


def _phase_texts(merged: list[dict], supplied) -> list[tuple[str, str]]:
    """The model's names/descriptions if valid, else the deterministic fallbacks.

    Valid means one entry per phase, each with a non-empty name. The model can only
    ever rename — dates, order and count are fixed before it is consulted.
    """
    fallback = [PHASE_TEXT[p["generator_phase"]] for p in merged]
    if not supplied or len(supplied) != len(merged):
        return fallback
    texts = []
    for entry, default in zip(supplied, fallback):
        name = str((entry or {}).get("name") or "").strip()[:80]
        description = str((entry or {}).get("description") or "").strip()[:600]
        if not name:
            return fallback
        texts.append((name, description or default[1]))
    return texts


@transaction.atomic
def propose_plan(
    athlete: Athlete,
    *,
    race_name: str,
    race_date: dt.date,
    distance_km: float,
    is_target: bool = True,
    available_days=None,
    long_run_day: int | None = None,
    phase_names_and_descriptions: list[dict] | None = None,
    chat_message=None,
) -> TrainingPlan:
    """Run the generator and save a `proposed` plan with phases and workouts.

    Nothing about the athlete's current calendar changes until `accept_plan`. The race
    row is created if it does not exist (so the proposal card can show it), but it is
    only made the target on accept.
    """
    today = athlete.local_today
    start = today + dt.timedelta(days=1)       # "Starts tomorrow"
    if race_date <= start:
        raise PlanError("The race must be at least two days away to build a plan.")
    if not 1 <= float(distance_km) <= 100:
        raise PlanError("Race distance must be between 1 and 100 km.")

    days = _normalise_days(available_days)
    history = history_baseline(athlete)
    baseline = baseline_for(athlete)
    beginner = history.source != "history"
    if beginner:
        # No segmented running at all (a new account, or no Garmin yet). baseline_for's
        # 1 km/week floor is a guard against division by zero, not a plan: it produced
        # four-minute sessions. Start from a conservative couch-to-5K-like week instead,
        # at the athlete's own easy pace rather than the generic 8:00/km.
        baseline = dataclasses.replace(
            baseline,
            run_km_per_week=max(baseline.run_km_per_week, BEGINNER_RUN_KM_PER_WEEK),
            run_pace_s_per_km=(athlete.easy_pace_min + athlete.easy_pace_max) / 2,
        )
    if days is not None:
        baseline = dataclasses.replace(baseline, available_days=days)
    if long_run_day is not None:
        baseline = dataclasses.replace(baseline, long_run_day=int(long_run_day))
    if not baseline.available_days.get(str(baseline.long_run_day), False):
        # Mirror the profile validation: the long run must be on a training day. Fall
        # back to the last available day rather than refusing a whole plan over it.
        available = [d for d in range(7) if baseline.available_days.get(str(d))]
        baseline = dataclasses.replace(baseline, long_run_day=available[-1] if available else 6)

    if athlete.runs_per_week:
        baseline = dataclasses.replace(baseline, runs_per_week=int(athlete.runs_per_week))
    generated = generate_plan(
        plan_start=start, race_date=race_date, race_km=float(distance_km),
        baseline=baseline, config=config_from_settings(),
    )

    race = Race.objects.filter(athlete=athlete, date=race_date).first()
    race_created = race is None
    if race is None:
        has_target = Race.objects.filter(athlete=athlete, is_target=True).exists()
        race = Race.objects.create(
            athlete=athlete, name=race_name[:120], date=race_date,
            distance_km=float(distance_km), is_target=bool(is_target) and not has_target,
        )

    plan = TrainingPlan.objects.create(
        athlete=athlete,
        race=race,
        name=f"{float(distance_km):g} km plan — {race.name}"[:160],
        goal=(
            f"Finish {race.name} ({float(distance_km):g} km) on {race_date:%-d %b %Y}"
            + ("" if generated.will_run_continuously else " — expect to run/walk it")
            + "."
        ),
        status=TrainingPlan.Status.PROPOSED,
        generator_version=GENERATOR_VERSION,
        chat_message=chat_message,
        summary={
            "runway": generated.runway,
            "weeks": generated.weeks_available,
            "peak_run_km": generated.peak_run_km,
            "ideal_peak_run_km": generated.ideal_peak_run_km,
            "reached_ideal_peak": generated.reached_ideal_peak,
            "peak_continuous_s": generated.peak_continuous_s,
            "race_needs_continuous_s": generated.race_needs_continuous_s,
            "will_run_continuously": generated.will_run_continuously,
            "warnings": (
                ["No running history yet, so this starts from beginner defaults "
                 f"({BEGINNER_RUN_KM_PER_WEEK:g} km of running a week, mostly run/walk). "
                 "It adapts once your runs sync."] if beginner else []
            ) + ([history.warning] if history.warning else []) + generated.warnings,
            "baseline_source": "beginner_defaults" if beginner else "history",
            "last_run_date": history.last_run_date.isoformat() if history.last_run_date else None,
            "gap_days": history.gap_days,
            "detraining_factor": history.detraining_factor,
            "best_week": {
                "start": history.best_week_start.isoformat(),
                "run_km": history.best_week_km,
                "longest_run_s": round(history.best_longest_run_s),
            } if history.best_week_start else None,
            "is_target": bool(is_target),
            "race_created": race_created,
            "available_days": baseline.available_days,
            "long_run_day": baseline.long_run_day,
            "runs_per_week": athlete.runs_per_week,
            "notes": generated.notes,
            "baseline": {
                "run_km_per_week": round(baseline.run_km_per_week, 1),
                "longest_run_s": round(baseline.longest_run_s),
                "run_pace_s_per_km": round(baseline.run_pace_s_per_km),
            },
        },
    )

    merged = _merge_phases(generated, race_date)
    texts = _phase_texts(merged, phase_names_and_descriptions)
    phases: list[PlanPhase] = []
    for order, (block, (name, description)) in enumerate(zip(merged, texts)):
        phases.append(PlanPhase.objects.create(
            plan=plan, order=order, name=name, description=description,
            kind=PHASE_KIND[block["generator_phase"]],
            generator_phase=block["generator_phase"],
            start=block["start"], end=block["end"],
        ))

    bands = bands_for(athlete)
    weight = athlete.weight_kg or FALLBACK_WEIGHT_KG
    rows: list[PlannedWorkout] = []
    for week, phase in _weeks_with_phases(generated.weeks, phases):
        for session in week.sessions:
            if session.optional:
                continue
            date = race_date if session.kind == "RACE" else session.date
            # The generator puts race week's race on the long-run weekday; the race
            # is on its own date, and nothing else is prescribed on or after it.
            if session.kind != "RACE" and date >= race_date:
                continue
            if date < start:
                continue
            spec = build_workout(
                session, bands, week.phase,
                race_name=race.name, race_km=float(distance_km),
                race_pace_s_per_km=baseline.run_pace_s_per_km,
            )
            rows.append(PlannedWorkout(
                athlete=athlete, plan=plan, phase=phase, date=date,
                title=spec.title[:120], kind=spec.kind, duration_s=spec.duration_s,
                load=spec.load, steps=[s.as_dict() for s in spec.steps],
                description=spec.description, purpose=spec.purpose,
                target_zone=spec.target_zone,
                fueling=fueling_for(spec.kind, spec.duration_s, weight).as_dict(),
            ))
    PlannedWorkout.objects.bulk_create(rows)
    return plan


def _weeks_with_phases(weeks, phases: list[PlanPhase]):
    """Pair each generator week with the merged phase that contains it."""
    by_start = sorted(phases, key=lambda p: p.start)
    for week in weeks:
        phase = next((p for p in by_start if p.start <= week.start_date <= p.end), None)
        yield week, phase


@transaction.atomic
def accept_plan(plan: TrainingPlan) -> TrainingPlan:
    """Make this the active plan. Archives the previous one and deletes its future,
    not-completed workouts; today's is kept, because the athlete may be mid-session."""
    plan = TrainingPlan.objects.select_for_update().get(pk=plan.pk)
    if plan.status == TrainingPlan.Status.ACTIVE:
        return plan
    if plan.status != TrainingPlan.Status.PROPOSED:
        raise PlanError(f"Only a proposed plan can be accepted (this one is {plan.status}).")

    athlete = plan.athlete
    today = athlete.local_today
    for previous in TrainingPlan.objects.select_for_update().filter(
        athlete=athlete, status=TrainingPlan.Status.ACTIVE
    ):
        doomed = previous.workouts.filter(date__gt=today, status=PlannedWorkout.Status.PLANNED)
        _forget_on_garmin(athlete, doomed)
        doomed.delete()
        previous.status = TrainingPlan.Status.ARCHIVED
        previous.save(update_fields=["status"])

    # A proposal accepted days later must not show its first days as missed.
    plan.workouts.filter(date__lt=today, status=PlannedWorkout.Status.PLANNED).delete()

    plan.status = TrainingPlan.Status.ACTIVE
    plan.accepted_at = timezone.now()
    plan.save(update_fields=["status", "accepted_at"])

    summary = plan.summary or {}
    if plan.race and summary.get("is_target"):
        Race.objects.filter(athlete=athlete, is_target=True).exclude(pk=plan.race.pk).update(
            is_target=False
        )
        if not plan.race.is_target:
            plan.race.is_target = True
            plan.race.save(update_fields=["is_target"])

    # The availability the plan was built on becomes the profile's, so the next plan
    # (and the readiness layer) agree with the calendar the athlete just accepted.
    changed = []
    if summary.get("available_days") and summary["available_days"] != athlete.available_days:
        athlete.available_days = summary["available_days"]
        changed.append("available_days")
    if summary.get("long_run_day") is not None and summary["long_run_day"] != athlete.long_run_day:
        athlete.long_run_day = summary["long_run_day"]
        changed.append("long_run_day")
    if changed:
        athlete.save(update_fields=changed + ["updated_at"])

    from apps.activities.models import Activity

    for activity in Activity.objects.filter(athlete=athlete, local_date=today):
        link_activity(activity)
    # R13 §4: the new plan's strength sessions (none unless the athlete chose them).
    if athlete.strength_per_week:
        from .strength_service import place_for

        place_for(athlete)
    return plan


@transaction.atomic
def decline_plan(plan: TrainingPlan) -> TrainingPlan:
    if plan.status != TrainingPlan.Status.PROPOSED:
        raise PlanError(f"Only a proposed plan can be declined (this one is {plan.status}).")
    plan.status = TrainingPlan.Status.DECLINED
    plan.save(update_fields=["status"])
    plan.workouts.all().delete()
    race = plan.race
    # A race the proposal created and nothing else uses goes with it, so declining
    # leaves the calendar exactly as it was.
    if (
        race and (plan.summary or {}).get("race_created")
        and not race.plans.exclude(pk=plan.pk).exists()
    ):
        plan.race = None
        plan.save(update_fields=["race"])
        race.delete()
    return plan


def link_activity(activity) -> PlannedWorkout | None:
    """A synced run on a day with a planned workout completes it.

    Only running sports link: a walk on an interval day did not complete the intervals.
    """
    if "run" not in (activity.sport or "").lower():
        return None
    if PlannedWorkout.objects.filter(completed_activity=activity).exists():
        return None
    workout = (
        PlannedWorkout.objects.filter(
            athlete_id=activity.athlete_id, date=activity.local_date,
            status=PlannedWorkout.Status.PLANNED, completed_activity__isnull=True,
            plan__status=TrainingPlan.Status.ACTIVE,
        ).order_by("id").first()
    )
    if workout is None:
        return None
    workout.status = PlannedWorkout.Status.COMPLETED
    workout.completed_activity = activity
    workout.save(update_fields=["status", "completed_activity"])
    return workout


def current_phase(plan: TrainingPlan, today: dt.date) -> PlanPhase | None:
    """The phase containing today; the first phase if the plan has not started."""
    phases = list(plan.phases.all())
    for phase in phases:
        if phase.start <= today <= phase.end:
            return phase
    if phases and today < phases[0].start:
        return phases[0]
    return None


def plan_weeks(plan: TrainingPlan) -> list[dict]:
    """Seven-day blocks from the plan start, with planned minutes and load."""
    phases = list(plan.phases.all())
    if not phases:
        return []
    start = phases[0].start
    end = phases[-1].end
    totals: dict[int, list[float]] = {}
    for workout in plan.workouts.all():
        index = (workout.date - start).days // 7
        bucket = totals.setdefault(index, [0.0, 0.0])
        bucket[0] += workout.duration_s / 60
        bucket[1] += workout.load

    weeks = []
    index = 0
    week_start = start
    while week_start <= end:
        week_end = min(week_start + dt.timedelta(days=6), end)
        phase = next((p for p in phases if p.start <= week_start <= p.end), None)
        minutes, load = totals.get(index, [0.0, 0.0])
        weeks.append({
            "start": week_start, "end": week_end,
            "planned_minutes": round(minutes), "planned_load": round(load, 1),
            "phase_id": phase.pk if phase else None,
        })
        index += 1
        week_start += dt.timedelta(days=7)
    return weeks


def _forget_on_garmin(athlete: Athlete, workouts) -> None:
    """Queue removal of the Garmin copies of workouts about to be deleted — after the
    transaction commits, so a rolled-back accept never deletes anything remote."""
    from .garmin_sync import forget_on_garmin

    forget_on_garmin(athlete, workouts.exclude(garmin_workout_id__isnull=True))


@transaction.atomic
def rebuild_active_plan(athlete: Athlete) -> TrainingPlan:
    """Regenerate the active plan for the same race from the athlete's CURRENT profile
    (training days, long-run day) and history, and make it active.

    New training days no longer need this — saving them re-flows the plan
    (apps.planning.reflow) — and the UI no longer offers it; kept for the API.
    Completed workouts stay attached to the archived plan; future ones are replaced.
    """
    active = (
        TrainingPlan.objects.select_for_update(of=("self",))
        .filter(athlete=athlete, status=TrainingPlan.Status.ACTIVE)
        .select_related("race").first()
    )
    if active is None:
        raise PlanError("There is no active plan to rebuild.")
    if active.race is None or active.race.date <= athlete.local_today:
        raise PlanError("The active plan's race has passed — ask the coach for a new plan.")
    race = active.race
    proposal = propose_plan(
        athlete, race_name=race.name, race_date=race.date,
        distance_km=race.distance_km, is_target=race.is_target,
    )
    return accept_plan(proposal)


# --- practice plans (R19) -----------------------------------------------------


PRACTICE_PHASE_NAMES: dict[str, tuple[str, str]] = {
    "FOUNDATION": ("Getting going again",
                   "Short, frequent, easy. The aim is consistency and letting the "
                   "tendons catch up with the enthusiasm."),
    "AEROBIC": ("Building the base",
                "The long run's unbroken block grows week by week. This is the "
                "phase that moves the number you are actually chasing."),
}



def _all_time_longest_run_s(athlete: Athlete) -> float:
    """The longest unbroken block this athlete has ever recorded.

    Deliberately unbounded in time. Every other figure in a baseline is recent
    on purpose — fitness decays and a plan built on last spring would start
    above the athlete. This one is the exception: it is not a claim about
    current fitness, it is a record of what the body has done before, and that
    does not expire. The decay is applied separately, by longest_run_s.
    """
    from django.db.models import Max

    from apps.activities.models import ActivityMetrics

    return ActivityMetrics.objects.filter(
        activity__athlete=athlete,
    ).aggregate(best=Max("longest_run_s"))["best"] or 0.0


def _practice_baseline(athlete: Athlete, available_days, long_run_day):
    """The baseline both no-race modes start from.

    Shared because the two differ only in what they build toward: how the
    athlete's history becomes a starting point is the same question either way,
    and two copies of it would drift the first time one was corrected.
    """
    history = history_baseline(athlete)
    baseline = baseline_for(athlete)
    if history.source != "history":
        baseline = dataclasses.replace(
            baseline,
            run_km_per_week=max(baseline.run_km_per_week, BEGINNER_RUN_KM_PER_WEEK),
            run_pace_s_per_km=(athlete.easy_pace_min + athlete.easy_pace_max) / 2,
        )
    # The best unbroken block EVER recorded, which is the whole input the regain
    # rate runs on.
    #
    # This was wired to history.best_longest_run_s, which is scoped to the recent
    # window history_baseline looks at — for Rohit it returned 392 s, exactly his
    # current block, so demonstrated == current and the regain branch could never
    # fire. The number it was meant to carry is 837 s, from 20 August. The
    # consequence was silent and large: a plan quoting Christmas Day for a
    # milestone he can reach in a fortnight, because it was treating ground he
    # had already held as new.
    baseline = dataclasses.replace(
        baseline,
        demonstrated_longest_s=max(
            float(_all_time_longest_run_s(athlete)),
            float(history.best_longest_run_s or 0.0),
            baseline.longest_run_s,
        ),
    )
    days = _normalise_days(available_days)
    if days is not None:
        baseline = dataclasses.replace(baseline, available_days=days)
    if long_run_day is not None:
        baseline = dataclasses.replace(baseline, long_run_day=int(long_run_day))
    if not baseline.available_days.get(str(baseline.long_run_day), False):
        open_days = [d for d in range(7) if baseline.available_days.get(str(d))]
        baseline = dataclasses.replace(
            baseline, long_run_day=open_days[-1] if open_days else 6,
        )
    if athlete.runs_per_week:
        baseline = dataclasses.replace(baseline, runs_per_week=int(athlete.runs_per_week))
    return baseline


def _persist_practice(athlete, plan, generated, baseline, start, horizon_end):
    """Phases and workouts for a plan with no race in it."""
    merged = _merge_phases(generated, horizon_end)
    phases: list[PlanPhase] = []
    for order, block in enumerate(merged):
        name, description = PRACTICE_PHASE_NAMES.get(
            block["generator_phase"], (block["generator_phase"].title(), ""),
        )
        phases.append(PlanPhase.objects.create(
            plan=plan, order=order, name=name, description=description,
            kind=PHASE_KIND[block["generator_phase"]],
            generator_phase=block["generator_phase"],
            start=block["start"], end=block["end"],
        ))

    bands = bands_for(athlete)
    weight = athlete.weight_kg or FALLBACK_WEIGHT_KG
    rows: list[PlannedWorkout] = []
    for week, phase in _weeks_with_phases(generated.weeks, phases):
        for session in week.sessions:
            if session.optional or session.kind == "RACE" or session.date < start:
                continue
            spec = build_workout(session, bands, week.phase)
            rows.append(PlannedWorkout(
                athlete=athlete, plan=plan, phase=phase, date=session.date,
                title=spec.title[:120], kind=spec.kind, duration_s=spec.duration_s,
                load=spec.load, steps=[s.as_dict() for s in spec.steps],
                description=spec.description, purpose=spec.purpose,
                target_zone=spec.target_zone,
                fueling=fueling_for(spec.kind, spec.duration_s, weight).as_dict(),
            ))
    PlannedWorkout.objects.bulk_create(rows)
    return plan


@transaction.atomic
def propose_goal_plan(
    athlete: Athlete,
    *,
    target_distance_km: float,
    target_date: dt.date,
    available_days=None,
    long_run_day: int | None = None,
    chat_message=None,
) -> TrainingPlan:
    """A dated goal with no race: "5 km without stopping, by June".

    Between the two existing modes. A race plan needs an event; a practice plan
    has no deadline. This has a date the athlete chose and nothing else a race
    brings — no taper, no race week, no entry.

    The one thing it does that a race plan does not is refuse. A race date is a
    fact, so a plan to it is built and warned about; a self-set date is a wish,
    and the useful answer to an impossible wish is the possible one beside it.
    The plan is still built either way, because the training is the same
    training — only the date in the goal changes.
    """
    from planning.practice import generate_goal

    today = athlete.local_today
    start = today + dt.timedelta(days=1)
    if target_date <= start:
        raise PlanError("Pick a date at least two days away.")
    if not 0.4 <= float(target_distance_km) <= 100:
        raise PlanError("The distance must be between 0.4 and 100 km.")

    baseline = _practice_baseline(athlete, available_days, long_run_day)
    generated, verdict = generate_goal(
        start, target_date, float(target_distance_km), baseline, config_from_settings(),
    )

    when = (
        f"by {target_date:%-d %b %Y}" if verdict.achievable
        else f"— realistically {verdict.earliest_date:%-d %b %Y}"
        if verdict.earliest_date else "— date to be revisited"
    )
    plan = TrainingPlan.objects.create(
        athlete=athlete,
        race=None,
        name=f"{float(target_distance_km):g} km without stopping"[:160],
        goal=f"Run {float(target_distance_km):g} km without stopping {when}.",
        status=TrainingPlan.Status.PROPOSED,
        generator_version=GENERATOR_VERSION,
        chat_message=chat_message,
        summary={
            "kind": "goal",
            "weeks": generated.weeks_available,
            "peak_run_km": generated.peak_run_km,
            "peak_continuous_s": generated.peak_continuous_s,
            "target_distance_km": float(target_distance_km),
            "target_date": target_date.isoformat(),
            "achievable": verdict.achievable,
            "needs_continuous_s": verdict.needs_s,
            "reaches_continuous_s": verdict.reaches_s,
            "earliest_date": verdict.earliest_date.isoformat() if verdict.earliest_date else None,
            "warnings": generated.warnings,
            "available_days": baseline.available_days,
            "long_run_day": baseline.long_run_day,
        },
    )
    _persist_practice(athlete, plan, generated, baseline, start,
                      start + dt.timedelta(days=generated.weeks_available * 7))
    return plan


@transaction.atomic
def propose_practice_plan(
    athlete: Athlete,
    *,
    available_days=None,
    long_run_day: int | None = None,
    weeks: int | None = None,
    chat_message=None,
) -> TrainingPlan:
    """A plan with no race, built toward the next milestone.

    Everything `propose_plan` does except the race: no Race row is created, no
    taper, no race week, and the thing the plan is measured against is the next
    unbroken block rather than a date. Accepting it uses the same `accept_plan`,
    so it archives the old plan and clears its future exactly as a race plan does
    — which is what removes the phantom 11 January race week.
    """
    from planning.practice import HORIZON_WEEKS, generate_practice, milestone_for

    today = athlete.local_today
    start = today + dt.timedelta(days=1)
    horizon = max(4, min(int(weeks or HORIZON_WEEKS), 26))
    history = history_baseline(athlete)
    beginner = history.source != "history"
    baseline = _practice_baseline(athlete, available_days, long_run_day)

    generated = generate_practice(start, baseline, config_from_settings(), weeks=horizon)
    milestone = milestone_for(baseline.longest_run_s, baseline.run_pace_s_per_km)

    plan = TrainingPlan.objects.create(
        athlete=athlete,
        race=None,
        name=f"Practice block — {milestone.label}"[:160],
        goal=(
            f"Build toward running {milestone.label} without stopping "
            f"(about {milestone.distance_m / 1000:.1f} km at your pace). "
            "No race, no date to miss."
        ),
        status=TrainingPlan.Status.PROPOSED,
        generator_version=GENERATOR_VERSION,
        chat_message=chat_message,
        summary={
            "kind": "practice",
            "weeks": generated.weeks_available,
            "peak_run_km": generated.peak_run_km,
            "ideal_peak_run_km": generated.ideal_peak_run_km,
            "peak_continuous_s": generated.peak_continuous_s,
            "milestone_s": milestone.seconds,
            "milestone_label": milestone.label,
            "milestone_distance_m": round(milestone.distance_m),
            "milestone_index": milestone.index,
            "milestone_total": milestone.total,
            "warnings": (
                ["No running history yet, so this starts from beginner defaults. "
                 "It adapts once your runs sync."] if beginner else []
            ) + ([history.warning] if history.warning else []) + generated.warnings,
            "baseline_source": "beginner_defaults" if beginner else "history",
            "gap_days": history.gap_days,
            "detraining_factor": history.detraining_factor,
            "available_days": baseline.available_days,
            "long_run_day": baseline.long_run_day,
            "runs_per_week": athlete.runs_per_week,
            "baseline": {
                "run_km_per_week": round(baseline.run_km_per_week, 1),
                "longest_run_s": round(baseline.longest_run_s),
                "demonstrated_longest_s": round(baseline.demonstrated_longest_s),
                "run_pace_s_per_km": round(baseline.run_pace_s_per_km),
            },
        },
    )

    _persist_practice(athlete, plan, generated, baseline, start,
                      start + dt.timedelta(days=horizon * 7))
    return plan
