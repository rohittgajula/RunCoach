"""The habits AI explanation (R8 §B). Coach tier, cached per day, budget-checked.

Only aggregates go to the model: the summary payload minus its daily series (counts per
day are still more detail than the explanation needs) — never a log row, time or note.
"""

from __future__ import annotations

import json

from apps.coaching.models import AIAnalysis

HABITS_USER = """This athlete tracks habits (cigarettes, standard drinks, sugar \
servings) next to their running. Everything below was calculated in Python; impact rows \
compare the morning after a day with the habit against the morning after a day without.

{payload}

Write 80-160 words of markdown: where they stand against their goals, the smoke-free \
streak and savings if they are quitting, and only the impact rows with enough_data true. \
Describe associations, never causes ("on nights after drinking, your HRV was 6 ms lower \
on average, n=7"). Be encouraging and non-judgemental. Use only numbers above, and always keep their units exactly as given (money is already formatted, e.g. "₹2,448" — never drop the ₹)."""


def rupees(value) -> str | None:
    """Money with its unit, for the model: 2448.0 -> "₹2,448"."""
    if value is None:
        return None
    return f"₹{value:,.0f}" if float(value).is_integer() or value >= 100 else f"₹{value:,.2f}"


def ai_payload(payload: dict) -> dict:
    """Aggregates only: drop the per-day series and the stored summary."""
    def strip(block):
        return {k: v for k, v in (block or {}).items() if k != "series"}

    smoke = {k: v for k, v in strip(payload["smoke"]).items() if k != "milestones"}
    smoke["milestones_reached"] = sum(1 for m in payload["smoke"]["milestones"] if m["reached"])
    if smoke.get("since_quit"):
        quit_ = dict(smoke["since_quit"])
        quit_["money_saved"] = rupees(quit_.get("money_saved"))
        smoke["since_quit"] = quit_
    return {
        "range": payload["range"], "today": str(payload["today"]),
        "goals": payload.get("goals"),
        "goal_meanings": {"quit": "stopping completely", "reduce": "cutting down",
                          "none": "no goal set — do not judge this habit against a goal"},
        "units": {"money": "INR (₹)", "alcohol":
                                                  "standard drinks", "sugar": "servings"},
        "smoke": smoke,
        "alcohol": strip(payload["alcohol"]), "sugar": strip(payload["sugar"]),
        "impact": [{k: r[k] for k in ("habit", "metric", "dose", "with_avg", "without_avg",
                                      "diff", "n_with", "n_without", "direction",
                                      "enough_data")} for r in payload["impact"]],
        "weekly": payload["weekly"],
    }


def summary_state(athlete, today) -> dict:
    row = AIAnalysis.objects.filter(athlete=athlete, kind=AIAnalysis.Kind.HABITS).first()
    tz = athlete.local_now.tzinfo
    if row is None or row.created_at.astimezone(tz).date() != today:
        return {"status": "none", "markdown": "", "generated_at": None}
    return {"status": "ready", "markdown": (row.result or {}).get("markdown", ""),
            "generated_at": row.created_at}


def generate_summary(athlete, payload: dict, refresh: bool = False) -> dict:
    """Return today's summary, generating it if needed. Raises AIUnavailable."""
    from apps.coaching.schemas import HabitsSummary
    from apps.coaching.services import _run

    today = athlete.local_today
    existing = summary_state(athlete, today)
    if existing["status"] == "ready" and not refresh:
        return existing
    clean = ai_payload(payload)
    if refresh:
        tz = athlete.local_now.tzinfo
        for row in AIAnalysis.objects.filter(athlete=athlete, kind=AIAnalysis.Kind.HABITS):
            if row.created_at.astimezone(tz).date() == today:
                row.delete()
    _run(athlete, kind=AIAnalysis.Kind.HABITS, operation="habits_summary", payload=clean,
         user_prompt=HABITS_USER.format(payload=json.dumps(clean, indent=2, default=str)),
         schema=HabitsSummary)
    return summary_state(athlete, today)
