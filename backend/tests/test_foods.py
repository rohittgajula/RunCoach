"""R25: the food table and the day-plan arithmetic.

Everything here is pure. The point of the split is that a model picks food keys
and Python owns every number, so these tests are the numbers.
"""

from __future__ import annotations

import pytest

from apps.diet.dayplan import SLOT_SHARE, _overshoot, _remaining_slots, slot_budgets
from nutrition import foods as F


# --- the table itself ---------------------------------------------------------

def test_keys_are_unique():
    keys = [f.key for f in F.FOODS]
    assert len(keys) == len(set(keys))


def test_every_food_has_plausible_macros():
    """Protein, carbs and fat should roughly account for the calories. A typo in
    a macro is invisible on screen and silently wrong in every plan."""
    for f in F.FOODS:
        from_macros = f.carbs_g * 4 + f.protein_g * 4 + f.fat_g * 9
        assert f.kcal > 0, f.key
        assert abs(from_macros - f.kcal) <= max(35, 0.25 * f.kcal), (
            f"{f.key}: {f.kcal} kcal but macros give {from_macros:.0f}"
        )


def test_no_negative_numbers():
    for f in F.FOODS:
        for field in ("kcal", "carbs_g", "protein_g", "fat_g", "iron_mg",
                      "vitamin_c_mg", "calcium_mg"):
            assert getattr(f, field) >= 0, f"{f.key}.{field}"


def test_haem_iron_only_on_animal_foods():
    """Haem iron is absorbed several times better than plant iron, and the plan
    leans on that distinction. Marking a dal as haem would be advice."""
    for f in F.FOODS:
        if f.haem:
            assert f.pattern in ("egg", "nonveg"), f"{f.key} claims haem iron"


def test_the_iron_blockers_are_real_foods():
    for key in F.IRON_BLOCKERS:
        assert key in F.BY_KEY


# --- who can eat what ---------------------------------------------------------

def test_vegetarian_sees_no_meat_or_egg():
    keys = {f.key for f in F.allowed("veg", "stove")}
    assert "chicken_curry" not in keys and "egg_boiled" not in keys
    assert "dal" in keys


def test_egg_eater_sees_eggs_but_no_meat():
    keys = {f.key for f in F.allowed("egg", "stove")}
    assert "egg_boiled" in keys
    assert "fish_curry" not in keys


def test_patterns_nest():
    """Each tier is a superset of the one above it, which is what lets `allowed`
    take a single ceiling rather than a set."""
    veg = {f.key for f in F.allowed("veg", "stove")}
    egg = {f.key for f in F.allowed("egg", "stove")}
    non = {f.key for f in F.allowed("nonveg", "stove")}
    assert veg < egg < non


def test_prep_nests_too():
    none = {f.key for f in F.allowed("nonveg", "none")}
    kettle = {f.key for f in F.allowed("nonveg", "kettle")}
    stove = {f.key for f in F.allowed("nonveg", "stove")}
    assert none < kettle < stove


def test_no_stove_means_no_boiled_eggs():
    keys = {f.key for f in F.allowed("nonveg", "none")}
    assert "egg_boiled" not in keys
    assert "curd" in keys and "milk" in keys and "peanuts" in keys


def test_someone_with_nothing_can_still_be_fed():
    """A PG resident with no kitchen is the hardest case and the one most likely
    to be handed an empty list by a bug."""
    keys = F.allowed("veg", "none")
    assert len(keys) >= 12
    assert sum(f.protein_g for f in keys) > 0


def test_dislikes_are_removed():
    keys = {f.key for f in F.allowed("nonveg", "stove", frozenset({"idli", "dosa"}))}
    assert "idli" not in keys and "dosa" not in keys


# --- the arithmetic -----------------------------------------------------------

def test_totals_add_up():
    t = F.total([("idli", 3), ("sambar", 1)])
    idli, sambar = F.BY_KEY["idli"], F.BY_KEY["sambar"]
    assert t.kcal == pytest.approx(idli.kcal * 3 + sambar.kcal)
    assert t.protein_g == pytest.approx(idli.protein_g * 3 + sambar.protein_g)


def test_an_unknown_key_is_skipped_not_guessed():
    assert F.total([("nonsense", 2), ("idli", 1)]).kcal == F.BY_KEY["idli"].kcal


def test_portions_are_capped():
    """A model asking for 40 idli should produce a wrong-looking plan, not a
    20,000 kcal one presented as normal."""
    assert F.total([("idli", 40)]).kcal == F.BY_KEY["idli"].kcal * F.MAX_PORTIONS


def test_zero_and_negative_portions_contribute_nothing():
    assert F.total([("idli", 0), ("dosa", -3)]).kcal == 0


def test_haem_iron_is_counted_separately():
    t = F.total([("chicken_curry", 1), ("dal", 1)])
    assert t.haem_iron_mg == pytest.approx(F.BY_KEY["chicken_curry"].iron_mg)
    assert t.iron_mg > t.haem_iron_mg


# --- how a portion reads ------------------------------------------------------

@pytest.mark.parametrize(
    ("key", "n", "expected"),
    [
        ("idli", 3, "3 idli"),
        ("idli", 1, "1 idli"),
        ("sambar", 1, "1 katori sambar"),
        ("sambar", 2, "2 katori sambar"),
        ("egg_boiled", 1, "1 egg"),
        ("egg_boiled", 2, "2 eggs"),
        ("chapati", 3, "3 chapatis"),
        ("chicken_grilled", 1, "150 g grilled chicken"),
        ("dates", 2, "6 dates"),
        ("guava", 1, "1 guava"),
    ],
)
def test_portions_read_like_english(key, n, expected):
    assert F.describe(key, n) == expected


def test_no_portion_phrase_repeats_a_word():
    """"3 chapatis chapati" shipped once, from pluralising before checking
    whether the unit already named the food."""
    for f in F.FOODS:
        for n in (1, 2, 3):
            words = F.describe(f.key, n).lower().split()
            assert len(words) == len(set(words)), f"{f.key} x{n}: {F.describe(f.key, n)}"


def test_every_portion_phrase_identifies_the_food():
    """"1 katori" on its own tells him nothing. Either the unit names the food
    or the food's name follows it."""
    for f in F.FOODS:
        phrase = F.describe(f.key, 1).lower()
        first_word = f.name.lower().split()[0].strip("(,/")
        unit_names_it = any(w in F.SELF_NAMING for w in phrase.split())
        assert unit_names_it or first_word in phrase, f"{f.key}: {phrase}"


# --- the day's budget ---------------------------------------------------------

def test_budgets_spend_the_whole_remaining_day():
    b = slot_budgets({"kcal": 2722, "protein_g": 116}, list(SLOT_SHARE))
    assert sum(v["kcal"] for v in b.values()) == pytest.approx(2722, abs=2)


def test_budgets_renormalise_when_meals_have_passed():
    """Planning from 3pm must spread the whole remaining day over the meals that
    are left, not 75% of it."""
    b = slot_budgets({"kcal": 1500, "protein_g": 70}, ["lunch", "snack", "dinner"])
    assert set(b) == {"lunch", "snack", "dinner"}
    assert sum(v["kcal"] for v in b.values()) == pytest.approx(1500, abs=2)


def test_one_meal_left_gets_the_lot():
    b = slot_budgets({"kcal": 800, "protein_g": 40}, ["dinner"])
    assert b["dinner"] == {"kcal": 800, "protein_g": 40}


def test_no_meals_left_is_no_budget_not_a_crash():
    assert slot_budgets({"kcal": 800, "protein_g": 40}, []) == {}


def test_a_day_already_over_budget_gives_no_negative_budgets():
    b = slot_budgets({"kcal": -400, "protein_g": -10}, ["dinner"])
    assert b["dinner"]["kcal"] == 0 and b["dinner"]["protein_g"] == 0


@pytest.mark.parametrize(
    ("planned", "budget", "expected"),
    [(3484, 2722, 0.28), (2862, 2722, 0.05), (2400, 2722, 0.0), (2722, 2722, 0.0)],
)
def test_overshoot_measures_only_the_overspend(planned, budget, expected):
    assert _overshoot({"kcal": planned}, {"kcal": budget}) == pytest.approx(expected, abs=0.01)


def test_overshoot_on_a_zero_budget_does_not_divide_by_zero():
    assert _overshoot({"kcal": 500}, {"kcal": 0}) == 0.0


# --- which meals are still ahead of him ---------------------------------------

def test_the_whole_day_is_ahead_in_the_morning():
    assert _remaining_slots(set(), 7) == ["breakfast", "lunch", "snack", "dinner"]


def test_a_logged_meal_is_behind_him():
    assert "breakfast" not in _remaining_slots({"breakfast"}, 9)


def test_late_evening_leaves_only_dinner():
    assert _remaining_slots(set(), 21) == ["dinner"]


def test_mid_afternoon_still_allows_a_late_lunch():
    """Generous on purpose: someone asking at 3pm has usually not eaten yet,
    and refusing to plan lunch because of the clock is the app being pedantic."""
    assert "lunch" in _remaining_slots(set(), 15)


# --- turning the model's keys into a plan --------------------------------------

from apps.diet.dayplan import DayPlanOut, PlannedItem, PlannedMeal, _assemble  # noqa: E402

ALL = F.allowed("nonveg", "stove")
SLOTS_LEFT = ["breakfast", "lunch", "snack", "dinner"]
LEFT = {"kcal": 2722, "protein_g": 116, "carbs_g": 434, "fat_g": 58}


def plan_out(meals, headline="A day.", focus=()):
    return DayPlanOut(
        meals=[
            PlannedMeal(slot=slot, items=[PlannedItem(key=k, portions=n) for k, n in items], why="")
            for slot, items in meals
        ],
        headline=headline, focus=list(focus),
    )


def assemble(meals, *, provided=(), staples=(), slots_left=None):
    return _assemble(
        plan_out(meals), ALL, set(provided), set(staples), LEFT, [], None,
        {"enough": False, "short": []}, slots_left if slots_left is not None else SLOTS_LEFT,
    )


def test_pg_needs_both_a_mess_food_and_a_pg_meal():
    """`provided` holds meal slots, not food keys. Testing a food key against it
    shipped once and meant the PG tag never appeared at all."""
    out = assemble(
        [("breakfast", [("idli", 2), ("oats_milk", 1)]),
         ("lunch", [("rice", 2), ("chicken_curry", 1)])],
        provided=["breakfast"],
    )
    breakfast, lunch = out["meals"]
    assert [i["key"] for i in breakfast["items"] if i["from_pg"]] == ["idli"]
    # Oats are not a mess food even at a PG-covered meal.
    assert not [i for i in breakfast["items"] if i["key"] == "oats_milk" and i["from_pg"]]
    # Rice IS a mess food, but lunch is not a meal his PG covers.
    assert not [i for i in lunch["items"] if i["from_pg"]]


def test_no_pg_meals_means_nothing_is_tagged_pg():
    out = assemble([("breakfast", [("idli", 3), ("sambar", 1)])], provided=[])
    assert not any(i["from_pg"] for m in out["meals"] for i in m["items"])


def test_staples_are_marked():
    out = assemble([("breakfast", [("oats_milk", 1), ("idli", 2)])], staples=["oats_milk"])
    marked = [i["key"] for i in out["meals"][0]["items"] if i["staple"]]
    assert marked == ["oats_milk"]


def test_an_invented_key_is_dropped_and_named():
    out = assemble([("breakfast", [("idli", 2), ("quinoa_bowl", 1)])])
    assert [i["key"] for i in out["meals"][0]["items"]] == ["idli"]
    assert out["dropped_keys"] == ["quinoa_bowl"]


def test_a_meal_that_is_already_eaten_is_not_planned():
    out = assemble(
        [("breakfast", [("idli", 3)]), ("dinner", [("rice", 2)])],
        slots_left=["dinner"],
    )
    assert [m["slot"] for m in out["meals"]] == ["dinner"]


def test_totals_are_summed_here_not_taken_from_the_model():
    out = assemble([("breakfast", [("idli", 3), ("sambar", 1)])])
    expected = F.total([("idli", 3), ("sambar", 1)]).rounded()
    assert out["totals"]["kcal"] == expected["kcal"]
    assert out["totals"]["protein_g"] == expected["protein_g"]


def test_a_meal_whose_items_were_all_dropped_does_not_appear_empty():
    out = assemble([("breakfast", [("nonsense", 2)]), ("lunch", [("rice", 1)])])
    assert [m["slot"] for m in out["meals"]] == ["lunch"]


def test_portions_are_clamped_into_the_plan_too():
    out = assemble([("breakfast", [("idli", 99)])])
    assert out["meals"][0]["items"][0]["portions"] == F.MAX_PORTIONS


def test_covers_says_what_fraction_of_the_day_the_plan_is():
    out = assemble([("breakfast", [("idli", 3), ("sambar", 1)])])
    assert out["covers"]["kcal"] == round(100 * out["totals"]["kcal"] / LEFT["kcal"])


def test_haem_iron_is_surfaced_on_the_item():
    out = assemble([("lunch", [("chicken_curry", 1), ("dal", 1)])])
    flags = {i["key"]: i["haem_iron"] for i in out["meals"][0]["items"]}
    assert flags == {"chicken_curry": True, "dal": False}
