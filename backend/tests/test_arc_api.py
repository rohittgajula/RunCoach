"""GET /api/arc/ — the series the Plan tab draws.

Two things are worth a test at this level rather than in test_arc.py. The first
is that an unsegmented activity contributes nothing: the logged distance on a
raw Garmin row includes the walking, and letting it through here would undo the
whole point of the segmenter one endpoint at a time. The second is that a
planned session's duration never reaches the block field, which is the axis bug
this feature could most easily ship with.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.activities.models import Activity, ActivityMetrics
from apps.planning.models import PlannedWorkout, StrengthSession, TrainingPlan


def a_run(athlete, day: dt.date, *, logged_m=2500.0, run_m=1900.0, run_s=900.0,
          longest_s=392.0, segmented=True):
    activity = Activity.objects.create(
        athlete=athlete, source=Activity.Source.GARMIN_SYNC, sport="running",
        started_at=timezone.now(), local_date=day,
        total_distance_m=logged_m, total_timer_s=run_s * 2, avg_hr=146,
    )
    if segmented:
        ActivityMetrics.objects.create(
            activity=activity, algorithm_version=2,
            run_distance_m=run_m, walk_distance_m=logged_m - run_m,
            run_fraction=run_m / logged_m, run_duration_s=run_s,
            walk_duration_s=run_s, stop_duration_s=0, run_block_count=3,
            longest_run_m=run_m / 3, longest_run_s=longest_s,
            run_pace_s_per_km=604, walk_pace_s_per_km=700, blended_pace_s_per_km=840,
            avg_run_cadence_spm=158, avg_run_hr=146,
        )
    return activity


def a_plan(athlete, *, name="Practice"):
    return TrainingPlan.objects.create(
        athlete=athlete, name=name, status=TrainingPlan.Status.ACTIVE,
        generator_version="test",
    )


def a_workout(athlete, plan, day: dt.date, *, duration_s=1440, block_s=370, kind="EASY"):
    steps = [
        {"intensity": "walk", "duration_s": 300},
        {"intensity": "easy", "duration_s": block_s},
        {"intensity": "walk", "duration_s": 180},
        {"intensity": "easy", "duration_s": block_s},
    ] if block_s else []
    return PlannedWorkout.objects.create(
        athlete=athlete, plan=plan, date=day, title="Easy run", kind=kind,
        duration_s=duration_s, load=30.0, steps=steps,
    )


@pytest.fixture
def today(athlete):
    return athlete.local_today


class TestShape:
    def test_empty_account_still_answers(self, api, athlete):
        data = api.get(reverse("training-arc")).data
        assert data["weeks"] == []
        assert data["peak"] == {"run_s": 1, "block_s": 1}
        assert data["notes"] == []

    def test_weeks_are_contiguous_mondays(self, api, athlete, today):
        a_run(athlete, today - dt.timedelta(days=21))
        a_run(athlete, today)
        weeks = api.get(reverse("training-arc")).data["weeks"]
        starts = [dt.date.fromisoformat(str(w["start"])) for w in weeks]
        assert all(s.weekday() == 0 for s in starts)
        assert all((b - a).days == 7 for a, b in zip(starts, starts[1:]))

    def test_exactly_one_current_week(self, api, athlete, today):
        a_run(athlete, today)
        weeks = api.get(reverse("training-arc")).data["weeks"]
        assert sum(1 for w in weeks if w["current"]) == 1

    def test_horizon_params_are_bounded(self, api, athlete, today):
        a_run(athlete, today)
        res = api.get(reverse("training-arc"), {"past_weeks": "900", "future_weeks": "900"})
        assert res.status_code == 200
        assert len(res.data["weeks"]) <= 105

    def test_rubbish_params_are_refused(self, api, athlete):
        assert api.get(reverse("training-arc"), {"past_weeks": "lots"}).status_code == 400


class TestDistanceMeansDistanceRun:
    def test_an_unsegmented_run_alone_leaves_nothing_to_draw(self, api, athlete, today):
        """Its logged distance counts the walking, so there is no honest figure
        to put on the axis — and one dishonest point is worse than an empty
        chart, which at least says so."""
        a_run(athlete, today, segmented=False)
        assert api.get(reverse("training-arc")).data["weeks"] == []

    def test_an_unsegmented_run_does_not_pad_a_real_week(self, api, athlete, today):
        a_run(athlete, today, logged_m=2500.0, run_m=1900.0, run_s=900.0)
        a_run(athlete, today, logged_m=4000.0, segmented=False)
        now = next(w for w in api.get(reverse("training-arc")).data["weeks"] if w["current"])
        assert now["done"]["runs"] == 1, "the raw row is not a second run"
        assert now["done"]["run_m"] == 1900, "and its 4 km never reaches the total"

    def test_a_segmented_run_reports_run_distance_not_logged(self, api, athlete, today):
        a_run(athlete, today, logged_m=2500.0, run_m=1900.0)
        now = next(w for w in api.get(reverse("training-arc")).data["weeks"] if w["current"])
        assert now["done"]["run_m"] == 1900
        assert now["done"]["run_s"] == 900


class TestTheAxisStaysHonest:
    def test_session_duration_never_becomes_a_block(self, api, athlete, today):
        plan = a_plan(athlete)
        ahead = today + dt.timedelta(days=7)
        a_workout(athlete, plan, ahead, duration_s=1800, block_s=600)
        week = next(w for w in api.get(reverse("training-arc")).data["weeks"]
                    if dt.date.fromisoformat(str(w["start"])) <= ahead
                    <= dt.date.fromisoformat(str(w["end"])))
        assert week["planned"]["run_s"] == 1800
        assert week["planned"]["block_s"] == 600, "the longest run step, not the session"

    def test_a_session_with_no_steps_claims_no_block(self, api, athlete, today):
        """Guessing the duration here would put a target on the chart nobody set."""
        plan = a_plan(athlete)
        ahead = today + dt.timedelta(days=7)
        a_workout(athlete, plan, ahead, duration_s=1800, block_s=0)
        week = next(w for w in api.get(reverse("training-arc")).data["weeks"]
                    if dt.date.fromisoformat(str(w["start"])) <= ahead
                    <= dt.date.fromisoformat(str(w["end"])))
        assert week["planned"]["run_s"] == 1800
        assert week["planned"]["block_s"] == 0

    def test_the_block_scale_is_not_stretched_by_a_long_session(self, api, athlete, today):
        plan = a_plan(athlete)
        a_run(athlete, today - dt.timedelta(days=7), longest_s=392.0)
        a_workout(athlete, plan, today + dt.timedelta(days=7), duration_s=3600, block_s=600)
        peak = api.get(reverse("training-arc")).data["peak"]
        assert peak["run_s"] == 3600
        assert peak["block_s"] == 600


class TestGymIsNotRunning:
    def test_strength_counts_as_gym_only(self, api, athlete, today):
        StrengthSession.objects.create(
            athlete=athlete, date=today, title="Full body", duration_s=2400, level=1,
            exercises=[],
        )
        now = next(w for w in api.get(reverse("training-arc")).data["weeks"] if w["current"])
        assert now["planned"]["gym"] == 1
        assert now["planned"]["runs"] == 0
        assert now["planned"]["run_s"] == 0
        assert now["planned"]["block_s"] == 0

    def test_a_strength_kind_workout_is_gym_too(self, api, athlete, today):
        plan = a_plan(athlete)
        a_workout(athlete, plan, today, duration_s=2400, block_s=0, kind="STRENGTH")
        now = next(w for w in api.get(reverse("training-arc")).data["weeks"] if w["current"])
        assert now["planned"]["gym"] == 1 and now["planned"]["runs"] == 0


class TestTheRecord:
    def test_best_holds_after_time_off(self, api, athlete, today):
        a_run(athlete, today - dt.timedelta(days=35), longest_s=699.0)
        a_run(athlete, today, longest_s=392.0)
        weeks = api.get(reverse("training-arc")).data["weeks"]
        assert weeks[-1]["best_run_s"] == 699
        assert next(w for w in weeks if w["current"])["done"]["longest_run_s"] == 392


class TestGoal:
    def test_practice_mode_names_the_next_milestone(self, api, athlete, today):
        a_run(athlete, today, longest_s=392.0)
        goal = api.get(reverse("training-arc")).data["goal"]
        assert goal["kind"] == "practice"
        assert goal["target_s"] > 392, "a milestone already passed is not a target"

    def test_a_race_plan_names_the_race(self, api, athlete, today):
        from apps.planning.models import Race

        race = Race.objects.create(athlete=athlete, name="Cadbury 10k",
                                   date=today + dt.timedelta(days=60), distance_km=10.0)
        plan = a_plan(athlete, name="10k build")
        plan.race = race
        plan.save(update_fields=["race"])
        a_run(athlete, today)
        goal = api.get(reverse("training-arc")).data["goal"]
        assert goal["kind"] == "race" and goal["label"] == "Cadbury 10k"


class TestItIsYours:
    def test_another_athlete_sees_none_of_it(self, api, other_api, athlete, today):
        a_run(athlete, today, longest_s=699.0)
        assert other_api.get(reverse("training-arc")).data["weeks"] == []

    def test_signing_out_closes_it(self, client):
        assert client.get(reverse("training-arc")).status_code in (401, 403)
