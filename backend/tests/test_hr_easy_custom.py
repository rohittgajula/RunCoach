"""Heart-rate zones that match the Garmin watch, and the athlete's own easy-run range.

Rohit's watch (percent of max, 193) says zone 2 = 116-134, while the app's
heart-rate-reserve zones sent run steps at 144-156. He now picks "same as Garmin"
zones and his own easy range (135-148, walk above 155); future workouts follow.
"""

import pytest

from analysis.zones import build_percent_max
from apps.planning.models import PlannedWorkout
from apps.planning.plan_store import bands_for
from apps.planning.presenters import guard_base
from apps.planning.reband import reband_steps
from tests.r7_helpers import make_workout, run_walk_steps, tomorrow


def test_percent_max_matches_garmin_watch():
    zones = build_percent_max(193, 61)
    got = [(z.name, z.low, z.high) for z in zones.zones]
    assert got == [("Z1", 97, 115), ("Z2", 116, 134), ("Z3", 135, 153),
                   ("Z4", 154, 173), ("Z5", 174, 193)]
    assert zones.source == "percent_of_max"
    assert zones.of(134) == "Z2" and zones.of(135) == "Z3"


def test_percent_max_refuses_nonsense():
    assert build_percent_max(0) is None and build_percent_max(90) is None


@pytest.mark.django_db
def test_athlete_zones_use_chosen_method(athlete):
    athlete.max_hr, athlete.resting_hr = 193, 61
    athlete.zones_source = "percent_of_max"
    athlete.save()
    assert athlete.zones().band("Z2").low == 116
    athlete.zones_source = "heart_rate_reserve"
    athlete.save()
    assert athlete.zones().band("Z2").low == 140      # 61 + 0.6 x 132


@pytest.mark.django_db
def test_own_easy_range_wins_everywhere(athlete):
    athlete.max_hr, athlete.resting_hr = 193, 61
    athlete.hr_easy_custom = True
    athlete.hr_easy_min, athlete.hr_easy_max, athlete.hr_ceiling = 135, 148, 155
    athlete.save()
    bands = bands_for(athlete)
    assert bands.hr_easy == (135, 148)
    assert bands.hr_moderate[0] == 148
    assert athlete.easy_hr_band() == (135, 148)
    assert guard_base(athlete)["z2_high"] == 148


@pytest.mark.django_db
def test_without_own_range_zone2_decides(athlete):
    athlete.max_hr, athlete.resting_hr, athlete.zones_source = 193, 61, "percent_of_max"
    athlete.save()
    assert bands_for(athlete).hr_easy == (116, 134)
    assert athlete.easy_hr_band() == (116, 134)


class _Bands:
    hr_easy, hr_moderate, hr_hard = (135, 148), (148, 155), None


def test_reband_steps_leaves_walks_and_edited_steps():
    steps = run_walk_steps(2, hr=(144, 156))
    steps.append({"kind": "run", "duration_s": 60, "intensity": "easy", "label": "Mine",
                  "hr_min": 120, "hr_max": 130, "target": "hr"})
    out, changed = reband_steps(steps, _Bands)
    assert changed
    runs = [s for s in out if s["intensity"] == "easy" and not s.get("target")]
    assert all((s["hr_min"], s["hr_max"]) == (135, 148) for s in runs)
    assert all(s["hr_max"] is None for s in out if s["intensity"] == "walk")
    assert (out[-1]["hr_min"], out[-1]["hr_max"]) == (120, 130)


def test_reband_never_harder_on_eased_day():
    out, _ = reband_steps(run_walk_steps(1, hr=(125, 140)), _Bands, eased=True)
    run = next(s for s in out if s["intensity"] == "easy")
    assert (run["hr_min"], run["hr_max"]) == (125, 140)


@pytest.mark.django_db
def test_settings_save_rebands_future_workouts(api, athlete):
    athlete.max_hr, athlete.resting_hr = 193, 61
    athlete.save()
    future = make_workout(athlete, tomorrow(athlete), steps=run_walk_steps(3, hr=(144, 156)))
    done = make_workout(athlete, tomorrow(athlete, 2), steps=run_walk_steps(3, hr=(144, 156)),
                        status="completed")
    r = api.patch("/api/athlete/", {"zones_source": "percent_of_max", "hr_easy_custom": True,
                                    "hr_easy_min": 135, "hr_easy_max": 148,
                                    "hr_ceiling": 155}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["hr_reband"]["updated"] == 1
    assert r.json()["zones"]["source"] == "percent_of_max"
    future.refresh_from_db()
    done.refresh_from_db()
    run = next(s for s in future.steps if s["intensity"] == "easy")
    assert (run["hr_min"], run["hr_max"]) == (135, 148)
    assert next(s for s in done.steps if s["intensity"] == "easy")["hr_max"] == 156
    assert PlannedWorkout.objects.count() == 2


@pytest.mark.django_db
def test_unrelated_save_does_not_reband(api, athlete):
    r = api.patch("/api/athlete/", {"display_name": "Rohit"}, format="json")
    assert r.status_code == 200 and r.json()["hr_reband"] is None


@pytest.mark.django_db
def test_band_order_still_validated(api, athlete):
    r = api.patch("/api/athlete/", {"hr_easy_custom": True, "hr_easy_min": 150,
                                    "hr_easy_max": 148}, format="json")
    assert r.status_code == 400


@pytest.mark.django_db
def test_rezone_task_recounts_time_in_zone(athlete):
    from apps.activities.tasks import rezone_athlete

    athlete.max_hr, athlete.resting_hr = 193, 61
    athlete.save()
    assert rezone_athlete(athlete.pk) == {"rezoned": 0}
