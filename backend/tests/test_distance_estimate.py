"""How far a timed session actually goes.

Rohit: "here we have hr time thats good, can you add how much distance it it
gonna be on an average (both run + walk & overall)".

A run/walk session is prescribed in minutes — "27 min: 5 min walk, then 4 min
run, then ..." — and the athlete cannot convert that to distance in their head,
because the two halves happen at paces about 100 s/km apart. The estimate
existed but gave one combined figure, and it built that figure on a constant.
"""

from __future__ import annotations

import datetime as dt

import pytest

from apps.planning.models import PlannedWorkout
from apps.planning.presenters import WALK_PACE_FALLBACK_S_PER_KM, distance_estimate, walk_pace_for
from tests.r6_helpers import make_activity
from tests.r7_helpers import active_plan


def steps(*parts) -> list[dict]:
    """(kind, seconds, intensity) triples -> stored step dicts."""
    return [
        {"kind": k, "duration_s": s, "intensity": i, "label": "",
         "pace_min_s": None, "pace_max_s": None, "hr_min": None, "hr_max": None}
        for k, s, i in parts
    ]


@pytest.fixture
def workout(athlete):
    """Rohit's shape of session: a walk, then run blocks with walks between."""
    athlete.easy_pace_min, athlete.easy_pace_max = 590, 650
    athlete.save(update_fields=["easy_pace_min", "easy_pace_max"])
    return PlannedWorkout.objects.create(
        athlete=athlete, plan=active_plan(athlete),
        date=athlete.local_today, title="27m run/walk",
        kind="RUN_WALK", duration_s=27 * 60, load=30,
        steps=steps(
            ("warmup", 300, "walk"),
            ("run", 240, "easy"), ("walk", 120, "walk"),
            ("run", 240, "easy"), ("walk", 120, "walk"),
            ("run", 240, "easy"), ("cooldown", 360, "walk"),
        ),
    )


@pytest.mark.django_db
def test_the_running_and_the_walking_are_reported_apart(workout):
    """One combined figure hides which part of the session is the training,
    which for a beginner building continuous running is the part that matters."""
    e = distance_estimate(workout)
    assert e["run_km"] > 0 and e["walk_km"] > 0
    assert e["run_s"] == 720 and e["walk_s"] == 900


@pytest.mark.django_db
def test_the_parts_add_up_to_the_total(workout):
    """A split that does not sum is worse than no split: the athlete checks."""
    e = distance_estimate(workout)
    assert e["run_km"] + e["walk_km"] == pytest.approx(e["km"], abs=0.05)


@pytest.mark.django_db
def test_the_walk_pace_is_measured_rather_than_assumed(athlete, workout):
    """It was a flat 600 s/km for everybody — a brisk walk, and not what most
    beginners do. Rohit's own figure is about 710, so every session with
    walking in it was credited with ground he does not cover.

    The number is in the data already: segmentation records walk_pace_s_per_km
    on every run."""
    for day_offset in range(3):
        make_activity(athlete, athlete.local_today - dt.timedelta(days=day_offset * 3))

    pace = walk_pace_for(athlete)
    assert pace == 750  # what r6_helpers records, not the old 600 constant

    e = distance_estimate(workout)
    assert e["walk_pace_s_per_km"] == 750
    assert e["walk_km"] == pytest.approx(900 / 750, abs=0.01)


@pytest.mark.django_db
def test_an_athlete_with_no_walking_on_record_gets_the_fallback(workout):
    """Nothing measured, so nothing to measure from — but the estimate must
    still appear rather than vanishing or dividing by zero."""
    assert walk_pace_for(workout.athlete) == WALK_PACE_FALLBACK_S_PER_KM
    e = distance_estimate(workout)
    assert e["walk_km"] > 0


@pytest.mark.django_db
def test_rest_and_gym_days_have_no_distance(athlete):
    """Neither covers ground on a plan, and a 0.0 km row on a gym card is a
    number pretending to be information."""
    for kind in ("REST", "STRENGTH"):
        w = PlannedWorkout.objects.create(
            athlete=athlete, plan=active_plan(athlete),
            date=athlete.local_today, title=kind, kind=kind,
            duration_s=1800, load=0, steps=steps(("run", 1800, "easy")),
        )
        assert distance_estimate(w) is None


@pytest.mark.django_db
def test_a_session_with_no_steps_has_no_estimate(athlete):
    w = PlannedWorkout.objects.create(
        athlete=athlete, plan=active_plan(athlete),
        date=athlete.local_today, title="Empty", kind="EASY",
        duration_s=0, load=0, steps=[],
    )
    assert distance_estimate(w) is None


@pytest.mark.django_db
def test_the_estimate_reaches_the_api(api, workout):
    """It is only useful on the screen the steps are on."""
    body = api.get(f"/api/workouts/{workout.pk}/").json()
    e = body["distance_estimate"]
    assert e["run_km"] > 0 and e["walk_km"] > 0 and e["km"] > 0
    assert e["run_pace_s_per_km"] > 0 and e["walk_pace_s_per_km"] > 0
