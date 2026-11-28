"""R26: measured sweat rate — the arithmetic, and what it refuses.

The interesting tests here are the refusals and the pounds case. A sweat test is
two numbers he types after a long run in the heat, and the failure mode is not a
crash: it is a plausible rate that is twice his real one, which tells him to drink
the cap when he needs half of it. On a hot Indian long run that is the wrong end of
the only safety number in the app.
"""

from __future__ import annotations

import datetime as dt

import pytest

from analysis import sweat, weather_advice

TODAY = dt.date(2026, 11, 28)


def test_sweat_is_weight_lost_plus_what_he_drank():
    """Drinking a litre and weighing the same means a litre of sweat, not none —
    the mistake that makes every well-hydrated runner look like a non-sweater."""
    out = sweat.measure(weight_before_kg=70.0, weight_after_kg=70.0,
                        drank_ml=1000, minutes=60)
    assert out["sweat_l"] == 1.0
    assert out["rate_l_h"] == 1.0
    # He never got lighter, so he never got dehydrated.
    assert out["pct_lost"] == 0.0 and out["flag"] is None


def test_a_real_indian_long_run():
    out = sweat.measure(weight_before_kg=70.0, weight_after_kg=68.8,
                        drank_ml=500, minutes=90)
    assert out["sweat_l"] == 1.7
    assert out["rate_l_h"] == 1.13
    assert out["pct_lost"] == 1.7


@pytest.mark.parametrize(
    ("kw", "because"),
    [
        (dict(weight_before_kg=70.0, weight_after_kg=70.2, drank_ml=0, minutes=90),
         "no sweat at all"),
        (dict(weight_before_kg=70.0, weight_after_kg=69.9, drank_ml=0, minutes=300),
         "L per hour"),
        (dict(weight_before_kg=70.0, weight_after_kg=66.0, drank_ml=0, minutes=30),
         "L per hour"),
        (dict(weight_before_kg=20.0, weight_after_kg=19.0, drank_ml=0, minutes=60),
         "outside"),
        (dict(weight_before_kg=70.0, weight_after_kg=69.0, drank_ml=0, minutes=5),
         "between"),
        (dict(weight_before_kg=70.0, weight_after_kg=69.0, drank_ml=99_999, minutes=60),
         "outside"),
    ],
)
def test_an_impossible_test_is_refused_with_a_reason(kw, because):
    with pytest.raises(ValueError, match=because):
        sweat.measure(**kw)


# --- the one a single test cannot catch ---------------------------------------

def test_a_scale_in_pounds_is_caught_by_his_known_weight():
    """154 lb and 151 lb are 70 kg and 68.5 kg. Both are possible weights and the
    rate they produce (2.3 L/h) is possible too — so nothing inside the test itself
    can tell. His profile weight can, and the message says which."""
    with pytest.raises(ValueError, match="in pounds"):
        sweat.measure(weight_before_kg=154.0, weight_after_kg=151.0,
                      drank_ml=500, minutes=90, expected_kg=70.0)


def test_without_his_weight_the_pounds_test_is_accepted_and_that_is_the_point():
    """Documenting the hole rather than pretending it is closed: with no profile
    weight there is nothing to compare against, so this passes. Every caller that
    knows his weight must pass it."""
    out = sweat.measure(weight_before_kg=154.0, weight_after_kg=151.0,
                        drank_ml=500, minutes=90)
    assert out["rate_l_h"] > sweat.MAX_RATE_L_H / 2


def test_a_weight_merely_off_is_refused_without_blaming_the_units():
    with pytest.raises(ValueError, match="on file as 70 kg"):
        sweat.measure(weight_before_kg=92.0, weight_after_kg=90.8,
                      drank_ml=500, minutes=90, expected_kg=70.0)


def test_normal_drift_from_the_profile_weight_is_fine():
    """The profile weight can be months stale. Three kg is him, not a typo."""
    out = sweat.measure(weight_before_kg=73.0, weight_after_kg=71.8,
                        drank_ml=500, minutes=90, expected_kg=70.0)
    assert out["rate_l_h"] == 1.13


def test_an_implausible_profile_weight_is_ignored_not_trusted():
    """A junk profile weight must not be able to refuse a good test."""
    out = sweat.measure(weight_before_kg=70.0, weight_after_kg=68.8,
                        drank_ml=500, minutes=90, expected_kg=2.0)
    assert out["rate_l_h"] == 1.13


# --- the dehydration flag ----------------------------------------------------

@pytest.mark.parametrize(
    ("after", "flag"),
    [(69.5, None), (68.5, "dehydrated"), (67.0, "severe")],
)
def test_the_flag_tracks_weight_actually_lost(after, flag):
    out = sweat.measure(weight_before_kg=70.0, weight_after_kg=after,
                        drank_ml=0, minutes=90)
    assert out["flag"] == flag


def test_drinking_enough_clears_the_flag_at_the_same_sweat_rate():
    """Two runs, identical sweat. The one where he drank is not the dehydrated one,
    which is the whole reason the flag reads weight lost and not sweat produced."""
    # Both lost 1.5 L of sweat: 70 -> 68.5 drinking nothing, 70 -> 69.3 having
    # drunk 800 ml (1.5 kg out, 0.8 kg back in).
    dry = sweat.measure(weight_before_kg=70.0, weight_after_kg=68.5, drank_ml=0, minutes=90)
    wet = sweat.measure(weight_before_kg=70.0, weight_after_kg=69.3, drank_ml=800, minutes=90)
    assert dry["rate_l_h"] == wet["rate_l_h"]
    assert dry["flag"] == "dehydrated" and wet["flag"] is None


# --- which tests count, and for which weather --------------------------------

def t(rate, band="hot", done_on=None):
    return {"rate_l_h": rate, "band": band, "done_on": done_on}


def test_no_tests_means_no_measured_rate():
    assert sweat.rate_for_band([], "hot") is None


def test_the_median_is_used_so_one_odd_day_does_not_move_it():
    tests = [t(1.1), t(1.2), t(1.3), t(3.4)]
    out = sweat.rate_for_band(tests, "hot")
    assert out["rate_l_h"] == 1.25 and out["source"] == "measured"


def test_another_bands_measurement_beats_the_population_table():
    """He has only ever tested in the heat. His cool-weather rate scaled from his
    own hot rate is a better guess than the table's cool average."""
    out = sweat.rate_for_band([t(1.2, "hot"), t(1.3, "hot")], "cool")
    assert out["source"] == "scaled" and out["from_band"] == "hot"
    assert out["rate_l_h"] == pytest.approx(0.52, abs=0.01)
    assert out["rate_l_h"] != weather_advice.SWEAT_L_H["cool"]


def test_the_band_with_the_most_tests_is_scaled_from():
    out = sweat.rate_for_band([t(1.2, "warm"), t(1.25, "warm"), t(2.0, "cool")], "hot")
    assert out["from_band"] == "warm" and out["tests"] == 2


def test_tests_with_no_band_are_still_better_than_nothing():
    out = sweat.rate_for_band([t(1.0, None), t(1.2, None)], "hot")
    assert out["source"] == "unbanded" and out["rate_l_h"] == 1.1


def test_a_stale_test_is_not_used():
    old = TODAY - dt.timedelta(days=sweat.STALE_DAYS + 1)
    assert sweat.rate_for_band([t(1.2, "hot", old)], "hot", today=TODAY) is None


def test_a_scaled_rate_cannot_leave_the_possible_range():
    out = sweat.rate_for_band([t(3.4, "cool")], "hot")
    assert out["rate_l_h"] <= sweat.MAX_RATE_L_H


# --- the drinking plan -------------------------------------------------------

def test_the_plan_does_not_try_to_match_sweat_litre_for_litre():
    """Above about a litre an hour the gut cannot keep up, and trying is how people
    end up nauseous or hyponatraemic."""
    plan = sweat.drink_plan(2.5, 120)
    assert plan["during_ml_per_h"] == sweat.MAX_DRINK_ML_H
    assert plan["during_ml_per_h"] < 2.5 * 1000


def test_a_light_sweater_is_not_told_to_drink_a_heavy_sweaters_amount():
    light = sweat.drink_plan(0.5, 60)["during_ml_per_h"]
    heavy = sweat.drink_plan(1.5, 60)["during_ml_per_h"]
    assert light < heavy
    # And the table would have given them the same number for the same weather.
    assert light == 400


def test_the_after_figure_replaces_only_what_is_still_missing():
    plan = sweat.drink_plan(1.13, 90)
    assert plan["after_ml"] == 500


# --- what the run will actually cost him -------------------------------------

def test_a_long_hot_run_drinking_nothing_is_flagged():
    out = sweat.loss_at(1.13, 90, 70.0, 0.0)
    assert out["pct_lost"] == 2.4 and out["flag"] == "dehydrated"


def test_following_the_plan_clears_it():
    out = sweat.loss_at(1.13, 90, 70.0, 900)
    assert out["flag"] is None and out["pct_lost"] < sweat.DEHYDRATION_PCT


# --- the seam into the existing weather advice -------------------------------

def test_hydration_is_unchanged_when_he_has_not_tested():
    """The table path must stay exactly as it was, down to the rounding — this
    feature is an addition, not a change to what every other screen already says."""
    for band in ("cool", "warm", "hot", "very_hot"):
        for minutes in (None, 30, 60, 120):
            out = weather_advice.hydration(band, minutes)
            base = "hot" if band == "very_hot" else band
            expected = (weather_advice.DURING_ML_H[base]
                        if minutes is None or minutes >= weather_advice.LONG_RUN_FOR_DRINKING_MIN
                        else 0)
            assert out["during_ml_per_h"] == expected
            assert out["measured"] is False


def test_hydration_uses_his_rate_when_he_has_one():
    table = weather_advice.hydration("hot", 90)
    mine = weather_advice.hydration("hot", 90, measured_l_h=0.6)
    assert mine["measured"] is True and table["measured"] is False
    assert mine["during_ml_per_h"] < table["during_ml_per_h"]
    assert mine["sweat_l_h"] == 0.6
    assert table["sweat_l_h"] == weather_advice.SWEAT_L_H["hot"]


def test_a_short_run_still_needs_no_drinking_whatever_his_rate():
    assert weather_advice.hydration("hot", 20, measured_l_h=2.0)["during_ml_per_h"] == 0


def test_every_band_in_the_table_can_be_scaled_between():
    """A band in SWEAT_L_H with no entry in BAND_RATIO would raise on scaling."""
    for band in weather_advice.SWEAT_L_H:
        assert band in sweat.BAND_RATIO
    assert set(sweat.BANDS) == set(sweat.BAND_RATIO)


# --- the endpoints -----------------------------------------------------------

from apps.health.models import SweatTest  # noqa: E402
from apps.health.sweat_service import measured_rate  # noqa: E402

from .r7_helpers import make_workout  # noqa: E402

GOOD = {"weight_before_kg": 70.0, "weight_after_kg": 68.8, "drank_ml": 500, "minutes": 90}


def post(api, athlete, **over):
    body = {"done_on": str(athlete.local_today), **GOOD, **over}
    return api.post("/api/health/sweat/", body, format="json")


def test_a_test_is_stored_and_comes_back_measured(api, athlete):
    res = post(api, athlete, feels_like_c=33.0)
    assert res.status_code == 201, res.data
    assert res.data["rate_l_h"] == 1.13
    assert res.data["band"] == "hot"          # 33 C is over HOT_FEELS_C
    assert res.data["usable"] is True


def test_the_band_comes_from_the_temperature_he_gives(api, athlete):
    post(api, athlete, feels_like_c=20.0)
    assert SweatTest.objects.get(athlete=athlete).band == "cool"


def test_a_past_run_with_no_temperature_is_stored_without_a_band(api, athlete):
    """The forecast API cannot be asked about last Tuesday, and guessing would file
    the test under a band it was not run in."""
    res = post(api, athlete, done_on=str(athlete.local_today - dt.timedelta(days=9)))
    assert res.status_code == 201
    assert res.data["band"] is None


def test_an_impossible_test_is_a_400_with_the_reason(api, athlete):
    res = post(api, athlete, weight_after_kg=70.5, drank_ml=0)
    assert res.status_code == 400
    assert "no sweat at all" in res.data["detail"]
    assert not SweatTest.objects.filter(athlete=athlete).exists()


def test_pounds_are_caught_once_his_weight_is_on_file(api, athlete):
    athlete.weight_kg = 70.0
    athlete.save(update_fields=["weight_kg"])
    res = post(api, athlete, weight_before_kg=154.0, weight_after_kg=151.0)
    assert res.status_code == 400
    assert "in pounds" in res.data["detail"]


def test_a_future_date_is_refused(api, athlete):
    res = post(api, athlete, done_on=str(athlete.local_today + dt.timedelta(days=4)))
    assert res.status_code == 400


def test_the_list_shows_his_rate_against_the_table(api, athlete):
    post(api, athlete, feels_like_c=33.0)
    body = api.get("/api/health/sweat/").json()
    hot = body["rates"]["hot"]
    assert hot["table_l_h"] == weather_advice.SWEAT_L_H["hot"]
    assert hot["measured"]["rate_l_h"] == 1.13
    assert hot["measured"]["source"] == "measured"
    # Scaled, not the table, for a band he has not tested in.
    assert body["rates"]["cool"]["measured"]["source"] == "scaled"


def test_with_no_tests_the_list_is_honest_about_having_none(api, athlete):
    body = api.get("/api/health/sweat/").json()
    assert body["tests"] == []
    assert all(b["measured"] is None for b in body["rates"].values())
    assert all(b["table_l_h"] for b in body["rates"].values())
    assert body["standing_note"]


def test_todays_run_is_costed_in_fluid(api, athlete):
    """The point of the feature: not "drink a lot" but "this run leaves you 2.7%
    down if you drink nothing, and fine if you follow the plan"."""
    athlete.weight_kg = 70.0
    athlete.save(update_fields=["weight_kg"])
    make_workout(athlete, kind="LONG", steps=[{"kind": "run", "duration_s": 150 * 60}])
    post(api, athlete, feels_like_c=33.0)
    today = api.get("/api/health/sweat/").json()["today"]
    assert today is not None
    assert today["if_you_drink_nothing"]["flag"] == "dehydrated"
    assert today["if_you_follow_the_plan"]["flag"] is None


def test_a_rate_scaled_from_another_band_does_not_claim_to_be_a_measurement(api, athlete):
    """He tested in the heat; there is no weather for today in a test, so the band
    falls back to warm and his rate is scaled. The screen must be able to say that
    rather than present it as today's own number."""
    make_workout(athlete, kind="LONG", steps=[{"kind": "run", "duration_s": 90 * 60}])
    post(api, athlete, feels_like_c=33.0)
    today = api.get("/api/health/sweat/").json()["today"]
    assert today["source"] == "scaled" and today["from_band"] == "hot"
    assert today["feels_like_c"] is None


def test_with_no_test_at_all_todays_plan_says_it_is_the_table(api, athlete):
    make_workout(athlete, kind="LONG", steps=[{"kind": "run", "duration_s": 90 * 60}])
    today = api.get("/api/health/sweat/").json()["today"]
    assert today["source"] == "table" and today["from_band"] is None


def test_no_run_today_means_no_plan_rather_than_a_made_up_one(api, athlete):
    post(api, athlete, feels_like_c=33.0)
    assert api.get("/api/health/sweat/").json()["today"] is None


def test_a_test_can_be_removed(api, athlete):
    pk = post(api, athlete).data["id"]
    assert api.delete(f"/api/health/sweat/{pk}/").status_code == 204
    assert not SweatTest.objects.filter(athlete=athlete).exists()
    assert api.delete(f"/api/health/sweat/{pk}/").status_code == 404


def test_another_athletes_test_is_not_visible_or_deletable(api, athlete, django_user_model):
    other = django_user_model.objects.create_user("other", password="correct-horse-battery-2")
    from apps.athletes.models import Athlete

    mine = SweatTest.objects.create(
        athlete=Athlete.objects.create(user=other, display_name="Other",
                                       timezone="Asia/Kolkata"),
        done_on=athlete.local_today, weight_before_kg=70.0, weight_after_kg=68.8,
        drank_ml=500, minutes=90,
    )
    assert api.get("/api/health/sweat/").json()["tests"] == []
    assert api.delete(f"/api/health/sweat/{mine.pk}/").status_code == 404


def test_the_service_hands_the_rate_to_everything_else(api, athlete):
    """`measured_rate` is what weather advice and the race-day fuel plan call. None
    before a test means those screens keep their old table answer."""
    assert measured_rate(athlete, "hot") is None
    post(api, athlete, feels_like_c=33.0)
    assert measured_rate(athlete, "hot") == 1.13
    assert measured_rate(athlete, "nonsense") is None


# --- the short-run rule, shared with the weather advice ----------------------

def test_a_run_too_short_to_drink_on_gets_no_drinking_plan():
    """The rest of the app has always said drink nothing under 45 minutes. A plan
    built from his measured rate has to agree: two screens giving different advice
    about the same run is worse than either answer on its own."""
    plan = sweat.drink_plan(1.2, 30)
    assert plan["during_ml_per_h"] == 0 and plan["too_short"] is True
    assert plan["sweat_l"] == 0.6


def test_at_the_threshold_drinking_starts():
    assert sweat.drink_plan(1.2, sweat.DRINK_FROM_MIN)["during_ml_per_h"] > 0
    assert sweat.drink_plan(1.2, sweat.DRINK_FROM_MIN - 1)["during_ml_per_h"] == 0


def test_the_rate_in_the_abstract_is_not_subject_to_the_short_run_rule():
    """`minutes=None` asks "on a long run, how much?" — the per-band figure."""
    plan = sweat.drink_plan(1.2, None)
    assert plan["during_ml_per_h"] > 0 and plan["too_short"] is False


def test_the_threshold_has_one_definition():
    """It used to live only in weather_advice. Two copies would drift, and the
    symptom would be two screens disagreeing about the same run."""
    assert weather_advice.LONG_RUN_FOR_DRINKING_MIN is sweat.DRINK_FROM_MIN


def test_the_sweat_screen_and_the_weather_advice_agree_about_one_run():
    """The regression this pair of modules exists to prevent, asserted directly."""
    for minutes in (20, 44, 45, 90, 180):
        weather = weather_advice.hydration("hot", minutes, measured_l_h=1.2)
        screen = sweat.drink_plan(1.2, minutes)
        assert weather["during_ml_per_h"] == screen["during_ml_per_h"], minutes
