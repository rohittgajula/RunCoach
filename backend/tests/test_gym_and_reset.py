"""The gym programme and clearing planning data.

The strength tests are about one promise: week one must be doable by somebody who
cannot do a push-up. That is not a style preference — failing in the first session
is the most reliable way to stop going, and a programme nobody returns to has no
other virtue worth testing.

The reset tests are about the opposite promise: that it stops where it is told to.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.urls import reverse

from apps.planning.models import PlannedWorkout, StrengthSession, TrainingPlan
from planning import strength as rules


# --- the ladders ------------------------------------------------------------


def test_week_one_is_doable_by_someone_who_cannot_do_a_pushup():
    """The founding requirement, as an assertion.

    Rohit's words were "i cant even make one pushup". A programme whose first
    session contains a push-up is therefore not a beginner programme, however
    beginner it looks from the outside.
    """
    session = {e["key"]: e for e in rules.exercises(1)}

    assert session["push"]["name"] == "Wall push-up"
    assert session["squat"]["name"] == "Box squat"
    assert session["hinge"]["name"] == "Glute bridge"
    # Nothing in week one needs equipment he may not have found yet.
    for entry in session.values():
        assert "barbell" not in entry["load"].lower()
        assert entry["sets"] == 2, "week one is two sets, not three"


def test_every_pattern_is_present_in_every_session():
    """Full body every time.

    A split exists for people lifting five days a week. Someone training twice
    cannot give a whole session to one half of themselves — they would train each
    half once a week, which is below the threshold where anything adapts.
    """
    for level in range(1, rules.MAX_LEVEL + 1):
        keys = [e["key"] for e in rules.exercises(level)]
        assert keys == list(rules.PATTERNS)


def test_patterns_climb_independently():
    """The whole reason the ladders are per pattern.

    Almost nobody can squat and press at the same level. One programme number
    forces one of the two to be wrong.
    """
    session = {e["key"]: e for e in rules.exercises(1, {"squat": 4, "push": 1})}
    assert session["squat"]["level"] == 4
    assert session["push"]["level"] == 1
    assert session["push"]["name"] == "Wall push-up"


def test_graduate_clamps_at_both_ends():
    levels = rules.default_levels()
    assert rules.graduate(levels, "push", -1)["push"] == 1
    top = levels | {"push": rules.MAX_LEVEL}
    assert rules.graduate(top, "push", 1)["push"] == rules.MAX_LEVEL


def test_every_rung_says_how_to_leave_it():
    """"When it feels easy" is unfalsifiable, and everybody under-rates themselves."""
    for ladder in rules.ladders():
        assert len(ladder["steps"]) == rules.MAX_LEVEL
        for step in ladder["steps"]:
            assert step["graduate_when"].strip()


# --- placement --------------------------------------------------------------


MONDAY = dt.date(2026, 11, 16)


def _week(long_run_on: int = 6) -> list[rules.Day]:
    kinds = {1: ("EASY",), 3: ("EASY",), long_run_on: ("LONG",)}
    return [rules.Day(MONDAY + dt.timedelta(days=i), kinds.get(i, ())) for i in range(7)]


def test_chosen_gym_days_are_honoured():
    placed = rules.place(_week(), 2, MONDAY, MONDAY + dt.timedelta(days=6),
                         gym_days={1, 4})
    assert {d.weekday() for d, _ in placed} == {1, 4}


def test_a_chosen_day_still_loses_to_tomorrows_long_run():
    """The one case where the athlete's preference is overruled.

    It loses to their own next run, which is the only thing that should be able
    to beat it. Squatting on Saturday and then asking for the week's longest
    continuous effort on Sunday produces a long run that falls apart in the
    first ten minutes.
    """
    placed = rules.place(_week(long_run_on=6), 2, MONDAY, MONDAY + dt.timedelta(days=6),
                         gym_days={5})
    assert placed == []


def test_no_gym_days_set_falls_back_to_spacing():
    placed = rules.place(_week(), 2, MONDAY, MONDAY + dt.timedelta(days=6))
    assert len(placed) == 2
    days = sorted(d for d, _ in placed)
    assert (days[1] - days[0]).days > 1, "sessions are never on consecutive days"


# --- clearing ---------------------------------------------------------------


@pytest.fixture
def plan_with_workouts(athlete):
    today = athlete.local_today
    plan = TrainingPlan.objects.create(
        athlete=athlete, name="Test plan", status=TrainingPlan.Status.ACTIVE,
        generator_version="test",
    )
    for offset in (-3, -1, 0, 2, 5):
        PlannedWorkout.objects.create(
            athlete=athlete, plan=plan, date=today + dt.timedelta(days=offset),
            title="Easy run", kind="EASY", duration_s=1800, load=30.0,
        )
    StrengthSession.objects.create(
        athlete=athlete, plan=plan, date=today + dt.timedelta(days=2),
        title="Gym", duration_s=2100, level=1, exercises=[],
    )
    return plan


@pytest.mark.django_db
def test_clearing_upcoming_keeps_the_past(api, athlete, plan_with_workouts):
    """What has already happened is not planning data.

    Deleting yesterday's session would quietly change the history every future
    plan is built from, which is a strange thing for a button labelled "start
    over" to do.
    """
    today = athlete.local_today

    response = api.post(reverse("plan-reset"), {"upcoming": True, "confirm": "CLEAR"}, format="json")

    assert response.status_code == 200
    remaining = list(PlannedWorkout.objects.filter(athlete=athlete).values_list("date", flat=True))
    assert all(d < today for d in remaining)
    assert len(remaining) == 2
    # Today counts as ahead of you: a session not yet done is still to do.
    assert not PlannedWorkout.objects.filter(athlete=athlete, date=today).exists()


@pytest.mark.django_db
def test_clearing_refuses_without_the_confirmation(api, athlete, plan_with_workouts):
    response = api.post(reverse("plan-reset"), {"plans": True, "confirm": "yes"}, format="json")
    assert response.status_code == 400
    assert PlannedWorkout.objects.filter(athlete=athlete).exists()


@pytest.mark.django_db
def test_clearing_nothing_is_an_error_not_a_no_op(api, athlete, plan_with_workouts):
    """A reset that silently does nothing is worse than one that refuses.

    The athlete came here to clear something; reporting success while every row
    survives means they find out weeks later.
    """
    response = api.post(reverse("plan-reset"), {"confirm": "CLEAR"}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_clearing_a_plan_leaves_activities_alone(api, athlete, plan_with_workouts):
    """Runs are the record of what happened, and replanning is no reason to forget."""
    from apps.activities.models import Activity
    from django.utils import timezone

    Activity.objects.create(
        athlete=athlete, source=Activity.Source.GARMIN_SYNC, sport="running",
        started_at=timezone.now(), local_date=athlete.local_today,
        total_distance_m=2500, total_timer_s=1700,
    )

    response = api.post(reverse("plan-reset"), {"plans": True, "confirm": "CLEAR"}, format="json")

    assert response.status_code == 200
    assert not TrainingPlan.objects.filter(athlete=athlete).exists()
    assert not PlannedWorkout.objects.filter(athlete=athlete).exists()
    assert Activity.objects.filter(athlete=athlete).count() == 1
