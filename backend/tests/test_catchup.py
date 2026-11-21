"""When the plan and the athlete disagree, the plan is the one that is wrong.

Rohit's record the day this was written: ten runs in eleven weeks, a four-week
gap through October, three runs in the week of 9 November, then ten days of
nothing. Thirteen past sessions sitting at "planned" — not done, not skipped,
never resolved — and the app's response was to keep generating more of them.

A cascade that rebuilds the ramp down to what somebody is actually managing has
existed for a while. It only ever ran when the coach called it mid-chat, so an
athlete who quietly stopped got a calendar that quietly carried on. This is the
piece that closes the loop.
"""

from __future__ import annotations

import datetime as dt

import pytest

from apps.planning import catchup
from apps.planning.models import PlannedWorkout, TrainingPlan
from tests.r6_helpers import make_activity
from tests.r7_helpers import active_plan, make_workout


def miss(athlete, days_ago: int, plan=None):
    """A session that was prescribed and never done."""
    return make_workout(athlete, athlete.local_today - dt.timedelta(days=days_ago))


@pytest.fixture
def plan(athlete):
    return active_plan(athlete)


# --- what counts as a miss ----------------------------------------------------


@pytest.mark.django_db
def test_a_prescribed_session_nobody_did_is_a_miss(athlete, plan):
    for days in (2, 4, 6):
        miss(athlete, days)
    assert len(catchup.missed_in_window(athlete, athlete.local_today, plan)) == 3


@pytest.mark.django_db
def test_a_session_they_skipped_on_purpose_is_not(athlete, plan):
    """They made a decision. The plan does not need to react to a decision the
    way it reacts to silence."""
    w = miss(athlete, 3)
    w.status = PlannedWorkout.Status.SKIPPED
    w.save(update_fields=["status"])
    assert catchup.missed_in_window(athlete, athlete.local_today, plan) == []


@pytest.mark.django_db
def test_a_session_they_actually_did_is_not(athlete, plan):
    w = miss(athlete, 3)
    w.completed_activity = make_activity(athlete, w.date)
    w.save(update_fields=["completed_activity"])
    assert catchup.missed_in_window(athlete, athlete.local_today, plan) == []


@pytest.mark.django_db
def test_sessions_from_a_proposal_nobody_accepted_are_not_misses(athlete, plan):
    """The bug this nearly shipped with.

    Sessions belonging to proposals that were never accepted, and to plans long
    since archived, stay in the table at "planned" forever. The calendar hides
    them. Counting them here would shrink a plan on the strength of sessions
    nobody agreed to do — on the real data, eight of twelve apparent misses
    came from two proposals that were declined by being ignored.
    """
    ghost = TrainingPlan.objects.create(
        athlete=athlete, name="Never accepted", status=TrainingPlan.Status.PROPOSED,
        generator_version="g1",
    )
    PlannedWorkout.objects.create(
        athlete=athlete, plan=ghost, date=athlete.local_today - dt.timedelta(days=3),
        title="Ghost run", kind="EASY", duration_s=1800, load=30,
        steps=[{"kind": "run", "duration_s": 1800, "intensity": "easy", "label": "Run"}],
    )
    assert catchup.missed_in_window(athlete, athlete.local_today, plan) == []


@pytest.mark.django_db
def test_the_window_does_not_reach_back_through_the_whole_plan(athlete, plan):
    """Someone who missed a week in September and has run every day since does
    not need their December rewritten."""
    miss(athlete, catchup.LOOKBACK_DAYS + 5)
    assert catchup.missed_in_window(athlete, athlete.local_today, plan) == []


# --- when it fires ------------------------------------------------------------


@pytest.mark.django_db
def test_one_missed_run_is_a_tuesday_with_something_else_on(athlete, plan):
    """It fires on a pattern, not an incident."""
    miss(athlete, 2)
    assert catchup.adapt(athlete)["adapted"] is False


@pytest.mark.django_db
def test_a_fortnight_nobody_followed_rebuilds_the_weeks_ahead(athlete, plan):
    from tests.r7_helpers import tomorrow

    for days in (2, 4, 6, 8):
        miss(athlete, days)
    future = make_workout(athlete, tomorrow(athlete, 9))
    before = future.duration_s

    result = catchup.adapt(athlete)
    assert result["adapted"] is True
    assert result["missed"] >= catchup.MISSED_BEFORE_ADAPTING

    future.refresh_from_db()
    assert future.duration_s < before, "the weeks ahead did not come down"


@pytest.mark.django_db
def test_it_rebuilds_once_per_interruption_not_once_per_day(athlete, plan):
    """An athlete who has stopped for a month should see the plan shrink once
    and then settle, not shrink every morning."""
    for days in (2, 4, 6, 8):
        miss(athlete, days)
    assert catchup.adapt(athlete)["adapted"] is True
    second = catchup.adapt(athlete)
    assert second["adapted"] is False
    assert second["reason"] == "adapted recently"


@pytest.mark.django_db
def test_nothing_happens_without_an_active_plan(athlete):
    assert catchup.adapt(athlete)["adapted"] is False


# --- what it rebuilds from ----------------------------------------------------


@pytest.mark.django_db
def test_running_that_was_never_matched_to_a_session_still_counts(athlete, plan):
    """Taken from activities rather than completed workouts: a run that was
    never linked to a planned session still happened, and a plan that ignored
    it would shrink somebody who is in fact running."""
    make_activity(athlete, athlete.local_today - dt.timedelta(days=2), run_s=1800)
    make_activity(athlete, athlete.local_today - dt.timedelta(days=5), run_s=1800)
    assert catchup.ran_in_window(athlete, athlete.local_today) > 0


@pytest.mark.django_db
def test_a_silent_fortnight_rebuilds_from_nothing_rather_than_dividing_by_it(
    athlete, plan,
):
    """The edge the cascade had to be fixed for once already: a week of zero
    cannot multiply its way back up, so the ramp restarts from a fraction of
    what was planned instead of staying at zero forever."""
    from tests.r7_helpers import tomorrow

    for days in (2, 4, 6, 8):
        miss(athlete, days)
    future = make_workout(athlete, tomorrow(athlete, 9))

    assert catchup.ran_in_window(athlete, athlete.local_today) == 0
    catchup.adapt(athlete)

    future.refresh_from_db()
    assert future.duration_s > 0, "the plan went to zero and could never climb out"


# --- the task -----------------------------------------------------------------


@pytest.mark.django_db
def test_illness_pauses_it(athlete, plan):
    """Someone who is ill has a reason for the empty fortnight and already has
    a mode for it. Shrinking the plan on top of pausing it would have them come
    back to a build smaller than illness mode is holding."""
    from apps.health.models import Illness
    from apps.planning.tasks import catchup_task

    for days in (2, 4, 6, 8):
        miss(athlete, days)
    Illness.objects.create(athlete=athlete, start_date=athlete.local_today, type="cold")
    assert catchup_task(athlete.pk) == {"skipped": "illness"}
