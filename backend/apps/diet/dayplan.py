"""What to eat today, and what has been missing.

Two questions, deliberately answered by different machinery.

**"What has been missing"** is arithmetic over the last two weeks and uses no
model at all. Whether his protein has averaged 60 g against a 116 g target is a
fact; dressing it up as an opinion would only make it easier to argue with.
`shortfalls()` is pure and returns the numbers.

**"What to eat today"** needs the model, but only for the part that is taste and
arrangement: which foods, at which meal, in what combination. Every number comes
from `nutrition.foods`. The model answers with food KEYS and portion counts, and
Python looks up and sums the macros — so a model that is wrong about nutrition
cannot be wrong about his day, only about whether he fancies idli.

Three things shape the plan beyond the macros:

* **What the PG serves.** Meals he has no say over are planned around, not
  rewritten. A plan that opens by telling him to cook his own breakfast when
  breakfast is already paid for and waiting downstairs is a plan he closes.
* **His staples.** He said oats and a couple of eggs daily. Those go in every
  plan as fixed points rather than being re-suggested as though they were the
  app's idea.
* **His bloods.** A flagged ferritin changes which of two equally adequate days
  is the better one, and the iron arithmetic -- haem versus non-haem, vitamin C
  in the same meal, tea and coffee an hour away from it -- is carried per food
  in the table.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Literal

from pydantic import BaseModel, Field

from analysis import bloodwork
from apps.athletes.models import Athlete
from apps.coaching.client import AIUnavailable, complete, model_for
from apps.coaching.services import check_budget, log_call
from nutrition import foods as F

logger = logging.getLogger(__name__)

OPERATION = "day_plan"
PROMPT_VERSION = "day-plan-v1"

LOOKBACK_DAYS = 14
#: Below this many logged days the averages are noise, and saying "your protein
#: is low" off three days would be a guess wearing a number's clothes.
MIN_LOGGED_DAYS = 4
#: A macro counts as short when the average misses by more than this fraction.
SHORT_BY = 0.15

SLOTS: tuple[F.Slot, ...] = ("breakfast", "lunch", "snack", "dinner")

#: Roughly how a day's eating divides, renormalised over whatever meals are
#: actually left. Asked for a day of food without these, the model produces a
#: generous day of food — the first real plan it wrote came back 28% over his
#: calories and 38% over his protein, every meal individually sensible. A budget
#: per meal is the only instruction it can actually check itself against.
SLOT_SHARE: dict[str, float] = {
    "breakfast": 0.25, "lunch": 0.35, "snack": 0.10, "dinner": 0.30,
}

#: How far over the day's remaining calories a plan may land before it is sent
#: back once with the overshoot spelled out. Some slack is right: portions come
#: in whole idli and whole katori, and a plan trimmed to the exact kcal would be
#: a plan of half-portions nobody serves.
OVER_BY = 0.12

#: Indian RDA-ish daily iron for an adult man, used only to say "low" or not.
#: Runners lose more through foot-strike haemolysis and sweat, which is why this
#: sits above the figure a sedentary person would be given.
IRON_TARGET_MG = 19.0
VITAMIN_C_WITH_IRON_MG = 50.0


class PlannedItem(BaseModel):
    model_config = {"extra": "forbid"}

    key: str = Field(description="A food key from the list given. Never invent one.")
    portions: float = Field(description="How many portions, e.g. 3 for three idli.")


class PlannedMeal(BaseModel):
    model_config = {"extra": "forbid"}

    slot: Literal["breakfast", "lunch", "snack", "dinner"]
    items: list[PlannedItem]
    #: One short line: why this meal is this way today.
    why: str = ""


class DayPlanOut(BaseModel):
    model_config = {"extra": "forbid"}

    meals: list[PlannedMeal]
    headline: str = Field(description="One sentence about today's eating, under 110 characters.")
    focus: list[str] = Field(default_factory=list, description="1-3 things to focus on.")


SYSTEM = """You arrange a day of food for a South Indian runner from a fixed list.

You are given his targets, what he has already eaten today, his training, his \
blood markers, what his PG kitchen serves him, and the exact foods available to \
him. Each food comes with a key.

Rules:
- Use ONLY the food keys given. Never invent a key, a food or a number.
- Never state calories, grams or any other figure. They are computed from the \
keys you choose and shown next to your words. Talk about food, not arithmetic.
- Plan the meals he still has left today, not the ones already eaten.
- Foods marked [PG] arrive from his mess without effort. Build the meal around \
them where you can and add to them rather than replacing them; suggest replacing \
a PG meal only when it genuinely cannot be made to work.
- Foods marked [staple] are ones he has said he eats most days. Include them.
- Portions should be realistic: 2-4 idli, 1-2 katori of a curry, not 6 of anything.
- Stay inside the per-meal budget you are given. The whole plan must fit what he has left for the day. Coming in a little under is fine; going over is not, and "one more katori" across four meals is how a day ends up several hundred calories over.
- If a blood marker is flagged, let it steer the choice between two otherwise \
equal options, and say so plainly in `why` or `focus`. For iron specifically: \
meat, fish and egg iron is absorbed far better than iron from dal, greens or \
millets; vitamin C in the SAME meal helps the plant kind; tea and coffee within \
about an hour of a meal work against it.
- Never recommend a supplement or a dose. Food only.
- `focus` is what to actually change, in plain words. No encouragement padding.
- Be concrete and short. He is reading this on a phone before a meal."""


def _profile(athlete: Athlete):
    from .models import FoodProfile

    return FoodProfile.objects.filter(athlete=athlete).first()


def shortfalls(athlete: Athlete, today: dt.date) -> dict:
    """What the last two weeks of logging actually say. Pure arithmetic, no model.

    Returns `logged_days` so the caller can stay quiet when there is not enough
    to speak from — an average over two logged days is not an average.
    """
    from .models import Meal
    from .services import targets_for

    start = today - dt.timedelta(days=LOOKBACK_DAYS - 1)
    rows = Meal.objects.filter(athlete=athlete, local_date__gte=start, local_date__lte=today)

    per_day: dict[dt.date, dict[str, float]] = {}
    for meal in rows:
        day = per_day.setdefault(meal.local_date, {"kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0})
        for macro in ("kcal", "protein_g", "carbs_g", "fat_g"):
            day[macro] += getattr(meal, macro) or 0.0

    # Today is excluded from the average: it is usually half-finished, and a day
    # in progress drags every average down for no reason.
    days = {d: v for d, v in per_day.items() if d != today}
    logged = len(days)
    if logged < MIN_LOGGED_DAYS:
        return {"logged_days": logged, "enough": False, "short": [], "averages": {}, "targets": {}}

    averages = {
        macro: round(sum(v[macro] for v in days.values()) / logged)
        for macro in ("kcal", "protein_g", "carbs_g", "fat_g")
    }
    target = targets_for(athlete, today)
    targets = {"kcal": target.kcal, "protein_g": target.protein_g,
               "carbs_g": target.carbs_g, "fat_g": target.fat_g}

    short = []
    for macro, label in (("protein_g", "protein"), ("carbs_g", "carbohydrate"), ("kcal", "calories")):
        want, got = targets[macro], averages[macro]
        if want > 0 and got < want * (1 - SHORT_BY):
            short.append({
                "macro": macro, "label": label,
                "average": got, "target": want,
                "gap": round(want - got),
                "pct": round(100 * got / want),
            })
    return {
        "logged_days": logged, "enough": True,
        "averages": averages, "targets": targets, "short": short,
        "window_days": LOOKBACK_DAYS,
    }


def _flagged(athlete: Athlete, today: dt.date) -> tuple[list[bloodwork.Reading], dt.date | None]:
    from .precheck import PANEL_FRESH_DAYS
    from apps.health.models import LabPanel

    panel = (LabPanel.objects.filter(athlete=athlete)
             .prefetch_related("readings").order_by("-taken_on", "-id").first())
    if panel is None or (today - panel.taken_on).days > PANEL_FRESH_DAYS:
        return [], None
    readings = [bloodwork.assess(r.key, r.value, r.ref_low, r.ref_high)
                for r in panel.readings.all()]
    return [r for r in readings if r is not None and r.flagged], panel.taken_on


def _remaining_slots(eaten_slots: set[str], now_hour: int) -> list[str]:
    """Meals still ahead of him. A slot already logged is done; past that it is
    the clock, generously — someone asking at 15:00 can still plan a late lunch."""
    cutoffs = {"breakfast": 11, "lunch": 16, "snack": 19, "dinner": 23}
    return [s for s in SLOTS if s not in eaten_slots and now_hour <= cutoffs[s]]


def build(athlete: Athlete, *, today: dt.date | None = None, now_hour: int | None = None) -> dict:
    """Today's plan. Saves nothing — it is a suggestion, not a log."""
    from .services import diet_day
    from .precheck import _sessions

    today = today or athlete.local_today
    # His clock, not the server's: at 21:00 in Kolkata the only meal left is
    # dinner, and a UTC server would still be offering him lunch.
    if now_hour is None:
        now_hour = athlete.local_now.hour

    profile = _profile(athlete)
    pattern = profile.pattern if profile else "veg"
    prep = profile.prep if profile else "none"
    provided = set(profile.provided or []) if profile else set()
    staples = set(profile.staples or []) if profile else set()
    dislikes = frozenset(profile.dislikes or []) if profile else frozenset()

    available = F.allowed(pattern, prep, dislikes)
    diet = diet_day(athlete, today)
    sessions = _sessions(athlete, today)
    flagged, panel_date = _flagged(athlete, today)
    gaps = shortfalls(athlete, today)

    eaten_slots = {m["meal_type"] for m in diet["meals"]}
    slots_left = _remaining_slots(eaten_slots, now_hour)

    targets, eaten = diet["targets"], diet["eaten"]
    left = {
        "kcal": round(targets["kcal"] - eaten["kcal"]),
        "protein_g": round(targets["protein_g"] - eaten["protein_g"]),
        "carbs_g": round(targets["carbs_g"] - eaten["carbs_g"]),
        "fat_g": round(targets["fat_g"] - eaten["fat_g"]),
    }

    budgets = slot_budgets(left, slots_left)

    model = model_for(OPERATION)
    check_budget(athlete, OPERATION, model)
    prompt = _prompt(available, provided, staples, left, slots_left, sessions,
                     flagged, panel_date, gaps, profile, budgets)
    try:
        out, stats = complete(operation=OPERATION, system=SYSTEM, user=prompt, schema=DayPlanOut)
    except AIUnavailable as exc:
        log_call(athlete, OPERATION, {"model": model}, exc, PROMPT_VERSION)
        raise
    log_call(athlete, OPERATION, stats, None, PROMPT_VERSION)

    plan = _assemble(out, available, provided, staples, left, flagged, panel_date,
                     gaps, slots_left, budgets)

    # One repair pass, and only when it is over by enough to matter. Being told
    # the exact number it missed by is the only feedback that reliably moves it;
    # repeating the instruction does not.
    over = _overshoot(plan["totals"], left)
    if over > OVER_BY:
        try:
            fixed, stats = complete(
                operation=OPERATION, system=SYSTEM,
                user=_repair_prompt(prompt, plan, left), schema=DayPlanOut,
            )
            log_call(athlete, OPERATION, stats, None, PROMPT_VERSION)
            retried = _assemble(fixed, available, provided, staples, left, flagged,
                                panel_date, gaps, slots_left, budgets)
            # Keep it only if it actually helped. A worse second attempt is not
            # an improvement just because it is second.
            if _overshoot(retried["totals"], left) < over:
                retried["repaired"] = True
                return retried
        except AIUnavailable:
            logger.warning("day_plan repair pass unavailable; returning the first plan")
    return plan


def _overshoot(totals: dict, left: dict) -> float:
    """How far past the day's remaining calories the plan lands, as a fraction.
    Under budget is 0.0 — eating less than planned is not an error to correct."""
    budget = left.get("kcal") or 0
    if budget <= 0:
        return 0.0
    return max(0.0, (totals["kcal"] - budget) / budget)


def slot_budgets(left: dict, slots_left: list[str]) -> dict[str, dict[str, int]]:
    """Split what is left of the day across the meals that are left.

    Pure. The shares are renormalised, so someone planning from 3pm gets lunch,
    snack and dinner adding to the whole remaining day rather than to 75% of it.
    """
    shares = {s: SLOT_SHARE[s] for s in slots_left if s in SLOT_SHARE}
    denominator = sum(shares.values())
    if not shares or denominator <= 0:
        return {}
    return {
        slot: {
            "kcal": max(0, round((left.get("kcal") or 0) * share / denominator)),
            "protein_g": max(0, round((left.get("protein_g") or 0) * share / denominator)),
        }
        for slot, share in shares.items()
    }


def _repair_prompt(original: str, plan: dict, left: dict) -> str:
    totals = plan["totals"]
    heaviest = sorted(plan["meals"], key=lambda m: -m["kcal"])[:2]
    lines = [
        original, "",
        "---",
        "That plan was too big. Exactly how much:",
        f"- it came to {totals['kcal']} kcal against {left['kcal']} he has left "
        f"({totals['kcal'] - left['kcal']} over)",
        f"- and {totals['protein_g']} g protein against {left['protein_g']} g.",
        "",
        "The heaviest meals were:",
    ]
    for meal in heaviest:
        items = ", ".join(i["text"] for i in meal["items"])
        lines.append(f"- {meal['slot']}: {meal['kcal']} kcal — {items}")
    lines += [
        "",
        "Plan it again, inside the per-meal budgets. Cut portions and drop the "
        "items doing the least work rather than shaving a little off everything. "
        "Landing slightly under is fine; landing over is not.",
    ]
    return "\n".join(lines)


def _food_line(food: F.Food, staples: set[str]) -> str:
    tags = []
    if food.mess:
        tags.append("[usually on the mess menu]")
    if food.key in staples:
        tags.append("[staple]")
    if food.haem:
        tags.append("[iron your body absorbs well]")
    elif food.iron_mg >= 2.0:
        tags.append("[plant iron]")
    if food.vitamin_c_mg >= 15:
        tags.append("[vitamin C]")
    if food.key in F.IRON_BLOCKERS:
        tags.append("[works against iron in the same meal]")
    tail = f" {' '.join(tags)}" if tags else ""
    note = f" — {food.note}" if food.note else ""
    return f"- {food.key}: {food.name}, one portion is {food.portion}{tail}{note}"


def _prompt(available, provided, staples, left, slots_left, sessions,
            flagged, panel_date, gaps, profile, budgets) -> str:
    lines = ["Plan the rest of his day.", ""]
    lines.append(f"Meals still to come: {', '.join(slots_left) if slots_left else 'none — the day is done'}.")
    if provided:
        covered = ", ".join(sorted(provided))
        lines.append(
            f"His PG serves him {covered}. Those meals arrive whether or not he does "
            "anything, so build on what the mess gives him there and add to it, rather "
            "than telling him to cook a meal that is already waiting downstairs."
        )
    else:
        lines.append("His PG serves him nothing — every meal here is one he makes or buys.")
    lines.append(
        f"Still to eat today: {left['kcal']} kcal, {left['protein_g']} g protein, "
        f"{left['carbs_g']} g carbs, {left['fat_g']} g fat. "
        "Do not repeat these numbers back."
    )
    if budgets:
        lines.append("")
        lines.append("Budget per meal — the whole plan must fit inside these:")
        for slot, b in budgets.items():
            lines.append(f"- {slot}: about {b['kcal']} kcal and {b['protein_g']} g protein")
        lines.append("Slightly under is fine. Over is not.")
    if sessions["ran_today"]:
        lines.append("He has already run today.")
    for s in sessions["sessions"]:
        if not s["done"]:
            lines.append(
                f"Session {s['when']}: {s['title']} ({s['kind']})"
                + (" — a demanding one." if s["demanding"] else ".")
            )
    if not sessions["sessions"]:
        lines.append("Nothing planned today or tomorrow.")

    if gaps.get("enough") and gaps["short"]:
        lines.append("")
        lines.append(f"Over his last {gaps['logged_days']} logged days he has been short on:")
        for s in gaps["short"]:
            lines.append(f"- {s['label']}: averaging {s['pct']}% of target")

    if flagged:
        lines.append("")
        lines.append(f"Blood markers outside range, from a panel taken {panel_date}:")
        for r in flagged:
            where = "below" if r.status == bloodwork.BELOW else "above"
            lines.append(f"- {r.label}: {where} range. {r.matters}")

    if profile and profile.notes:
        lines.append("")
        lines.append(f'In his own words: """{profile.notes[:400]}"""')

    lines += ["", "Foods available to him. Use these keys only:"]
    lines += [_food_line(f, staples) for f in available]
    return "\n".join(lines)


def _assemble(out: DayPlanOut, available, provided, staples, left,
              flagged, panel_date, gaps, slots_left, budgets=None) -> dict:
    """Turn the model's keys into the plan, with every number computed here."""
    ok = {f.key: f for f in available}
    meals: list[dict] = []
    all_items: list[tuple[str, float]] = []
    dropped: list[str] = []

    for meal in out.meals:
        if meal.slot not in slots_left and slots_left:
            continue
        items = []
        slot_is_pg = meal.slot in provided
        for item in meal.items:
            food = ok.get(item.key)
            if food is None:
                dropped.append(item.key)
                continue
            portions = max(0.5, min(float(item.portions), F.MAX_PORTIONS))
            all_items.append((food.key, portions))
            items.append({
                "key": food.key,
                "text": F.describe(food.key, portions),
                "name": food.name,
                "portions": portions,
                # On his plate already: the mess serves this kind of thing AND the
                # PG covers this meal. Either alone is not enough.
                "from_pg": food.mess and slot_is_pg,
                "staple": food.key in staples,
                "haem_iron": food.haem,
                "note": food.note,
                **F.total([(food.key, portions)]).rounded(),
            })
        if items:
            meals.append({
                "slot": meal.slot,
                "items": items,
                "why": meal.why.strip()[:200],
                **F.total([(i["key"], i["portions"]) for i in items]).rounded(),
            })

    totals = F.total(all_items).rounded()
    return {
        "meals": meals,
        "totals": totals,
        "left_before": left,
        # What the plan does to the day's gap, computed here rather than claimed.
        "covers": {
            macro: (round(100 * totals[macro] / left[macro]) if left[macro] > 0 else None)
            for macro in ("kcal", "protein_g", "carbs_g")
        },
        "iron": {
            "total_mg": totals["iron_mg"],
            "haem_mg": totals["haem_iron_mg"],
            "vitamin_c_mg": totals["vitamin_c_mg"],
            "target_mg": IRON_TARGET_MG,
            "paired": totals["vitamin_c_mg"] >= VITAMIN_C_WITH_IRON_MG,
        },
        "budgets": budgets or {},
        "over_by_pct": round(100 * _overshoot(totals, left)),
        "repaired": False,
        "headline": out.headline.strip()[:200],
        "focus": [f.strip()[:200] for f in out.focus[:3] if f.strip()],
        "missing": gaps,
        "bloods": {
            "taken_on": panel_date,
            "flagged": [{"key": r.key, "label": r.label} for r in flagged],
        },
        # Named rather than swallowed, same rule as the lab extractor.
        "dropped_keys": sorted(set(dropped)),
        "standing_note": (
            "Portions are the usual household sizes, and the numbers are a reference "
            "table rather than a measurement of your plate."
        ),
    }
