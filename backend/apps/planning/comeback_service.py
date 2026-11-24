"""The comeback card: noticing a gap, and doing something about the answer.

Rules live in `planning/comeback.py`; this reads the athlete's rows and turns
an answer into a change.

The answers are the point. The app has had a journal and a morning check-in for
months and neither has ever asked why he stopped, so adding a question that
only records the reply would be adding a survey. Each answer does something:

    hurt    -> illness mode, which already exists and already pauses the plan
    much    -> the catch-up cascade, forced, which rebuilds from what he did
    life    -> nothing, said plainly, because nothing is the right answer
    restart -> a new block from today, for a gap long enough that the old plan
               is about somebody else

`nothing` is not a no-op in the UI sense — it dismisses the card for a while,
so an honest "life got in the way" is not punished with the same question
tomorrow morning.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.db import transaction

from planning import comeback

from .models import TrainingPlan

logger = logging.getLogger(__name__)

#: How long an answer quietens the card for. A fortnight: long enough that
#: answering is not a daily chore, short enough that a gap which carries on
#: gets asked about again.
QUIET_DAYS = 14

#: Where the last answer is recorded. On the athlete rather than the plan,
#: because "life got in the way" outlives the plan it was said about, and in
#: `ui_state` rather than anywhere training-shaped, because an answer to a
#: prompt must never be mistaken for a setting.
MARKER = "comeback_answered_on"


def _last_run(athlete) -> dt.date | None:
    from apps.activities.models import Activity

    row = (Activity.objects.filter(athlete=athlete, sport="running")
           .order_by("-local_date").values_list("local_date", flat=True).first())
    return row


def _best_block_s(athlete) -> float:
    from apps.activities.models import ActivityMetrics
    from django.db.models import Max

    return float(ActivityMetrics.objects.filter(
        activity__athlete=athlete,
    ).aggregate(best=Max("longest_run_s"))["best"] or 0)


def _weekly_counts(athlete, today: dt.date, weeks: int = comeback.FLOOR_WEEKS) -> list[int]:
    """Runs per week over the recent past, oldest first, zeros included.

    The zeros are load-bearing. A floor computed only from the weeks he showed
    up would be the floor of a man who never stops, which is not this one.
    """
    from apps.activities.models import Activity

    monday = today - dt.timedelta(days=today.weekday())
    start = monday - dt.timedelta(weeks=weeks - 1)
    counts = {monday - dt.timedelta(weeks=i): 0 for i in range(weeks)}
    for day in Activity.objects.filter(
        athlete=athlete, sport="running", local_date__gte=start,
    ).values_list("local_date", flat=True):
        week = day - dt.timedelta(days=day.weekday())
        if week in counts:
            counts[week] += 1
    return [counts[monday - dt.timedelta(weeks=i)] for i in range(weeks - 1, -1, -1)]


def _answered_recently(athlete, today: dt.date) -> bool:
    raw = (athlete.ui_state or {}).get(MARKER)
    if not raw:
        return False
    try:
        when = dt.date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return False
    return (today - when).days < QUIET_DAYS


def card_for(athlete) -> dict:
    """What Today should show about the gap, the return run and the week."""
    today = athlete.local_today
    counts = _weekly_counts(athlete, today)
    floor = comeback.week_floor(counts)
    this_week = counts[-1] if counts else 0

    gap = comeback.gap_for(_last_run(athlete), today)
    show_gap = gap.noticed and not _answered_recently(athlete, today)
    ret = comeback.return_session(gap, _best_block_s(athlete)) if gap.noticed else None

    return {
        # The floor is always on, gap or no gap: a week is a week.
        "week": {
            "floor": floor,
            "runs": this_week,
            "met": comeback.floor_met(this_week, floor),
            "line": comeback.floor_line(this_week, floor),
            "recent": counts,
        },
        "gap": ({
            "days": gap.days,
            "long": gap.long,
            "headline": gap.headline,
            "answers": [
                {"key": a.key, "label": a.label, "action": a.action, "note": a.note}
                for a in gap.answers
            ],
        } if show_gap else None),
        "return": ({"minutes": ret.minutes, "framing": ret.framing} if ret else None),
    }


@transaction.atomic
def answer(athlete, key: str) -> dict:
    """Act on what the athlete said. Returns what was done, in their words."""
    valid = {a.key: a for a in (*comeback.ANSWERS, comeback.RESTART)}
    chosen = valid.get(key)
    if chosen is None:
        raise ValueError("That is not one of the answers.")

    today = athlete.local_today
    done = {"action": chosen.action, "label": chosen.label}

    if chosen.action == "shrink":
        from .catchup import adapt

        done["result"] = adapt(athlete, force=True)

    elif chosen.action == "restart":
        from .plan_store import PlanError, accept_plan, propose_practice_plan

        try:
            plan = accept_plan(propose_practice_plan(athlete))
            done["result"] = {"plan_id": plan.pk, "name": plan.name}
        except PlanError as exc:
            done["result"] = {"error": str(exc)}

    elif chosen.action == "illness":
        # Deliberately not started here. Illness mode asks what is wrong and
        # for how long, and guessing those on the athlete's behalf would put
        # the plan into a state they did not choose. The card routes them to
        # the screen that asks properly.
        done["result"] = {"go_to": "/health/illness"}

    # "life" does nothing, which is the honest answer to "life got in the way".
    athlete.ui_state = {**(athlete.ui_state or {}), MARKER: today.isoformat()}
    athlete.save(update_fields=["ui_state"])

    logger.info("comeback answer %s for athlete %s -> %s", key, athlete.pk, chosen.action)
    return done
