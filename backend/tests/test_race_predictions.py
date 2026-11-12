"""Garmin's race prediction beside ours.

Both numbers were already in the database and had never been shown together.
They disagree, and the disagreement is the content: Garmin's 5k of 46:03 is
9:13/km held continuously, and Rohit's longest unbroken run is 11:39.

What these tests protect is that neither number is presented as the answer.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.activities.models import Activity, ActivityMetrics
from apps.ingest.models import DailyMetrics


def add_run(athlete, *, day, logged_m, run_m, run_s, longest_s, pace):
    activity = Activity.objects.create(
        athlete=athlete, source=Activity.Source.GARMIN_SYNC, sport="running",
        started_at=timezone.now(), local_date=day,
        total_distance_m=logged_m, total_timer_s=run_s * 2,
    )
    ActivityMetrics.objects.create(
        activity=activity, algorithm_version=1,
        run_distance_m=run_m, walk_distance_m=logged_m - run_m,
        run_fraction=run_m / logged_m, run_duration_s=run_s, walk_duration_s=run_s,
        stop_duration_s=0, run_block_count=3, longest_run_m=run_m / 3,
        longest_run_s=longest_s, run_pace_s_per_km=pace,
        walk_pace_s_per_km=700, blended_pace_s_per_km=pace * 1.4,
    )
    return activity


@pytest.fixture
def athlete_with_both(athlete):
    """Rohit's real shape: Garmin optimistic, segmented runs modest."""
    today = athlete.local_today
    for weeks_ago in range(12):
        add_run(athlete, day=today - dt.timedelta(weeks=weeks_ago),
                logged_m=2400, run_m=1200, run_s=725, longest_s=400, pace=604)
    DailyMetrics.objects.create(
        athlete=athlete, metric_date=today,
        race_pred_5k_s=2763, race_pred_10k_s=5970,      # 46:03 and 1:39:30
        race_pred_half_s=13791, race_pred_marathon_s=28000,
    )
    return athlete


@pytest.mark.django_db
def test_both_numbers_appear_and_neither_is_called_the_answer(api, athlete_with_both):
    data = api.get(reverse("race-predictions")).data
    five = next(d for d in data["distances"] if d["key"] == "5k")

    assert five["garmin_s"] == 2763
    assert five["ours"]["mode"] in ("RUN_WALK", "CONTINUOUS", "INSUFFICIENT_DATA")
    # The explanation frames them as different questions, not a contest.
    assert data["explanation"]["garmin_assumes"]
    assert data["explanation"]["ours_assumes"]


@pytest.mark.django_db
def test_the_gap_is_explained_by_the_unbroken_block(api, athlete_with_both):
    """The useful sentence on the whole screen.

    Until the block grows, the difference between the two numbers is mostly
    walking rather than fitness — and that is a thing the plan can change.
    """
    data = api.get(reverse("race-predictions")).data
    why = data["explanation"]["why_they_differ"]

    assert why and "unbroken" in why
    assert data["explanation"]["longest_unbroken_s"] == 400


@pytest.mark.django_db
def test_a_stale_garmin_estimate_is_flagged_not_hidden(api, athlete):
    """Garmin stops updating without sustained running.

    Rohit's sat frozen for weeks while he was disconnected. Presenting a
    two-month-old estimate as today's answer is the same failure as the sync
    banner existed to fix.
    """
    DailyMetrics.objects.create(
        athlete=athlete, metric_date=athlete.local_today - dt.timedelta(days=40),
        race_pred_5k_s=2763,
    )
    data = api.get(reverse("race-predictions")).data

    assert data["garmin_stale"] is True
    assert data["garmin_age_days"] == 40
    assert data["distances"][0]["garmin_s"] == 2763, "still shown, with its age"


@pytest.mark.django_db
def test_no_garmin_estimate_is_not_an_error(api, athlete):
    """A new athlete, or one whose watch has never had enough to go on."""
    data = api.get(reverse("race-predictions")).data

    assert data["garmin_as_of"] is None
    assert all(d["garmin_s"] is None for d in data["distances"])
    assert data["explanation"] is None


@pytest.mark.django_db
def test_our_side_refuses_rather_than_inventing_one(api, athlete):
    """Below the data threshold there is no number at all.

    A point estimate off three runs is fiction, and fiction beside Garmin's
    figure would read as a second opinion.
    """
    add_run(athlete, day=athlete.local_today, logged_m=2000, run_m=800,
            run_s=500, longest_s=300, pace=600)
    data = api.get(reverse("race-predictions")).data
    five = next(d for d in data["distances"] if d["key"] == "5k")

    assert five["ours"]["mode"] == "INSUFFICIENT_DATA"
    assert five["ours"]["likely_finish_s"] is None
