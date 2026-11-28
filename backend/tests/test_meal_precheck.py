"""R25: the arithmetic behind "should I eat this?".

`assess_fit` is pure, which is the point of it being separate: the verdict he
sees has to be the same verdict for the same plate on any day, and that is not a
property a model has. Everything here tests the half that must never drift.
"""

from __future__ import annotations

import pytest

from apps.diet.precheck import DEMANDING, FIT_RULES, assess_fit


def day(*, kcal=2400, protein=120, carbs=300, eaten_kcal=0, eaten_protein=0, eaten_carbs=0):
    return {
        "targets": {"kcal": kcal, "protein_g": protein, "carbs_g": carbs, "fat_g": 70},
        "eaten": {"kcal": eaten_kcal, "protein_g": eaten_protein,
                  "carbs_g": eaten_carbs, "fat_g": 0},
    }


def meal(kcal=500.0, protein=25.0, carbs=60.0, fat=15.0):
    return {"kcal": kcal, "protein_g": protein, "carbs_g": carbs, "fat_g": fat}


def session(kind="EASY", *, when="tomorrow", done=False, minutes=40):
    return {"when": when, "title": f"{kind.title()} run", "kind": kind,
            "minutes": minutes, "demanding": kind in DEMANDING, "done": done}


def ctx(sessions=(), ran_today=False):
    return {"ran_today": ran_today, "sessions": list(sessions)}


# --- the verdict --------------------------------------------------------------

def test_a_meal_well_inside_the_day_just_fits():
    fit = assess_fit(day(eaten_kcal=600), meal(kcal=400, protein=5), ctx())
    assert fit["verdict"] == "fits"


def test_a_meal_that_closes_a_protein_gap_is_good():
    fit = assess_fit(day(eaten_kcal=600, eaten_protein=40), meal(kcal=400, protein=40), ctx())
    assert fit["verdict"] == "good"
    assert fit["protein_gap_before_g"] == 80


def test_protein_that_barely_dents_the_gap_does_not_earn_good():
    fit = assess_fit(day(eaten_kcal=600, eaten_protein=40), meal(kcal=400, protein=5), ctx())
    assert fit["verdict"] == "fits"


def test_a_meal_that_eats_most_of_what_is_left_is_heavy():
    fit = assess_fit(day(eaten_kcal=1800), meal(kcal=700, protein=35), ctx())
    assert fit["verdict"] == "heavy"
    assert fit["kcal_left_after"] == -100


def test_a_big_overshoot_is_over_not_merely_heavy():
    fit = assess_fit(day(eaten_kcal=2200), meal(kcal=900), ctx())
    assert fit["verdict"] == "over"
    assert fit["kcal_left_after"] == -700


def test_a_single_huge_meal_is_heavy_even_on_an_empty_day():
    """Nothing eaten yet, so it fits the day's total — but 60% of a day in one
    sitting is still worth saying out loud."""
    fit = assess_fit(day(), meal(kcal=1500, protein=90), ctx())
    assert fit["share_of_day_pct"] == 62  # 1500 of 2400
    assert fit["verdict"] == "heavy"


def test_protein_cannot_rescue_a_meal_that_blows_the_day():
    fit = assess_fit(day(eaten_kcal=2300, eaten_protein=10), meal(kcal=1000, protein=100), ctx())
    assert fit["verdict"] == "over"


def test_every_rule_has_a_reason_and_they_are_all_distinct():
    verdicts = [v for v, _ in FIT_RULES]
    assert len(set(verdicts)) == len(verdicts)
    assert all(reason and not reason.endswith(".") for _, reason in FIT_RULES)


# --- the numbers he is shown --------------------------------------------------

def test_the_numbers_are_the_ones_the_card_prints():
    fit = assess_fit(day(eaten_kcal=1000, eaten_protein=50, eaten_carbs=120),
                     meal(kcal=600, protein=30, carbs=70), ctx())
    assert fit["kcal_left_before"] == 1400
    assert fit["kcal_in_meal"] == 600
    assert fit["kcal_left_after"] == 800
    assert fit["share_of_day_pct"] == 25
    assert fit["protein_gap_before_g"] == 70
    assert fit["carb_gap_before_g"] == 180
    assert fit["carbs_in_meal_g"] == 70


def test_a_gap_already_met_is_zero_not_negative():
    fit = assess_fit(day(eaten_protein=200, eaten_carbs=400), meal(), ctx())
    assert fit["protein_gap_before_g"] == 0
    assert fit["carb_gap_before_g"] == 0


def test_a_zero_target_does_not_divide_by_zero():
    """Targets are zero until the profile has a weight, and he will still ask."""
    fit = assess_fit(day(kcal=0, protein=0, carbs=0), meal(), ctx())
    assert fit["share_of_day_pct"] == 0


# --- the sessions ------------------------------------------------------------

def test_the_next_demanding_session_is_found_past_an_easy_one():
    fit = assess_fit(day(), meal(), ctx([session("EASY", when="today"), session("LONG")]))
    assert fit["next_demanding"]["kind"] == "LONG"
    assert len(fit["upcoming"]) == 2


def test_a_session_already_run_is_not_upcoming():
    fit = assess_fit(day(), meal(), ctx([session("LONG", when="today", done=True)], ran_today=True))
    assert fit["upcoming"] == []
    assert fit["next_demanding"] is None
    assert fit["ran_today"] is True


def test_an_easy_week_has_nothing_demanding():
    fit = assess_fit(day(), meal(), ctx([session("EASY"), session("RUN_WALK")]))
    assert fit["next_demanding"] is None


@pytest.mark.parametrize("kind", sorted(DEMANDING))
def test_demanding_kinds_are_flagged(kind):
    fit = assess_fit(day(), meal(), ctx([session(kind)]))
    assert fit["next_demanding"] is not None


@pytest.mark.parametrize("kind", ["EASY", "WALK", "RUN_WALK", "REST"])
def test_easy_kinds_are_not(kind):
    fit = assess_fit(day(), meal(), ctx([session(kind)]))
    assert fit["next_demanding"] is None


def test_demanding_is_a_subset_of_the_generators_kinds():
    """A typo here would silently stop every long-run carb note from firing."""
    from planning.generator import SessionKind

    assert DEMANDING <= set(SessionKind.__args__)


# --- purity ------------------------------------------------------------------

def test_assess_fit_does_not_mutate_what_it_is_given():
    d, m, c = day(eaten_kcal=500), meal(), ctx([session("LONG")])
    before = (str(d), str(m), str(c))
    assess_fit(d, m, c)
    assert (str(d), str(m), str(c)) == before
