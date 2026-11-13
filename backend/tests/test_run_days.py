"""A gym day is not a run day, however the two maps got written.

The generator places runs from `available_days` and has no idea gym days
exist. The settings picker writes both maps together so it cannot create a day
that is in both — but it cannot repair one either, because a day already in
both renders as "Gym" (gym wins the display) while still being handed to the
generator as a candidate.

What that looked like: four run days picked, and a plan with runs on three of
them plus one on a gym day. The generator saw five candidates, wanted four,
spaced them, and dropped the Thursday nobody had taken away.
"""

from __future__ import annotations

import pytest

from apps.planning.plan_services import run_days_for

MON, TUE, WED, THU, FRI, SAT, SUN = (str(d) for d in range(7))


def days(**kw) -> dict:
    return {str(d): kw.get("mtwtfss"[d], False) for d in range(7)}


@pytest.fixture
def athlete_days(athlete):
    def setup(available: dict, gym: dict):
        athlete.available_days = available
        athlete.gym_days = gym
        athlete.save(update_fields=["available_days", "gym_days"])
        return athlete
    return setup


def test_a_day_in_both_maps_is_a_gym_day(athlete_days, db):
    """The exact reported state: Friday left available and also a gym day."""
    a = athlete_days(
        {MON: True, WED: True, THU: True, FRI: True, SUN: True},
        {TUE: True, FRI: True},
    )
    assert run_days_for(a) == {MON: True, WED: True, THU: True, FRI: False, SUN: True}


def test_the_count_is_what_the_picker_showed(athlete_days, db):
    """Five candidates for four runs is what let it drop a day of its choosing."""
    a = athlete_days(
        {MON: True, WED: True, THU: True, FRI: True, SUN: True},
        {TUE: True, FRI: True},
    )
    assert sum(1 for on in run_days_for(a).values() if on) == 4


def test_clean_data_is_untouched(athlete_days, db):
    a = athlete_days({MON: True, WED: True, THU: True, SUN: True}, {TUE: True, FRI: True})
    assert run_days_for(a) == {MON: True, WED: True, THU: True, SUN: True}


def test_no_gym_days_changes_nothing(athlete_days, db):
    a = athlete_days({MON: True, TUE: True, SAT: True}, {})
    assert run_days_for(a) == {MON: True, TUE: True, SAT: True}


def test_every_day_a_gym_day_leaves_no_run_days(athlete_days, db):
    """Not a crash: the caller treats no available days as "you choose"."""
    a = athlete_days({MON: True, TUE: True}, {MON: True, TUE: True})
    assert not any(run_days_for(a).values())


def test_it_reaches_the_baseline(athlete_days, db):
    from apps.planning.plan_services import baseline_for

    a = athlete_days(
        {MON: True, WED: True, THU: True, FRI: True, SUN: True},
        {TUE: True, FRI: True},
    )
    assert baseline_for(a).available_days.get(FRI) is False


# --- the same mistake, everywhere else it was made ---------------------------


def test_the_coach_is_told_run_days_not_training_days(athlete_days, db):
    """`training_days_per_week` goes into the model's context and into the
    relayout. Counting gym days there tells the coach you have five days to run
    on when you have four."""
    a = athlete_days(
        {MON: True, WED: True, THU: True, FRI: True, SUN: True},
        {TUE: True, FRI: True},
    )
    assert a.training_days_per_week == 4


def test_is_available_is_false_on_a_gym_day(athlete_days, db):
    """Used by the illness return-to-running, which would otherwise bring you
    back on a day you are in the gym."""
    a = athlete_days({MON: True, FRI: True}, {FRI: True})
    assert a.is_available(0) is True
    assert a.is_available(4) is False


def test_a_long_run_cannot_be_set_on_a_gym_day(athlete_days, db):
    """The validator checked the raw map, so it accepted a day the generator
    would then refuse to put anything on."""
    from apps.athletes import profile_params

    a = athlete_days({MON: True, FRI: True}, {FRI: True})
    with pytest.raises(ValueError, match="isn't one of your run days"):
        profile_params.validate_setting(a, "long_run_day", 4)
    profile_params.validate_setting(a, "long_run_day", 0)
