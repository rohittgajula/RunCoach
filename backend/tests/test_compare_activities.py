"""Comparing runs against each other.

The thing these tests protect is the one a comparison screen most easily gets
wrong: telling an athlete a good week was a bad one because a number went down.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.activities.models import Activity, ActivityMetrics


def make_run(athlete, *, day, logged_m, run_m, run_s, longest_s, pace, hr=None, cadence=None):
    activity = Activity.objects.create(
        athlete=athlete, source=Activity.Source.GARMIN_SYNC, sport="running",
        started_at=timezone.now(), local_date=day,
        total_distance_m=logged_m, total_timer_s=run_s * 2, avg_hr=hr,
    )
    ActivityMetrics.objects.create(
        activity=activity, algorithm_version=1,
        run_distance_m=run_m, walk_distance_m=logged_m - run_m,
        run_fraction=run_m / logged_m if logged_m else 0,
        run_duration_s=run_s, walk_duration_s=run_s, stop_duration_s=0,
        run_block_count=3, longest_run_m=run_m / 3, longest_run_s=longest_s,
        run_pace_s_per_km=pace, walk_pace_s_per_km=700, blended_pace_s_per_km=pace * 1.4,
        avg_run_cadence_spm=cadence, avg_run_hr=hr,
    )
    return activity


@pytest.fixture
def two_runs(athlete):
    older = make_run(athlete, day=dt.date(2026, 8, 20), logged_m=2180, run_m=1373,
                     run_s=838, longest_s=837, pace=610, hr=133, cadence=161)
    newer = make_run(athlete, day=dt.date(2026, 10, 9), logged_m=2320, run_m=1200,
                     run_s=700, longest_s=699, pace=583, hr=126, cadence=160)
    return older, newer


@pytest.mark.django_db
def test_faster_at_a_lower_heart_rate_reads_as_better(api, athlete, two_runs):
    """The case that matters, and the one a naive screen gets backwards.

    Pace fell and heart rate fell. Both are improvements, and both are negative
    numbers — a comparison that colours by sign would paint this athlete's best
    progress red.
    """
    older, newer = two_runs
    response = api.post(reverse("activity-compare"),
                        {"ids": [older.pk, newer.pk]}, format="json")

    assert response.status_code == 200
    metrics = {m["key"]: m for m in response.data["metrics"]}

    pace = metrics["run_pace_s_per_km"]
    assert pace["direction"] == -1, "lower pace is better"
    assert pace["change_pct"][str(newer.pk)] < 0

    hr = metrics["avg_run_hr"]
    assert hr["direction"] == -1
    assert hr["change_pct"][str(newer.pk)] < 0

    # And distance, which really did go down, is a metric where down is worse.
    assert metrics["run_distance_m"]["direction"] == 1
    assert metrics["run_distance_m"]["change_pct"][str(newer.pk)] < 0


@pytest.mark.django_db
def test_the_baseline_is_the_oldest_not_the_first_ticked(api, athlete, two_runs):
    """A comparison must not change its mind because you selected in another order.

    Garmin baselines on the first row you ticked, which makes the same four runs
    produce two different readings depending on click order.
    """
    older, newer = two_runs
    forwards = api.post(reverse("activity-compare"),
                        {"ids": [older.pk, newer.pk]}, format="json").data
    backwards = api.post(reverse("activity-compare"),
                         {"ids": [newer.pk, older.pk]}, format="json").data

    assert forwards["metrics"] == backwards["metrics"]
    assert all(m["baseline_id"] == older.pk for m in forwards["metrics"])


@pytest.mark.django_db
def test_everything_compared_is_the_segmented_figure(api, athlete, two_runs):
    """Not what the watch logged.

    The newer run logged MORE than the older one (2.32 km against 2.18) and
    contained LESS running (1.20 km against 1.37). Comparing the logged figure
    would report an improvement that did not happen.
    """
    older, newer = two_runs
    data = api.post(reverse("activity-compare"),
                    {"ids": [older.pk, newer.pk]}, format="json").data

    rows = {r["id"]: r for r in data["activities"]}
    assert rows[newer.pk]["logged_km"] > rows[older.pk]["logged_km"]
    assert rows[newer.pk]["values"]["run_distance_m"] < rows[older.pk]["values"]["run_distance_m"]
    assert data["metrics"], "run distance is compared"
    assert all(m["key"] != "logged_km" for m in data["metrics"])


@pytest.mark.django_db
def test_an_unanalysed_run_says_so_rather_than_reading_as_zero(api, athlete, two_runs):
    older, _ = two_runs
    raw = Activity.objects.create(
        athlete=athlete, source=Activity.Source.GARMIN_SYNC, sport="running",
        started_at=timezone.now(), local_date=dt.date(2026, 10, 10),
        total_distance_m=2000, total_timer_s=1500,
    )
    data = api.post(reverse("activity-compare"),
                    {"ids": [older.pk, raw.pk]}, format="json").data

    assert raw.pk in data["unanalysed"]
    row = next(r for r in data["activities"] if r["id"] == raw.pk)
    assert row["analysed"] is False and row["values"] == {}


@pytest.mark.django_db
def test_one_activity_is_not_a_comparison(api, athlete, two_runs):
    older, _ = two_runs
    response = api.post(reverse("activity-compare"), {"ids": [older.pk]}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_another_athletes_run_cannot_be_compared_in(api, athlete, other_athlete, two_runs):
    """Tenancy, at the one endpoint that takes a list of ids from the client."""
    older, newer = two_runs
    theirs = make_run(other_athlete, day=dt.date(2026, 10, 1), logged_m=5000,
                      run_m=5000, run_s=1500, longest_s=1500, pace=300)
    data = api.post(reverse("activity-compare"),
                    {"ids": [older.pk, newer.pk, theirs.pk]}, format="json").data

    assert {r["id"] for r in data["activities"]} == {older.pk, newer.pk}


@pytest.mark.django_db
def test_at_most_four(api, athlete, two_runs):
    older, newer = two_runs
    extra = [make_run(athlete, day=dt.date(2026, 9, d), logged_m=2000, run_m=1000,
                      run_s=600, longest_s=300, pace=600).pk for d in (1, 2, 3)]
    response = api.post(reverse("activity-compare"),
                        {"ids": [older.pk, newer.pk, *extra]}, format="json")
    assert response.status_code == 400
