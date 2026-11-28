"""South Indian food, in household portions, with the numbers in Python.

The day plan has to say "three idli with sambar" and have that mean descibed
grams of protein. There are two ways to get there: ask a model for the food and
the numbers together, or ask it only for the food and look the numbers up. This
is the lookup.

It matters more here than anywhere else in the app. A meal estimate that is 15%
out is a slightly wrong log entry; a day plan that is 15% out is advice to eat
the wrong amount, repeated every day, with a protein target the athlete then
believes he is hitting. So the model picks from `FOODS` by key and says how many
portions, and every kcal, gram and milligram on screen is summed from this table.
A key the model invents is dropped rather than guessed at.

**Portions are household measures**, because that is how food is actually
served and eaten: one idli, one katori, one glass. Rohit said he does not know
exact weights and would give averages, so asking him — or a model — for grams
would be a false precision.

**Iron and vitamin C are carried per food**, which no other part of the app
needs. They are here because ferritin is the marker most likely to be low in a
runner and the one most affected by what is on the plate: plant (non-haem) iron
is absorbed at a few percent, haem iron from meat, fish and liver at several
times that, vitamin C alongside a meal increases non-haem absorption, and tea or
coffee within about an hour of eating reduces it. That is a real, well-evidenced
set of food interactions, and the only way to act on it is to know which foods
carry which.

Numbers are representative of home/mess cooking with normal oil, rounded to the
precision they deserve. They are a reference table, not a lab assay, and the
day plan says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

#: What a person's diet allows. Ordered: each tier includes everything above it.
Pattern = Literal["veg", "egg", "nonveg"]
PATTERN_ORDER: tuple[Pattern, ...] = ("veg", "egg", "nonveg")

#: What it takes to put the food in front of you.
#: none   — arrives on the PG plate, or is bought ready to eat
#: kettle — hot water only: oats, soaked chana, milk
#: stove  — a burner or induction plate: eggs, dal, upma, sabzi
Prep = Literal["none", "kettle", "stove"]
PREP_ORDER: tuple[Prep, ...] = ("none", "kettle", "stove")

Slot = Literal["breakfast", "lunch", "snack", "dinner"]


@dataclass(frozen=True)
class Food:
    key: str
    name: str
    #: One portion, as it would be said out loud. "2 idli" is two portions of `idli`.
    portion: str
    kcal: float
    carbs_g: float
    protein_g: float
    fat_g: float
    pattern: Pattern
    prep: Prep
    #: Milligrams of iron per portion, and whether it is haem (meat/fish/egg yolk).
    iron_mg: float = 0.0
    haem: bool = False
    #: Milligrams of vitamin C per portion — what helps the iron in the same meal.
    vitamin_c_mg: float = 0.0
    calcium_mg: float = 0.0
    #: Meals this is normally eaten at. Empty = anytime.
    slots: tuple[Slot, ...] = ()
    #: Shown to the athlete as the reason to reach for it.
    note: str = ""
    #: True when a PG/mess kitchen typically serves it, so the plan can say
    #: "this should already be on your plate" rather than "go and make this".
    mess: bool = False


FOODS: tuple[Food, ...] = (
    # --- the PG plate: what a South Indian mess actually serves ---------------
    Food("idli", "Idli", "1 idli", 58, 12.0, 1.9, 0.2, "veg", "none",
         iron_mg=0.3, slots=("breakfast", "dinner"), mess=True,
         note="Steamed, no oil, easy before a run."),
    Food("dosa", "Plain dosa", "1 dosa", 133, 18.0, 3.0, 5.0, "veg", "none",
         iron_mg=0.5, slots=("breakfast", "dinner"), mess=True,
         note="More oil than idli — fine, but not right before intervals."),
    Food("masala_dosa", "Masala dosa", "1 masala dosa", 230, 33.0, 4.5, 8.5, "veg", "none",
         iron_mg=0.8, vitamin_c_mg=6.0, slots=("breakfast", "dinner"), mess=True),
    Food("upma", "Upma", "1 katori", 190, 28.0, 4.5, 6.5, "veg", "stove",
         iron_mg=0.9, slots=("breakfast",), mess=True),
    Food("pongal", "Ven pongal", "1 katori", 215, 30.0, 6.5, 7.5, "veg", "none",
         iron_mg=1.2, slots=("breakfast",), mess=True,
         note="Rice and moong together — more protein than most mess breakfasts."),
    Food("poha", "Poha", "1 katori", 180, 30.0, 3.5, 5.0, "veg", "stove",
         iron_mg=1.4, vitamin_c_mg=4.0, slots=("breakfast",), mess=True,
         note="Flattened rice carries useful iron from its processing."),
    Food("rice", "Cooked rice", "1 katori", 205, 45.0, 4.0, 0.4, "veg", "none",
         iron_mg=0.5, slots=("lunch", "dinner"), mess=True),
    Food("chapati", "Chapati", "1 chapati", 104, 18.0, 3.1, 2.5, "veg", "stove",
         iron_mg=1.0, slots=("lunch", "dinner"), mess=True),
    Food("sambar", "Sambar", "1 katori", 125, 15.0, 5.5, 4.5, "veg", "stove",
         iron_mg=1.3, vitamin_c_mg=8.0, mess=True,
         note="The protein on an idli plate. Ask for a second katori."),
    Food("rasam", "Rasam", "1 katori", 65, 8.0, 2.0, 2.5, "veg", "stove",
         iron_mg=0.8, vitamin_c_mg=12.0, mess=True,
         note="Tamarind and tomato — vitamin C with the meal, which helps the iron."),
    Food("dal", "Dal / pappu", "1 katori", 150, 18.0, 8.5, 4.5, "veg", "stove",
         iron_mg=2.0, slots=("lunch", "dinner"), mess=True,
         note="The cheapest protein on the plate."),
    Food("rajma", "Rajma", "1 katori", 190, 25.0, 9.0, 5.0, "veg", "stove",
         iron_mg=2.6, slots=("lunch", "dinner"),
         note="One of the better plant iron sources."),
    Food("chana_masala", "Chana masala", "1 katori", 200, 26.0, 9.5, 6.0, "veg", "stove",
         iron_mg=2.4, vitamin_c_mg=5.0, slots=("lunch", "dinner")),
    Food("sabzi", "Mixed vegetable sabzi", "1 katori", 110, 12.0, 3.0, 5.5, "veg", "stove",
         iron_mg=1.2, vitamin_c_mg=20.0, slots=("lunch", "dinner"), mess=True),
    Food("palak", "Palak / spinach sabzi", "1 katori", 95, 8.0, 3.5, 5.0, "veg", "stove",
         iron_mg=2.8, vitamin_c_mg=18.0, slots=("lunch", "dinner"),
         note="Iron-rich, but plant iron — eat it with something sour or citrus."),
    Food("curd", "Curd", "1 katori", 90, 6.0, 5.0, 4.5, "veg", "none",
         calcium_mg=200.0, mess=True,
         note="Protein and calcium, and it sits well before a run."),
    Food("buttermilk", "Buttermilk / majjiga", "1 glass", 45, 4.5, 2.5, 1.5, "veg", "none",
         calcium_mg=110.0, mess=True),
    Food("coconut_chutney", "Coconut chutney", "2 tbsp", 90, 3.0, 1.5, 8.0, "veg", "none",
         mess=True, note="Mostly fat. Fine, but it is not the protein on the plate."),
    Food("pickle_papad", "Pickle / papad", "1 small", 45, 4.0, 1.0, 3.0, "veg", "none", mess=True),

    # --- what he can add himself: stove, kettle, or straight off a shelf ------
    Food("egg_boiled", "Boiled egg", "1 egg", 78, 0.6, 6.3, 5.3, "egg", "stove",
         iron_mg=0.9, haem=True,
         note="12 g of protein for two eggs, five minutes, and its iron is the kind you absorb."),
    Food("egg_omelette", "Omelette (2 eggs)", "1 omelette", 200, 2.0, 13.0, 15.0, "egg", "stove",
         iron_mg=1.9, haem=True, vitamin_c_mg=4.0),
    Food("egg_bhurji", "Egg bhurji", "1 katori", 220, 5.0, 13.5, 16.0, "egg", "stove",
         iron_mg=2.1, haem=True, vitamin_c_mg=8.0),
    Food("oats_milk", "Oats with milk", "1 bowl", 230, 33.0, 10.0, 6.0, "veg", "kettle",
         iron_mg=2.1, calcium_mg=160.0, slots=("breakfast", "snack"),
         note="Kettle is enough. Oats carry more protein and iron than any mess breakfast."),
    Food("oats_curd", "Oats with curd", "1 bowl", 215, 30.0, 10.5, 5.5, "veg", "none",
         iron_mg=1.9, calcium_mg=190.0, slots=("breakfast", "snack")),
    Food("milk", "Milk", "1 glass", 150, 12.0, 8.0, 8.0, "veg", "none",
         calcium_mg=300.0, note="8 g of protein, no cooking at all."),
    Food("paneer", "Paneer", "100 g", 265, 3.5, 18.0, 20.0, "veg", "stove",
         calcium_mg=420.0, iron_mg=0.4, slots=("lunch", "dinner"),
         note="The densest vegetarian protein you can buy ready-made."),
    Food("sprouts", "Sprouted moong salad", "1 katori", 125, 20.0, 8.0, 1.0, "veg", "none",
         iron_mg=2.2, vitamin_c_mg=15.0, slots=("snack",),
         note="No cooking, and the lemon on it is doing iron work."),
    Food("peanuts", "Roasted peanuts", "1 fistful", 165, 6.0, 7.5, 13.5, "veg", "none",
         iron_mg=1.3, slots=("snack",)),
    Food("chana_roasted", "Roasted chana", "1 fistful", 130, 20.0, 7.0, 2.0, "veg", "none",
         iron_mg=1.7, slots=("snack",),
         note="Pocket protein. Keeps in a PG room for weeks."),
    Food("banana", "Banana", "1 banana", 105, 27.0, 1.3, 0.3, "veg", "none",
         vitamin_c_mg=10.0, slots=("snack",),
         note="The simplest thing to eat before an early run."),
    Food("dates", "Dates", "3 dates", 70, 18.0, 0.6, 0.1, "veg", "none",
         iron_mg=0.4, slots=("snack",)),
    Food("orange", "Orange / mosambi", "1 orange", 70, 17.0, 1.2, 0.2, "veg", "none",
         vitamin_c_mg=70.0, slots=("snack",),
         note="Eat it with the meal, not after — that is when it helps the iron."),
    Food("guava", "Guava", "1 guava", 68, 14.0, 2.6, 0.9, "veg", "none",
         vitamin_c_mg=125.0, slots=("snack",),
         note="More vitamin C than an orange, and cheap all year."),
    Food("lemon", "Lemon, squeezed over the meal", "1 lemon", 10, 3.0, 0.2, 0.1, "veg", "none",
         vitamin_c_mg=30.0, note="Costs nothing and makes the dal's iron count for more."),

    # --- non-veg, the best answer to both protein and ferritin ---------------
    Food("chicken_curry", "Chicken curry", "1 katori", 245, 5.0, 24.0, 14.0, "nonveg", "stove",
         iron_mg=1.4, haem=True, slots=("lunch", "dinner"),
         note="Haem iron — absorbed several times better than the iron in dal."),
    Food("chicken_grilled", "Grilled chicken", "150 g", 250, 2.0, 38.0, 9.0, "nonveg", "stove",
         iron_mg=1.5, haem=True, slots=("lunch", "dinner"),
         note="The most protein per rupee you will find."),
    Food("fish_curry", "Fish curry", "1 katori", 200, 6.0, 22.0, 10.0, "nonveg", "stove",
         iron_mg=1.1, haem=True, slots=("lunch", "dinner")),
    Food("fish_fry", "Fish fry", "2 pieces", 230, 7.0, 23.0, 12.0, "nonveg", "stove",
         iron_mg=1.2, haem=True, slots=("lunch", "dinner")),
    Food("mutton_curry", "Mutton curry", "1 katori", 290, 4.0, 22.0, 21.0, "nonveg", "stove",
         iron_mg=3.0, haem=True, slots=("lunch", "dinner"),
         note="The highest iron on this list, haem iron at that."),
    Food("egg_curry", "Egg curry (2 eggs)", "1 katori", 265, 8.0, 14.0, 19.0, "egg", "stove",
         iron_mg=2.3, haem=True, vitamin_c_mg=6.0, slots=("lunch", "dinner")),

    # --- drinks, and the one that works against the iron ---------------------
    Food("chai", "Chai with sugar", "1 cup", 90, 12.0, 2.5, 3.0, "veg", "none", mess=True,
         note="Fine — but an hour away from your dal, not with it."),
    Food("filter_coffee", "Filter coffee", "1 cup", 85, 10.0, 3.0, 3.5, "veg", "none", mess=True,
         note="Same as chai: it blunts the iron in the meal it comes with."),
    Food("tender_coconut", "Tender coconut water", "1 glass", 45, 9.0, 0.5, 0.1, "veg", "none",
         vitamin_c_mg=5.0, slots=("snack",)),
)

BY_KEY: dict[str, Food] = {f.key: f for f in FOODS}

#: Tea and coffee, which reduce non-haem iron absorption when drunk with a meal.
IRON_BLOCKERS: frozenset[str] = frozenset({"chai", "filter_coffee"})

#: Portion counts a sane plan stays inside, per food, per day.
MAX_PORTIONS = 6


def allowed(pattern: Pattern, prep: Prep, dislikes: frozenset[str] = frozenset()) -> list[Food]:
    """Every food this person can actually eat and actually produce.

    `pattern` and `prep` are both ceilings: "nonveg" admits veg and egg foods
    too, and a stove admits everything a kettle does.
    """
    pat_ok = set(PATTERN_ORDER[: PATTERN_ORDER.index(pattern) + 1])
    prep_ok = set(PREP_ORDER[: PREP_ORDER.index(prep) + 1])
    return [
        f for f in FOODS
        if f.pattern in pat_ok and f.prep in prep_ok and f.key not in dislikes
    ]


@dataclass(frozen=True)
class Totals:
    kcal: float = 0.0
    carbs_g: float = 0.0
    protein_g: float = 0.0
    fat_g: float = 0.0
    iron_mg: float = 0.0
    haem_iron_mg: float = 0.0
    vitamin_c_mg: float = 0.0
    calcium_mg: float = 0.0

    def rounded(self) -> dict:
        return {
            "kcal": round(self.kcal), "carbs_g": round(self.carbs_g),
            "protein_g": round(self.protein_g), "fat_g": round(self.fat_g),
            "iron_mg": round(self.iron_mg, 1), "haem_iron_mg": round(self.haem_iron_mg, 1),
            "vitamin_c_mg": round(self.vitamin_c_mg), "calcium_mg": round(self.calcium_mg),
        }


def total(items: list[tuple[str, float]]) -> Totals:
    """Sum (food key, portions). Unknown keys are skipped, never guessed at."""
    acc = {k: 0.0 for k in Totals.__dataclass_fields__}
    for key, portions in items:
        food = BY_KEY.get(key)
        if food is None or portions <= 0:
            continue
        n = min(float(portions), MAX_PORTIONS)
        acc["kcal"] += food.kcal * n
        acc["carbs_g"] += food.carbs_g * n
        acc["protein_g"] += food.protein_g * n
        acc["fat_g"] += food.fat_g * n
        acc["iron_mg"] += food.iron_mg * n
        acc["haem_iron_mg"] += food.iron_mg * n if food.haem else 0.0
        acc["vitamin_c_mg"] += food.vitamin_c_mg * n
        acc["calcium_mg"] += food.calcium_mg * n
    return Totals(**acc)


#: Units that already name the food, so "3 idli" needs no second noun. Anything
#: not here is a measure ("katori", "glass", "g") and gets the food's name after
#: it, because "1 katori" on its own tells you nothing about what is in it.
SELF_NAMING: frozenset[str] = frozenset({
    "idli", "dosa", "chapati", "egg", "omelette", "banana", "lemon",
    "dates", "date", "orange", "guava", "masala dosa",
})

#: Only where English insists. "3 idli" and "2 dosa" are what people say.
PLURALS: dict[str, str] = {
    "egg": "eggs", "banana": "bananas", "omelette": "omelettes",
    "chapati": "chapatis", "piece": "pieces", "lemon": "lemons", "fruit": "fruit",
    "glass": "glasses", "bowl": "bowls", "cup": "cups", "katori": "katori",
    "fistful": "fistfuls",
}


def _split_portion(portion: str) -> tuple[float, str]:
    """"3 dates" -> (3, "dates"); "150 g" -> (150, "g"); "1 katori" -> (1, "katori")."""
    head, _, tail = portion.strip().partition(" ")
    try:
        return float(head), (tail or head).strip()
    except ValueError:
        return 1.0, portion.strip()


def _count(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def describe(key: str, portions: float) -> str:
    """"3 idli", "1 katori sambar", "150 g grilled chicken".

    The phrase has to survive being read on a phone with no other context, which
    is why a measure unit always carries the food's name after it. `portions`
    multiplies the portion, so 2 portions of "3 dates" is "6 dates".
    """
    food = BY_KEY[key]
    amount, unit = _split_portion(food.portion)
    total_amount = amount * max(float(portions), 0)

    # Decided on the unit as written, BEFORE pluralising: "chapati" is
    # self-naming and "chapatis" would not have been found in the set.
    self_naming = unit.lower() in SELF_NAMING
    if total_amount != 1:
        unit = PLURALS.get(unit, unit)
    shown = _count(total_amount)

    if self_naming:
        return f"{shown} {unit}"
    if unit == "g":
        return f"{shown} g {food.name.lower()}"
    return f"{shown} {unit} {food.name.lower()}"
