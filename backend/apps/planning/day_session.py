"""Putting your own session on a day the plan had nothing on.

Rohit: "in calender i should be able to select any date even it its a run/gym
or non-training day and there i should be able to create a plan either for run
or gym either manually or using ai".

Until now the calendar was read-only in one direction: the coach wrote days and
you could move, edit or skip what it wrote, but you could not *add* a day. A
rest day was a day with nothing to tap. That is the wrong shape for somebody
whose training is their own — plans are a suggestion, and Tuesday evenings free
up.

Three rules shape this module.

**A session you added is yours, and nothing automatic may remove it.** Every
layout pass here deletes what it did not place: accepting a plan deletes the
previous plan's future sessions, and the gym re-layout drops sessions off days
it no longer wants. Both would quietly eat a session the athlete put down on
purpose. They are marked `created_by="user"` and both passes now leave them
alone — the same rule that keeps `edited_by` edits through a re-layout.

**The AI writes steps, and the same validator checks them.** A described
session goes through `planning.edit.expand`, which is the validator the manual
editor uses: step durations, the total, heart-rate bands against the athlete's
own limits. A model that returns a 9-hour interval gets the same refusal a
person typing it would. Nothing reaches the calendar unvalidated.

**Nothing is saved until it is accepted.** `preview` builds the session and
returns it without writing, because a described session is a guess at what you
meant and you should see it before it is on your watch.
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction

from apps.athletes.models import Athlete
from planning import edit as rules

from .models import PlannedWorkout, StrengthSession, TrainingPlan

USER = "user"

#: Presets are the manual path: a shape and a length, built by the same code
#: that writes the plan's own sessions. Deliberately few — this is "put a run
#: here", not a workout designer. The editor that already exists handles the
#: rest, which is why nothing here tries to be one.
PRESETS: dict[str, dict] = {
    "RUN_WALK": {"label": "Run/walk", "run_share": 0.55,
                 "purpose": "Aerobic volume at an easy effort, taken in run/walk blocks."},
    "EASY": {"label": "Easy run", "run_share": 0.85,
             "purpose": "Easy aerobic running. Conversational throughout."},
    "LONG": {"label": "Long run", "run_share": 0.8,
             "purpose": "Time on feet. The session that grows your longest continuous run."},
    "INTERVALS": {"label": "Intervals", "run_share": 0.7,
                  "purpose": "Controlled faster running, kept short on purpose."},
    "TEMPO": {"label": "Tempo", "run_share": 0.75,
              "purpose": "Sustained comfortably-hard effort."},
}

MIN_MINUTES = 5
MAX_MINUTES = 240


class DayError(ValueError):
    """Something the athlete can fix, phrased for them."""


def _check_date(athlete: Athlete, day: dt.date) -> None:
    """Today or later only.

    The past is the record of what happened. Writing a plan onto it would put a
    session the athlete never did into the history every future plan is built
    from — and it would show up as "missed" the moment it was saved.
    """
    if day < athlete.local_today:
        raise DayError("That day has already been. Pick today or a day ahead.")


def container_plan(athlete: Athlete) -> TrainingPlan:
    """The plan a user-added run hangs off.

    `PlannedWorkout.plan` is not nullable and a great deal of code reads
    `plan__status`, so an orphan workout would disappear from the calendar
    rather than fail loudly. The active plan is the right home when there is
    one; when there is not — the athlete cleared everything, or has never
    accepted a plan — a plain container is made so that "add a run on Tuesday"
    does not require accepting sixteen weeks of training first.
    """
    active = TrainingPlan.objects.filter(
        athlete=athlete, status=TrainingPlan.Status.ACTIVE,
    ).order_by("-created_at").first()
    if active is not None:
        return active
    return TrainingPlan.objects.create(
        athlete=athlete,
        name="Your own sessions",
        goal="Sessions you added yourself, outside any training plan.",
        status=TrainingPlan.Status.ACTIVE,
        generator_version="user",
        summary={"kind": "personal"},
    )


def _bands(athlete: Athlete):
    from .plan_store import bands_for

    return bands_for(athlete)


def build_preset(athlete: Athlete, kind: str, minutes: int) -> dict:
    """A session of this shape and this length, built the way the plan builds one.

    Routed through `planning.workouts.build_workout`, so an added easy run is
    the same object as a generated one: the athlete's own pace and heart-rate
    bands, the same warm-up and cool-down rules, the same step grid. A second
    way of writing sessions would be a second thing to keep correct.
    """
    from planning.generator import Session
    from planning.workouts import build_workout

    if kind not in PRESETS:
        raise DayError(f"Pick one of: {', '.join(p['label'] for p in PRESETS.values())}.")
    if not MIN_MINUTES <= minutes <= MAX_MINUTES:
        raise DayError(f"A session is {MIN_MINUTES}–{MAX_MINUTES} minutes.")

    share = PRESETS[kind]["run_share"]
    run_minutes = round(minutes * share)
    walk_minutes = minutes - run_minutes

    session = Session(
        date=athlete.local_today, kind=kind,
        run_minutes=run_minutes, walk_minutes=walk_minutes,
        target_run_m=0.0, purpose=PRESETS[kind]["purpose"], effort="Easy",
    )
    # AEROBIC: the steady-state phase. A one-off session has no phase of its
    # own, and borrowing the plan's would make the same request produce
    # different sessions depending on where the plan happened to be.
    spec = build_workout(session, _bands(athlete), "AEROBIC")
    return {
        "title": spec.title, "kind": spec.kind, "duration_s": spec.duration_s,
        "load": spec.load, "steps": [s.as_dict() for s in spec.steps],
        "description": spec.description, "purpose": spec.purpose,
        "target_zone": spec.target_zone,
    }


#: How far either side of the day the coach looks before writing a session.
#:
#: Rohit: "if i ask you to plan for a specific day, you need to compare that
#: days future runs and past runs couple of days and plan accordingly."
#:
#: Short on purpose. What decides whether Tuesday can be hard is Monday and
#: Wednesday, not last month — and a window wide enough to hold the whole plan
#: would bury the two days that matter in thirty that do not.
CONTEXT_DAYS_BACK = 4
CONTEXT_DAYS_FORWARD = 4


def day_context(athlete: Athlete, day: dt.date) -> dict:
    """What sits either side of this day: what was run, and what is planned.

    A session written in isolation is the thing this feature would otherwise
    get wrong. "An easy 30 minutes" is a reasonable request on any day of the
    week, and an easy 30 minutes placed the day before a long run, on the back
    of two hard days, is not the same session — it needs to be genuinely easy,
    or shorter, or somewhere else.

    Both directions, because both constrain: the days behind say what the legs
    have had, the days ahead say what they are being saved for.
    """
    from apps.activities.models import Activity

    back = day - dt.timedelta(days=CONTEXT_DAYS_BACK)
    forward = day + dt.timedelta(days=CONTEXT_DAYS_FORWARD)

    done = []
    for activity in (
        Activity.objects.filter(athlete=athlete, local_date__gte=back, local_date__lt=day)
        .select_related("metrics").order_by("local_date")
    ):
        metrics = getattr(activity, "metrics", None)
        done.append({
            "date": activity.local_date.isoformat(),
            "days_before": (day - activity.local_date).days,
            "sport": activity.sport,
            "minutes": round((activity.total_timer_s or 0) / 60),
            "run_km": round((metrics.run_distance_m or 0) / 1000, 2) if metrics else None,
            "longest_block_s": round(metrics.longest_run_s) if metrics else None,
        })

    planned = []
    for workout in PlannedWorkout.objects.filter(
        athlete=athlete, date__gte=back, date__lte=forward,
    ).exclude(status=PlannedWorkout.Status.SKIPPED).order_by("date"):
        planned.append({
            "workout_id": workout.pk,
            "date": workout.date.isoformat(),
            "offset_days": (workout.date - day).days,
            "title": workout.title,
            "kind": workout.kind,
            "minutes": round((workout.duration_s or 0) / 60),
            "is_the_day_asked_about": workout.date == day,
        })

    gym = [
        {"date": s.date.isoformat(), "offset_days": (s.date - day).days, "title": s.title}
        for s in StrengthSession.objects.filter(
            athlete=athlete, date__gte=back, date__lte=forward,
        ).exclude(status=StrengthSession.Status.SKIPPED).order_by("date")
    ]
    return {"day": day.isoformat(), "recent_runs": done,
            "planned_runs": planned, "planned_gym": gym}


def build_described(athlete: Athlete, text: str, day: dt.date) -> tuple[dict, str, list[dict]]:
    """A session from a sentence: "easy run in zone 2 for 30 min, run/walk".

    The model chooses the shape; `planning.edit.expand` decides whether it is
    allowed. That split matters — the useful thing a model does here is read
    "zone 2" and "run/walk strategy" off a sentence, and the thing it must
    never do is set a heart-rate band outside the athlete's own limits.

    The days either side go in with the sentence, so the session is written
    against the week it lands in rather than in isolation. Where that week
    cannot absorb it, the model may propose changes to OTHER days — and those
    come back as proposals, never as edits. Nothing outside the day being asked
    about is touched without the athlete saying yes to that specific day.

    Returns (session, note, changes): the note is the model's one line about
    what it understood, so the athlete can see whether it heard them.
    """
    from apps.coaching.services import describe_session

    text = " ".join((text or "").split())
    if len(text) < 3:
        raise DayError("Say what you want to do — “30 minutes easy, run/walk”.")

    described, _cached = describe_session(athlete, text, day_context(athlete, day))
    limits = rules.limits_for(athlete.resting_hr, athlete.max_hr, athlete.age)
    try:
        steps = rules.expand([_tidy(s.model_dump()) for s in described.steps], limits)
    except rules.EditError as exc:
        # The validator's message is written for a person, so it is the right
        # thing to show — "Step 3: each step must be between 10 s and 90 min"
        # tells the athlete what to ask for instead.
        raise DayError(str(exc)) from exc

    total = rules.total_s(steps)
    kind = described.kind if described.kind in PRESETS else "RUN_WALK"
    session = {
        "title": rules.retitle(described.title, total)[:120],
        "kind": kind,
        "duration_s": total,
        "load": rules.load_for(steps),
        "steps": steps,
        "description": described.description,
        "purpose": PRESETS[kind]["purpose"],
        "target_zone": described.target_zone,
    }
    return session, described.understood, _proposed_changes(athlete, day, described)


def _tidy(item: dict) -> dict:
    """Clean up the one shape a model gets wrong that is not a safety question.

    The validator stays exactly as strict as it is. This only removes a
    heart-rate range with one end filled in: "Step 1: give both ends of the
    heart-rate range" is the right message for somebody typing a step by hand
    and the wrong one for somebody who asked for an interval session. The band
    is optional and the app fills it in when absent, so half of it — which is
    less information than none of it — becomes none of it.

    Everything else the model gets wrong still fails, loudly, in the
    validator's own words.
    """
    item = dict(item)
    if isinstance(item.get("steps"), list):
        return {**item, "steps": [_tidy(s) for s in item["steps"]]}
    if bool(item.get("hr_low")) != bool(item.get("hr_high")):
        item["hr_low"] = item["hr_high"] = None
    return item


#: What a proposed change to another day may do. Deliberately a closed set,
#: and deliberately only ever gentler: a session the athlete did not ask about
#: may be made easier, moved, or dropped, and may never be made harder or
#: longer. The model is reading a clash, not re-planning the week.
CHANGE_ACTIONS = ("easier", "move", "skip")


def _proposed_changes(athlete: Athlete, day: dt.date, described) -> list[dict]:
    """The model's suggestions for OTHER days, checked against reality.

    Rohit: "if you wanna change future runs ask for a updated on specific day i
    will give you a go or no go."

    So nothing here changes anything. Every suggestion is resolved to a real
    workout the athlete owns before it is shown — a proposal naming a session
    that does not exist is worse than no proposal, because it is the one the
    athlete would say yes to without being able to check — and then shown one
    per day with its own yes or no. "Shall I move your long run" and "shall I
    shorten Thursday" are two questions, and answering one is not answering the
    other.
    """
    out: list[dict] = []
    for raw in (described.changes or [])[:4]:
        if raw.action not in CHANGE_ACTIONS:
            continue
        try:
            when = dt.date.fromisoformat(raw.date)
        except (TypeError, ValueError):
            continue
        # Only ever another day, and never the past.
        if when == day or when < athlete.local_today:
            continue
        workout = PlannedWorkout.objects.filter(
            athlete=athlete, date=when, status=PlannedWorkout.Status.PLANNED,
        ).order_by("id").first()
        if workout is None:
            continue
        minutes = None
        if raw.action == "easier":
            minutes = max(MIN_MINUTES, min(int(raw.minutes or 0), MAX_MINUTES))
            # "Easier" that is not easier is a no-op dressed as a change.
            if minutes >= round(workout.duration_s / 60):
                continue
        move_to = None
        if raw.action == "move":
            try:
                move_to = dt.date.fromisoformat(raw.move_to or "")
            except (TypeError, ValueError):
                continue
            if move_to < athlete.local_today or move_to == when:
                continue
        out.append({
            "workout_id": workout.pk,
            "date": when.isoformat(),
            "title": workout.title,
            "current_minutes": round(workout.duration_s / 60),
            "action": raw.action,
            "minutes": minutes,
            "move_to": move_to.isoformat() if move_to else None,
            "why": raw.why,
        })
    return out


@transaction.atomic
def apply_change(athlete: Athlete, change: dict) -> dict:
    """Carry out ONE approved change, on one day.

    Routed through the services that already do these things — the editor, the
    move, the skip — so an approved change is the same operation the athlete
    could have done by hand, with the same validation, the same undo and the
    same watch sync. A second path to "make Thursday shorter" would be a second
    thing to keep correct.
    """
    from apps.planning import edit_service as edit

    from .garmin_sync import remove_from_garmin, resync_on_garmin

    workout = PlannedWorkout.objects.filter(
        athlete=athlete, pk=change.get("workout_id"),
        status=PlannedWorkout.Status.PLANNED,
    ).first()
    if workout is None:
        raise DayError("That session is no longer there.")
    if workout.date < athlete.local_today:
        raise DayError("That day has already been.")

    action = change.get("action")
    if action == "skip":
        workout.status = PlannedWorkout.Status.SKIPPED
        workout.save(update_fields=["status"])
        remove_from_garmin(athlete, [workout.pk])
        return {"workout_id": workout.pk, "action": "skip", "date": workout.date.isoformat()}

    if action == "move":
        try:
            when = dt.date.fromisoformat(str(change.get("move_to")))
        except (TypeError, ValueError) as exc:
            raise DayError("That move has no date on it.") from exc
        if when < athlete.local_today:
            raise DayError("A session cannot be moved into the past.")
        workout.moved_from = workout.moved_from or workout.date
        workout.date = when
        workout.save(update_fields=["date", "moved_from"])
        resync_on_garmin(athlete, [workout.pk])
        return {"workout_id": workout.pk, "action": "move", "date": when.isoformat()}

    if action == "easier":
        minutes = int(change.get("minutes") or 0)
        if not MIN_MINUTES <= minutes <= MAX_MINUTES:
            raise DayError(f"A session is {MIN_MINUTES}–{MAX_MINUTES} minutes.")
        try:
            edit.edit_workout(athlete, workout.pk, {"total_minutes": minutes},
                              via="app", confirmed=True)
        except (edit.NotEditable, edit.EditError) as exc:
            raise DayError(str(exc)) from exc
        return {"workout_id": workout.pk, "action": "easier", "minutes": minutes,
                "date": workout.date.isoformat()}

    raise DayError("That is not a change this can make.")


def gym_level(athlete: Athlete, day: dt.date) -> int:
    """Where this athlete is on the programme clock for that day.

    Read the same way the gym re-layout reads it, from the start of the
    strength programme rather than from today, so a session added for next
    Tuesday is the session the programme would have placed on next Tuesday.
    Taking the level from the current date instead would make an added session
    quietly easier than the ones around it.
    """
    from planning import strength as srules

    from .strength_service import _level_start

    plan = TrainingPlan.objects.filter(
        athlete=athlete, status=TrainingPlan.Status.ACTIVE,
    ).first()
    start = _level_start(plan, athlete) if plan else athlete.local_today
    return srules.level_for(start, day)


def build_gym(athlete: Athlete, day: dt.date) -> dict:
    """A strength session at the athlete's current rungs.

    Reuses the programme's own exercise selection, so an added gym day is the
    session the programme would have given on that day — including the
    per-pattern levels, which is the whole point of the ladder. Adding one does
    not reset anybody to wall push-ups.
    """
    from planning import strength as srules

    level = gym_level(athlete, day)
    return {
        "title": srules.title_for(level),
        "level": level,
        "duration_s": srules.DURATION_S,
        "exercises": srules.exercises(
            level, athlete.strength_levels or {}, equipment=athlete.gym_equipment,
        ),
    }


@transaction.atomic
def save_run(athlete: Athlete, day: dt.date, session: dict) -> PlannedWorkout:
    _check_date(athlete, day)
    return PlannedWorkout.objects.create(
        athlete=athlete, plan=container_plan(athlete), phase=None, date=day,
        title=session["title"][:120], kind=session["kind"],
        duration_s=session["duration_s"], load=session["load"],
        steps=session["steps"], description=session.get("description", ""),
        purpose=session.get("purpose", ""), target_zone=session.get("target_zone"),
        created_by=USER,
    )


@transaction.atomic
def save_gym(athlete: Athlete, day: dt.date, session: dict) -> StrengthSession:
    _check_date(athlete, day)
    return StrengthSession.objects.create(
        athlete=athlete, plan=None, date=day,
        title=session["title"][:80], level=session["level"],
        duration_s=session["duration_s"], exercises=session["exercises"],
        after_run=PlannedWorkout.objects.filter(
            athlete=athlete, date=day, status=PlannedWorkout.Status.PLANNED,
        ).exists(),
        created_by=USER,
    )
