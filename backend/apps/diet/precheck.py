"""Before he eats it: is this a good idea, given his bloods and his running?

The ask was "before eating I will give input of what I am eating, give an
overview according to my report, run etc., healthiness". That is three different
questions wearing one coat, and they are answered by three different things:

    does it fit the day?      arithmetic        -> Python, in `assess_fit`
    does it fit the running?  arithmetic        -> Python, in `assess_fit`
    is the food itself good?  judgement         -> the model, in SYSTEM

So the model never sees a subtraction it has to do. It is handed the finished
numbers — what is left of the day, what this meal does to that, what the next
session needs — and asked only for the part a table cannot answer: whether dosa
and sambar at 9pm before a long run is a sensible thing to eat, and what to
change if it is not.

The verdict is Python's too, for a reason that is not purity. A model asked
"is this too much?" on a Tuesday and again on a Wednesday will not answer the
same way about the same plate, and a food log that praises a meal one day and
scolds it the next is one he will stop opening. `FIT_RULES` are boring, visible
and the same every time.

**The bloods are the part worth getting right.** A flagged marker changes what
food means: with ferritin at 18, the iron in a plate of rajma is the most useful
thing on it, and the tea he drinks with it is working against him. That is a
real, specific, well-evidenced interaction and exactly the kind of thing he
bought a blood test to find out. But only flagged markers are passed, only from
a panel recent enough to still be true, and the model is told it is talking
about food, not treating a deficiency.
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

logger = logging.getLogger(__name__)

OPERATION = "meal_precheck"
PROMPT_VERSION = "meal-precheck-v1"

#: A panel older than this is history, not a fact about him today. Ferritin moves
#: in weeks on supplements and in months without them; a year-old iron result
#: should not be shaping what he has for lunch.
PANEL_FRESH_DAYS = 240

#: Sessions where carbohydrate the evening before genuinely matters.
DEMANDING = {"LONG", "INTERVALS", "TEMPO", "RACE"}

Verdict = Literal["good", "fits", "heavy", "over"]

#: Python's half of the answer, in order. The first match wins. `share` is this
#: meal as a fraction of the day's kcal target; `after` is what is left of the
#: day's kcal once it is eaten.
FIT_RULES: tuple[tuple[Verdict, str], ...] = (
    ("over", "it goes past today's calories, and by enough to notice"),
    ("heavy", "it uses most of what is left of today"),
    ("good", "it fits today, and it brings protein you still need"),
    ("fits", "it fits inside today's calories"),
)


def _fit_verdict(share: float, after: int, target_kcal: int,
                 protein_gap_before: int, protein_in_meal: int) -> tuple[Verdict, str]:
    overshoot = -after
    if after < 0 and overshoot > 0.1 * max(target_kcal, 1):
        return FIT_RULES[0]
    if after < 0 or share > 0.55:
        return FIT_RULES[1]
    if protein_gap_before > 0 and protein_in_meal >= 0.3 * protein_gap_before:
        return FIT_RULES[2]
    return FIT_RULES[3]


class PrecheckAdvice(BaseModel):
    """Only the judgement. Every number in the response comes from Python."""

    model_config = {"extra": "forbid"}

    headline: str = Field(description="One sentence, under 110 characters, about the food itself.")
    good: list[str] = Field(default_factory=list,
                            description="What is genuinely good about this plate. 0-3 short items.")
    watch: list[str] = Field(default_factory=list,
                             description="What is worth knowing. 0-3 short items.")
    swap: str = Field(default="", description="One change worth making, or empty if none is.")
    timing: str = Field(default="", description="Anything about when to eat it given the session, or empty.")


SYSTEM = """You are a running coach's nutrition voice, looking at a meal the athlete \
is ABOUT TO eat. He has not eaten it yet, so talk about the decision, not the past.

You are given the meal's estimated contents, the arithmetic already done (what is \
left of his day, what this meal does to it, what his next session asks for), and any \
blood markers of his that are currently outside their range.

Rules:
- Never do arithmetic and never restate the numbers you were given. They are already \
on screen beside your words. Say what they mean.
- Judge the food, which is the part the numbers miss: how it is cooked, how much oil \
or sugar it carries, how much of it is refined carbohydrate, what it is missing.
- When a blood marker is flagged, say what this plate does for it or against it, in \
food terms. Iron absorption, for one, is worth being concrete about: vitamin C with \
a meal helps it, tea and coffee within an hour of eating hinder it, and the iron in \
meat is absorbed far better than the iron in pulses or spinach.
- Never recommend a supplement, a dose, or a treatment, and never say or imply a \
marker is improving, worsening, or caused by anything. That is his doctor's.
- `swap` is one specific, easy change ("have the chai an hour later, not with it"), \
not a lecture. Leave it empty if the meal is fine.
- `timing` only if his next session makes timing matter. Otherwise empty.
- Indian home cooking is the norm here. Do not treat rice, roti, ghee or chai as \
problems in themselves.
- Be direct and short. No praise padding, no hedging, no disclaimers — the response \
carries its own."""


def _latest_panel(athlete: Athlete, today: dt.date) -> tuple[list[bloodwork.Reading], dt.date | None]:
    """Flagged readings from his most recent panel, if it is still recent."""
    from apps.health.models import LabPanel

    panel = (LabPanel.objects.filter(athlete=athlete)
             .prefetch_related("readings").order_by("-taken_on", "-id").first())
    if panel is None or (today - panel.taken_on).days > PANEL_FRESH_DAYS:
        return [], None
    readings = [bloodwork.assess(r.key, r.value, r.ref_low, r.ref_high)
                for r in panel.readings.all()]
    return [r for r in readings if r is not None and r.flagged], panel.taken_on


def _sessions(athlete: Athlete, today: dt.date) -> dict:
    """What he has run today, and what is next. Plans carry a date, not a time, so
    this is "today" and "tomorrow" rather than hours."""
    from apps.activities.models import Activity
    from apps.planning.models import INACTIVE_STATUSES, PlannedWorkout, TrainingPlan

    planned = list(
        PlannedWorkout.objects.filter(
            plan__athlete=athlete, date__in=(today, today + dt.timedelta(days=1)),
        ).exclude(status__in=INACTIVE_STATUSES).exclude(
            # A proposed plan he has not accepted is not his schedule yet.
            plan__status__in=(TrainingPlan.Status.PROPOSED, TrainingPlan.Status.DECLINED),
        )
        .order_by("date")
    )
    ran_today = Activity.objects.filter(athlete=athlete, local_date=today).exists()

    def shape(workout) -> dict:
        return {
            "when": "today" if workout.date == today else "tomorrow",
            "title": workout.title,
            "kind": workout.kind,
            "minutes": round((workout.duration_s or 0) / 60),
            "demanding": workout.kind in DEMANDING,
            "done": workout.completed_activity_id is not None,
        }

    return {
        "ran_today": ran_today,
        "sessions": [shape(w) for w in planned],
    }


def assess_fit(day: dict, meal: dict, sessions: dict) -> dict:
    """Every number in the answer. Pure: a dict in, a dict out, no model, no clock."""
    targets, eaten = day["targets"], day["eaten"]
    target_kcal = int(targets["kcal"] or 0)

    before = int(round(target_kcal - eaten["kcal"]))
    meal_kcal = int(round(meal["kcal"]))
    after = before - meal_kcal
    share = meal_kcal / target_kcal if target_kcal else 0.0

    protein_gap = int(round(max(0.0, targets["protein_g"] - eaten["protein_g"])))
    carb_gap = int(round(max(0.0, targets["carbs_g"] - eaten["carbs_g"])))
    verdict, reason = _fit_verdict(
        share, after, target_kcal, protein_gap, int(round(meal["protein_g"]))
    )

    upcoming = [s for s in sessions["sessions"] if not s["done"]]
    demanding = next((s for s in upcoming if s["demanding"]), None)

    return {
        "verdict": verdict,
        "reason": reason,
        "kcal_left_before": before,
        "kcal_in_meal": meal_kcal,
        "kcal_left_after": after,
        "share_of_day_pct": round(share * 100),
        "protein_gap_before_g": protein_gap,
        "protein_in_meal_g": int(round(meal["protein_g"])),
        "carb_gap_before_g": carb_gap,
        "carbs_in_meal_g": int(round(meal["carbs_g"])),
        "next_demanding": demanding,
        "upcoming": upcoming,
        "ran_today": sessions["ran_today"],
    }


def _prompt(text: str, meal: dict, fit: dict, flagged: list[bloodwork.Reading],
            panel_date: dt.date | None, goal: str) -> str:
    lines = [f'He is about to eat, in his words: """{text.strip()[:600]}"""', "", "Estimated contents:"]
    for item in meal["items"]:
        lines.append(
            f"- {item['quantity']} {item['name']}: {item['kcal']:g} kcal, "
            f"{item['carbs_g']:g} g carbs, {item['protein_g']:g} g protein, {item['fat_g']:g} g fat"
        )
    lines += [
        "",
        f"Whole meal: {meal['kcal']:g} kcal, {meal['carbs_g']:g} g carbs, "
        f"{meal['protein_g']:g} g protein, {meal['fat_g']:g} g fat "
        f"(the estimate's own confidence: {meal['confidence']}).",
        "",
        "The arithmetic, already done — do not repeat these numbers back:",
        f"- {fit['kcal_left_before']} kcal left of today before this meal; "
        f"{fit['kcal_left_after']} after it ({fit['share_of_day_pct']}% of the day's target).",
        f"- Protein still short by {fit['protein_gap_before_g']} g today; this meal brings "
        f"{fit['protein_in_meal_g']} g.",
        f"- Carbs still short by {fit['carb_gap_before_g']} g today; this meal brings "
        f"{fit['carbs_in_meal_g']} g.",
        f"- The day's verdict on the numbers alone: {fit['verdict']} — {fit['reason']}.",
        f"- His weight goal is to {goal}.",
    ]
    if fit["ran_today"]:
        lines.append("- He has already run today.")
    if fit["upcoming"]:
        for session in fit["upcoming"]:
            lines.append(
                f"- Next session: {session['title']} ({session['kind']}, "
                f"{session['minutes']} min) {session['when']}"
                + (" — a demanding one." if session["demanding"] else ".")
            )
    else:
        lines.append("- Nothing planned today or tomorrow.")

    if flagged:
        lines += ["", f"Blood markers of his outside their range, from a panel taken {panel_date}:"]
        for reading in flagged:
            where = "below" if reading.status == bloodwork.BELOW else "above"
            lines.append(
                f"- {reading.label}: {reading.value:g} {reading.unit}, {where} the range "
                f"({reading.low}–{reading.high}). {reading.matters}"
            )
        lines.append(
            "Speak about these only in terms of what is on this plate. No supplements, "
            "no doses, no claims about why they are where they are."
        )
    else:
        lines += ["", "No flagged blood markers on file — say nothing about his bloods."]
    return "\n".join(lines)


def precheck_meal(athlete: Athlete, *, text: str, meal_type: str | None = None,
                  day: dt.date | None = None) -> dict:
    """Judge a meal he has not eaten yet. Saves nothing.

    Raises ValueError for an empty description and AIUnavailable when the model is
    not reachable — the caller turns that into a 503, and the fit numbers are still
    worth showing him on their own.
    """
    from .estimate import estimate_meal
    from .services import diet_day

    text = (text or "").strip()
    if not text:
        raise ValueError("Tell me what you are about to eat.")

    today = day or athlete.local_today
    meal = estimate_meal(athlete, text=text, meal_type=meal_type)
    diet = diet_day(athlete, today)
    sessions = _sessions(athlete, today)
    fit = assess_fit(diet, meal, sessions)
    flagged, panel_date = _latest_panel(athlete, today)

    goal = {"lose": "lose weight slowly", "gain": "gain weight"}.get(
        athlete.diet_goal or "maintain", "hold your weight"
    )

    model = model_for(OPERATION)
    check_budget(athlete, OPERATION, model)
    try:
        advice, stats = complete(
            operation=OPERATION, system=SYSTEM,
            user=_prompt(text, meal, fit, flagged, panel_date, goal),
            schema=PrecheckAdvice,
        )
    except AIUnavailable as exc:
        log_call(athlete, OPERATION, {"model": model}, exc, PROMPT_VERSION)
        raise
    log_call(athlete, OPERATION, stats, None, PROMPT_VERSION)

    return {
        "estimate": meal,
        "fit": fit,
        "advice": {
            "headline": advice.headline.strip()[:200],
            "good": [s.strip()[:160] for s in advice.good[:3] if s.strip()],
            "watch": [s.strip()[:160] for s in advice.watch[:3] if s.strip()],
            "swap": advice.swap.strip()[:200],
            "timing": advice.timing.strip()[:200],
        },
        "bloods": {
            "taken_on": panel_date,
            "flagged": [{"key": r.key, "label": r.label} for r in flagged],
        },
        "targets": diet["targets"],
        "eaten": diet["eaten"],
        "standing_note": (
            "An estimate, not a measurement — the portions are guessed from your "
            "words. Nothing here is medical advice."
        ),
    }
