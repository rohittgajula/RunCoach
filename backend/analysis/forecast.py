"""Tomorrow's readiness forecast (R10 §C14). A transparent, deterministic estimate —
labelled as one — from today's readiness, today's load, the HRV trend, sleep debt and
habits logged today, plus the levers that could raise it. Pure.

The private habit is never an input.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .insights import readiness_label

SPREAD = 8
NEUTRAL = 70.0              # where readiness drifts back to overnight, all else equal
TODAY_WEIGHT = 0.6
NOTE = "An estimate from today's numbers, not a measurement. Garmin's score tomorrow may differ."


@dataclass
class ForecastInputs:
    today_score: int | None = None
    recent_scores: list[int] = field(default_factory=list)   # last 14 days, any order
    today_load: float = 0.0
    chronic_daily_load: float = 0.0
    hrv_recent: list[float] = field(default_factory=list)    # last 3 nights
    hrv_baseline_low: float | None = None
    hrv_baseline_high: float | None = None
    sleep_debt_s: int | None = None
    need_s: int | None = None
    bedtime_target: str | None = None     # "HH:MM"
    late_bedtimes: bool = False           # recent bedtimes later than the target
    alcohol_today: float = 0.0
    drinks_regularly: bool = False        # drinks logged on 2+ of the last 7 days, or a goal
    smoke_today: float = 0.0


def _clock_12h(value: str | None) -> str | None:
    if not value:
        return None
    hour, minute = (int(p) for p in value.split(":"))
    suffix = "am" if hour < 12 else "pm"
    shown = hour % 12 or 12
    return f"{shown}{':' + f'{minute:02d}' if minute else ''} {suffix}"


def factors(i: ForecastInputs) -> list[dict]:
    out = []
    if i.chronic_daily_load > 0 or i.today_load > 0:
        ratio = i.today_load / i.chronic_daily_load if i.chronic_daily_load else 2.0
        if i.today_load <= 0:
            out.append({"key": "load", "label": "Rest day", "effect": 4,
                        "detail": "No training today — recovery usually shows overnight."})
        elif ratio >= 1.5:
            out.append({"key": "load", "label": "Big training day", "effect": -8,
                        "detail": "Today's load is well above your recent daily average."})
        elif ratio >= 1.0:
            out.append({"key": "load", "label": "Training day", "effect": -3,
                        "detail": "Today's load is around or above your daily average."})
        else:
            out.append({"key": "load", "label": "Light training day", "effect": 0,
                        "detail": "Today's load is below your daily average."})
    hrv = [v for v in i.hrv_recent if v is not None]
    if hrv and i.hrv_baseline_low is not None:
        avg = sum(hrv) / len(hrv)
        if avg < i.hrv_baseline_low:
            out.append({"key": "hrv_trend", "label": "HRV below your normal", "effect": -6,
                        "detail": f"Last {len(hrv)} nights averaged {avg:.0f} ms, under "
                                  f"your usual {i.hrv_baseline_low:.0f} ms floor."})
        elif i.hrv_baseline_high is None or avg <= i.hrv_baseline_high:
            out.append({"key": "hrv_trend", "label": "HRV in your normal range",
                        "effect": 2, "detail": f"Last {len(hrv)} nights averaged {avg:.0f} ms."})
    if i.sleep_debt_s is not None:
        hours = i.sleep_debt_s / 3600
        if hours > 5:
            effect, label = -8, "Big sleep debt"
        elif hours > 2:
            effect, label = -4, "Some sleep debt"
        elif hours <= 0.5:
            effect, label = 2, "Sleep on track"
        else:
            effect, label = -1, "A little sleep debt"
        out.append({"key": "sleep_debt", "label": label, "effect": effect,
                    "detail": f"{hours:.1f} h short of your need over the last week."})
    if i.alcohol_today >= 3:
        out.append({"key": "alcohol", "label": "Drinks today", "effect": -10,
                    "detail": f"{i.alcohol_today:g} drinks logged today."})
    elif i.alcohol_today > 0:
        out.append({"key": "alcohol", "label": "A drink today", "effect": -5,
                    "detail": f"{i.alcohol_today:g} drink{'s' if i.alcohol_today != 1 else ''} logged today."})
    if i.smoke_today > 0:
        out.append({"key": "smoke", "label": "Cigarettes today", "effect": -2,
                    "detail": f"{i.smoke_today:g} logged today."})
    return out


def levers(i: ForecastInputs, factor_list: list[dict]) -> list[dict]:
    out = []
    debt = next((f for f in factor_list if f["key"] == "sleep_debt"), None)
    if i.bedtime_target and ((debt and debt["effect"] < 0) or i.late_bedtimes):
        gain = 6 if debt and debt["effect"] <= -4 else 4
        out.append({"key": "bedtime", "label": f"Asleep by {_clock_12h(i.bedtime_target)}",
                    "gain": gain})
    if i.drinks_regularly or i.alcohol_today > 0:
        gain = 5 if i.alcohol_today > 0 or i.drinks_regularly else 3
        label = "No more alcohol tonight" if i.alcohol_today > 0 else "No alcohol tonight"
        out.append({"key": "no_alcohol", "label": label, "gain": gain})
    return out


def forecast(i: ForecastInputs) -> dict:
    scores = [s for s in i.recent_scores if s is not None]
    if i.today_score is None and not scores:
        return {"estimate": None, "low": None, "high": None, "label": "Unknown",
                "factors": [], "levers": [], "best_case": None,
                "sentence": "Not enough recent readiness data to estimate tomorrow yet.",
                "note": NOTE}
    today = i.today_score if i.today_score is not None else sum(scores) / len(scores)
    normal = sum(scores) / len(scores) if scores else NEUTRAL
    base = TODAY_WEIGHT * today + (1 - TODAY_WEIGHT) * normal
    found = factors(i)
    estimate = max(0, min(100, round(base + sum(f["effect"] for f in found))))
    lever_list = levers(i, found)
    best = min(100, estimate + sum(l["gain"] for l in lever_list)) if lever_list else None
    if lever_list:
        names = " and ".join(l["label"][0].lower() + l["label"][1:] if n else l["label"]
                             for n, l in enumerate(lever_list))
        sentence = f"About {estimate} tomorrow. {names} could make it {best}."
    else:
        sentence = f"About {estimate} tomorrow — an estimate, not a promise."
    return {"estimate": estimate, "low": max(0, estimate - SPREAD),
            "high": min(100, estimate + SPREAD), "label": readiness_label(estimate),
            "factors": found, "levers": lever_list, "best_case": best,
            "sentence": sentence, "note": NOTE}
