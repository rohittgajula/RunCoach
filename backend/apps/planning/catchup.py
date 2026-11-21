"""When the plan and the athlete disagree, the plan is the one that is wrong.

Rohit's record, the day this was written: ten runs in eleven weeks, a four-week
gap through October, three runs in the week of 9 November, then nothing for ten
days. Thirteen past sessions sitting at "planned" — not done, not skipped, just
never resolved. Three gym sessions, none done.

The app's response to all of that was to keep generating more of it. There is a
cascade that rebuilds the ramp down to what somebody is actually managing, and
it only ever ran when the coach decided to call it mid-conversation. So an
athlete who quietly stopped got a calendar that quietly carried on.

This is the piece that closes the loop. Once a day it asks one question of each
active plan — *has the last fortnight actually happened?* — and when the answer
is no, it rebuilds the weeks ahead from what did happen.

Three rules, each of which is a way this could go wrong:

**Only the recent past counts.** A fortnight, not the whole plan. Someone who
missed a week in September and has run every day since does not need their
December rewritten, and a window wide enough to hold the whole history would
mean the plan never climbs back out of one bad fortnight.

**It fires on a pattern, not an incident.** One missed run is a Tuesday with
something else on. `MISSED_BEFORE_ADAPTING` consecutive-ish misses is a plan
nobody is following, which is a different thing and the only one worth acting
on.

**Once per interruption, not once per day.** The cascade is recorded against
the plan, so a fortnight of silence produces one rebuild and one thing to tell
the athlete, rather than fourteen. Nobody needs a daily notification that their
plan got smaller again.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.db import transaction

from .models import PlannedWorkout, TrainingPlan

logger = logging.getLogger(__name__)

#: How far back to look. A fortnight is two cycles of a normal week, which is
#: long enough to tell a bad week from a stopped plan.
LOOKBACK_DAYS = 14

#: Misses in that window before the plan is rebuilt. Two is a coincidence;
#: three is a pattern, and the point of the rule is to not react to a
#: coincidence.
MISSED_BEFORE_ADAPTING = 3

#: Don't rebuild again within this many days of the last one. An athlete who
#: has stopped for a month should see the plan shrink once and then settle, not
#: shrink every morning.
QUIET_DAYS = 7

#: Where the record of the last automatic rebuild lives on the plan's summary.
MARKER = "auto_cascade"


def _window(athlete, today: dt.date) -> tuple[dt.date, dt.date]:
    return today - dt.timedelta(days=LOOKBACK_DAYS), today - dt.timedelta(days=1)


def missed_in_window(athlete, today: dt.date, plan: TrainingPlan) -> list[PlannedWorkout]:
    """Past sessions of THIS plan that were prescribed and never done.

    "Missed" is read, never stored — the same definition the calendar paints
    with — so this cannot drift from what the athlete sees. A session they
    skipped on purpose is excluded: they made a decision, and the plan does not
    need to react to a decision the way it reacts to silence.

    Scoped to the one plan, which is not a detail. Sessions belonging to
    proposals the athlete never accepted, and to plans long since archived,
    stay in the table and sit at "planned" forever; the calendar hides them and
    counting them here would shrink a plan on the strength of sessions nobody
    ever agreed to do. On the data this was written against, eight of twelve
    apparent misses were from two proposals that were never accepted.
    """
    start, end = _window(athlete, today)
    return list(
        PlannedWorkout.objects.filter(
            athlete=athlete, plan=plan, date__gte=start, date__lte=end,
            status=PlannedWorkout.Status.PLANNED,
            completed_activity__isnull=True,
        ).exclude(kind__in=("REST", "STRENGTH")).order_by("date")
    )


def ran_in_window(athlete, today: dt.date) -> int:
    """Seconds of running actually recorded in the window.

    What the rebuilt ramp starts from. Taken from activities rather than from
    completed workouts, because a run that was never matched to a planned
    session still happened, and a plan that ignores it would shrink somebody
    who is in fact running.
    """
    from apps.activities.models import Activity

    start, end = _window(athlete, today)
    total = 0.0
    for activity in Activity.objects.filter(
        athlete=athlete, sport="running", local_date__gte=start, local_date__lte=end,
    ).select_related("metrics"):
        metrics = getattr(activity, "metrics", None)
        if metrics:
            total += float(metrics.run_duration_s or 0)
    # Per week, which is the unit the cascade rebuilds in.
    return round(total / (LOOKBACK_DAYS / 7))


def _recently_adapted(plan: TrainingPlan, today: dt.date) -> bool:
    raw = (plan.summary or {}).get(MARKER)
    if not raw:
        return False
    try:
        when = dt.date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return False
    return (today - when).days < QUIET_DAYS


@transaction.atomic
def adapt(athlete, *, force: bool = False) -> dict:
    """Bring one athlete's plan down to what they are actually doing.

    Returns a summary: `{"adapted": bool, "missed": n, "changed": n, "lines": [...]}`.
    Safe to call daily; safe to call twice.
    """
    from .cascade_service import cascade

    today = athlete.local_today
    plan = TrainingPlan.objects.filter(
        athlete=athlete, status=TrainingPlan.Status.ACTIVE,
    ).select_related("race").first()
    if plan is None:
        return {"adapted": False, "reason": "no active plan"}

    missed = missed_in_window(athlete, today, plan)
    if len(missed) < MISSED_BEFORE_ADAPTING and not force:
        return {"adapted": False, "missed": len(missed), "reason": "not a pattern yet"}
    if _recently_adapted(plan, today) and not force:
        return {"adapted": False, "missed": len(missed), "reason": "adapted recently"}

    achieved = ran_in_window(athlete, today)
    result = cascade(
        plan, athlete, achieved_run_s=achieved,
        reason=f"{len(missed)} sessions missed in the last {LOOKBACK_DAYS} days",
    )

    plan.summary = {**(plan.summary or {}), MARKER: today.isoformat()}
    plan.save(update_fields=["summary"])

    logger.info(
        "auto-adapted plan %s for athlete %s: %s missed, %s weeks changed",
        plan.pk, athlete.pk, len(missed), result.get("changed", 0),
    )
    return {
        "adapted": True,
        "missed": len(missed),
        "achieved_run_s": achieved,
        "changed": result.get("changed", 0),
        "lines": result.get("lines", []),
    }
