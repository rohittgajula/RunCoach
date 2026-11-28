"""Measured sweat rate. Pure — no Django, no HTTP, no clock, no model.

A sweat test is two weigh-ins either side of a run, plus whatever he drank during
it. That is enough to know his own litres per hour, which is the number every
hydration figure in the app is currently guessing from a three-row table of
population averages (`weather_advice.SWEAT_L_H`).

The guess is not a bad one, but sweat rate varies between people by a factor of
three or more at the same temperature, and no amount of weather data narrows that
down. One honest weigh-in beats the table permanently.

Two things this module deliberately will not do:

* **Match sweat litre for litre.** Above roughly a litre an hour the stomach cannot
  absorb what the skin is losing, and trying is how runners end up nauseous or
  hyponatraemic. The plan replaces most of the loss and caps the rate.
* **Average a bad test away.** A test outside the physiologically possible is a
  mis-entry — clothes on one side and off the other, a duration typed in hours. It
  is rejected with a reason rather than folded into a median, because a median of
  three good tests and one wrong one is wrong.

The error this module cannot catch on its own is a scale set to pounds: 154 lb is
70 kg, both are possible weights, and the resulting rate is plausible but a bit
over twice what it should be — which on a hot long run is the difference between
drinking 400 ml an hour and the 900 ml cap. So `measure` takes `expected_kg`, his
weight as the app already knows it, and refuses a weigh-in that is nowhere near it.
Pass it wherever it is known.
"""

from __future__ import annotations

import datetime as dt
from statistics import median

#: A weight outside this is not his.
MIN_WEIGHT_KG, MAX_WEIGHT_KG = 30.0, 200.0
#: Under 20 minutes the difference is mostly the towel; over 6 hours it is not a run.
MIN_MINUTES, MAX_MINUTES = 20, 360
MAX_DRANK_ML = 5000
#: Outside this a test is arithmetic, not physiology. Elite runners in heat reach
#: about 2.5 L/h; nobody runs 20 minutes and loses under 0.2 L/h.
MIN_RATE_L_H, MAX_RATE_L_H = 0.2, 3.5
#: Losing this share of body weight is where performance goes, and then safety.
DEHYDRATION_PCT = 2.0
SEVERE_PCT = 4.0
#: Below this many minutes, drinking during the run is not advised at all — the
#: loss is small and stopping to drink costs more than it returns. The rest of the
#: app has always applied this (weather_advice.LONG_RUN_FOR_DRINKING_MIN, which is
#: now this constant), and a plan from here has to agree with it: two screens
#: giving different advice about the same run is worse than either answer.
DRINK_FROM_MIN = 45
#: How much of the loss the drinking plan tries to replace while running, and the
#: ceiling the gut imposes regardless of what the skin is doing.
REPLACE_SHARE = 0.80
MAX_DRINK_ML_H = 900
#: Replace about 1.5x the deficit afterwards: some of what you drink leaves again.
AFTER_FACTOR = 1.5
#: A test this old is still his body but may not be his fitness or his acclimatisation.
STALE_DAYS = 365
#: How far a weigh-in may sit from his known weight before it is a mis-entry rather
#: than a change in him. Generous, because the profile weight can be months stale.
WEIGHT_DRIFT_KG = 15.0
#: kg per pound, for naming the likely cause when a weight is about 2.2x too big.
LB_PER_KG = 2.20462
#: Tests are matched to the heat band they were run in. With none in the band we
#: scale the nearest measurement by the table's own ratios — his measured warm rate
#: tells us more about his hot rate than the population's hot average does.
BAND_RATIO = {"cool": 0.5, "warm": 0.8, "hot": 1.2}
BANDS = ("cool", "warm", "hot")


def measure(*, weight_before_kg: float, weight_after_kg: float,
            drank_ml: float, minutes: float,
            expected_kg: float | None = None) -> dict:
    """One test -> his rate for that run. Raises ValueError with a readable reason.

    Sweat is the weight he lost plus everything he drank while losing it: drinking
    a litre and weighing the same means a litre of sweat, not none.

    `expected_kg` is his weight as the app already knows it. Given it, a weigh-in
    far away from it is refused: that is the only way to catch a scale left in
    pounds, which is otherwise a pair of possible weights producing a possible rate.
    """
    for label, kg in (("before", weight_before_kg), ("after", weight_after_kg)):
        if kg is None or not (MIN_WEIGHT_KG <= kg <= MAX_WEIGHT_KG):
            raise ValueError(
                f"The {label} weight ({kg} kg) is outside {MIN_WEIGHT_KG:.0f}–"
                f"{MAX_WEIGHT_KG:.0f} kg."
            )

    if expected_kg and MIN_WEIGHT_KG <= expected_kg <= MAX_WEIGHT_KG:
        drift = abs(weight_before_kg - expected_kg)
        if drift > WEIGHT_DRIFT_KG:
            # Name the cause when the numbers say it outright, rather than making him
            # work out why a weight he really typed was refused.
            in_lb = abs(weight_before_kg / LB_PER_KG - expected_kg)
            hint = (" That is almost exactly your weight in pounds — check the scale's"
                    " units." if in_lb <= WEIGHT_DRIFT_KG else
                    f" Your weight is on file as {expected_kg:g} kg.")
            raise ValueError(
                f"{weight_before_kg:g} kg is {drift:.0f} kg from what you normally "
                f"weigh.{hint}"
            )
    if not (MIN_MINUTES <= minutes <= MAX_MINUTES):
        raise ValueError(
            f"A sweat test needs a run between {MIN_MINUTES} and {MAX_MINUTES} minutes"
            f" — {minutes:g} is outside that."
        )
    if not (0 <= drank_ml <= MAX_DRANK_ML):
        raise ValueError(f"{drank_ml:g} ml drunk is outside 0–{MAX_DRANK_ML} ml.")

    sweat_l = (weight_before_kg - weight_after_kg) + drank_ml / 1000.0
    if sweat_l <= 0:
        raise ValueError(
            "That works out to no sweat at all — heavier afterwards than the fluid "
            "drunk accounts for. Check the two weights are the right way round."
        )

    rate = sweat_l / (minutes / 60.0)
    if not (MIN_RATE_L_H <= rate <= MAX_RATE_L_H):
        raise ValueError(
            f"That comes to {rate:.1f} L per hour, outside the possible "
            f"{MIN_RATE_L_H}–{MAX_RATE_L_H}. Check the weights, the units and the "
            "duration — one of the three is off."
        )

    # Of the weight he actually lost, not of the sweat: the fluid he drank is back
    # in him, so it never counted against him.
    pct = (weight_before_kg - weight_after_kg) / weight_before_kg * 100.0
    flag = "severe" if pct >= SEVERE_PCT else "dehydrated" if pct >= DEHYDRATION_PCT else None

    return {
        "sweat_l": round(sweat_l, 2),
        "rate_l_h": round(rate, 2),
        "pct_lost": round(pct, 1),
        "flag": flag,
    }


def _usable(tests: list[dict], today: dt.date | None) -> list[dict]:
    if today is None:
        return list(tests)
    cutoff = today - dt.timedelta(days=STALE_DAYS)
    return [t for t in tests if t.get("done_on") is None or t["done_on"] >= cutoff]


def rate_for_band(tests: list[dict], band: str, *, today: dt.date | None = None) -> dict | None:
    """His litres per hour for one heat band, or None if he has never tested.

    `tests` are dicts with `rate_l_h`, and optionally `band` and `done_on`. The
    median is used rather than the mean: four good tests and one unusual day should
    not move the number much, and with two tests the mean and median agree anyway.
    """
    usable = _usable(tests, today)
    if not usable:
        return None
    if band not in BAND_RATIO:
        raise ValueError(f"{band!r} is not one of {BANDS}.")

    same = [t["rate_l_h"] for t in usable if t.get("band") == band]
    if same:
        return {"rate_l_h": round(median(same), 2), "source": "measured",
                "from_band": band, "tests": len(same)}

    # Nothing in this band. Scale from whichever band he has tested most in — more
    # tests beats a closer band, because the scaling is the smaller error.
    counts = {b: [t["rate_l_h"] for t in usable if t.get("band") == b] for b in BANDS}
    best = max((b for b in BANDS if counts[b]), key=lambda b: len(counts[b]), default=None)
    if best is None:
        # Tests with no band recorded at all: better than the table, worse than a match.
        rates = [t["rate_l_h"] for t in usable]
        return {"rate_l_h": round(median(rates), 2), "source": "unbanded",
                "from_band": None, "tests": len(rates)}

    scaled = median(counts[best]) * BAND_RATIO[band] / BAND_RATIO[best]
    return {"rate_l_h": round(min(max(scaled, MIN_RATE_L_H), MAX_RATE_L_H), 2),
            "source": "scaled", "from_band": best, "tests": len(counts[best])}


def drink_plan(rate_l_h: float, minutes: float | None) -> dict:
    """What to drink while running at a known sweat rate, and what to replace after.

    `during_ml_per_h` is deliberately less than the sweat rate and capped: the aim is
    to finish under the 2% loss where performance falls off, not to break even. It
    is zero for a run shorter than `DRINK_FROM_MIN`, matching the rest of the app.

    `minutes=None` asks for the rate in the abstract ("on a long run, drink this"),
    so the short-run rule does not apply to it.
    """
    if minutes is not None and minutes < DRINK_FROM_MIN:
        return {"during_ml_per_h": 0, "rate_l_h": round(rate_l_h, 2),
                "sweat_l": round(rate_l_h * minutes / 60.0, 2), "after_ml": 0,
                "too_short": True}
    during = min(rate_l_h * 1000 * REPLACE_SHARE, MAX_DRINK_ML_H)
    out = {"during_ml_per_h": int(round(during / 50) * 50), "rate_l_h": round(rate_l_h, 2),
           "too_short": False}
    if minutes:
        sweat_l = rate_l_h * minutes / 60.0
        deficit_l = max(sweat_l - during * (minutes / 60.0) / 1000.0, 0.0)
        out["sweat_l"] = round(sweat_l, 2)
        out["after_ml"] = int(round(deficit_l * 1000 * AFTER_FACTOR / 50) * 50)
    return out


def loss_at(rate_l_h: float, minutes: float, weight_kg: float,
            drink_ml_per_h: float = 0.0) -> dict:
    """Where he ends up after a given run drinking a given amount — the number that
    makes a long hot run in India an actual decision rather than a vibe."""
    sweat_l = rate_l_h * minutes / 60.0
    drunk_l = drink_ml_per_h * minutes / 60.0 / 1000.0
    deficit_l = sweat_l - drunk_l
    pct = deficit_l / weight_kg * 100.0
    return {
        "sweat_l": round(sweat_l, 2),
        "deficit_l": round(deficit_l, 2),
        "pct_lost": round(pct, 1),
        "flag": "severe" if pct >= SEVERE_PCT else "dehydrated" if pct >= DEHYDRATION_PCT else None,
    }
