"""What to eat and drink around one run: before, during, after.

Concrete grams and timings rather than "fuel well", because advice a tired runner can't
turn into a breakfast at 6 a.m. is not advice. The bands are the conventional
sports-nutrition ones, deliberately on the conservative side for a beginner's gut.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

HARD_KINDS = {"INTERVALS", "TEMPO", "RACE"}
SWEAT_L_PER_HOUR = 0.8
EARLY_MORNING_BEFORE_HOUR = 8


@dataclass(frozen=True)
class Fueling:
    before: str
    during: str
    after: str
    carbs_g_during_per_h: int | None

    def as_dict(self) -> dict:
        return asdict(self)


def fueling_for(
    kind: str,
    duration_s: float,
    weight_kg: float,
    start_hour: int | None = None,
) -> Fueling:
    """`start_hour` is the planned local start hour when known. Planned workouts have
    no time of day, so with None both the normal and the early-morning option are
    given rather than guessing which applies."""
    minutes = duration_s / 60
    hard = kind in HARD_KINDS
    long_or_hard = hard or kind == "LONG"
    kg = weight_kg

    # --- before -------------------------------------------------------------
    water = "Drink 300–500 ml of water."
    if minutes < 45 and not hard:
        before = f"Optional: a banana or a slice of toast 30–60 min before. {water}"
    else:
        low, high = round(1.0 * kg), round(1.5 * kg)
        main = f"{low}–{high} g carbs 2–3 h before (rice, oats, bread, banana)"
        early = "30 g carbs 30–60 min before (a banana and 2 dates)"
        if start_hour is not None and start_hour < EARLY_MORNING_BEFORE_HOUR:
            before = f"Early start: {early}. {water}"
        elif start_hour is not None:
            before = f"{main}. {water}"
        else:
            before = f"{main} — or, for an early-morning run, {early}. {water}"

    # --- during -------------------------------------------------------------
    if minutes < 60:
        during, carbs_per_h = "Water only — no fuel needed for under an hour.", None
    elif minutes <= 90:
        during, carbs_per_h = (
            "30 g carbs per hour: one gel, or 3 dates, or half a banana every 30 min. "
            "Sip water to thirst.",
            30,
        )
    else:
        during, carbs_per_h = (
            "45–60 g carbs per hour (a gel every 30–40 min, or dates/banana) plus "
            "300–600 mg sodium per hour (electrolyte tab or salted drink). Start in the "
            "first 30 min.",
            45,
        )

    # --- after --------------------------------------------------------------
    rehydrate_l = round(1.5 * SWEAT_L_PER_HOUR * minutes / 60, 1)
    rehydrate = f"Rehydrate with about {rehydrate_l:g} L over the next few hours."
    if long_or_hard:
        after = (
            f"Within 60 min: 20–30 g protein plus about {round(kg)} g carbs "
            f"(e.g. curd rice, milk and a banana, or eggs on toast). {rehydrate}"
        )
    else:
        after = f"A normal meal within 1–2 hours is enough. {rehydrate}"

    return Fueling(before=before, during=during, after=after, carbs_g_during_per_h=carbs_per_h)
