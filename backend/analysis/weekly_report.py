"""Weekly report card (R10 §C10): last week against the week before, three things that
went well, three to improve and one goal for this week. Deterministic. Pure."""

from __future__ import annotations

MIN_VALUES = 2
MAX_BULLETS = 3

# metric -> (label, unit, threshold, threshold relative?, higher is better?, digits)
WELLNESS = {
    "hrv": ("Overnight HRV", "ms", 0.05, True, True, 0),
    "rhr": ("Resting HR", "bpm", 2.0, False, False, 0),
    "sleep": ("Sleep", "h", 0.25, False, True, 1),
    "sleep_score": ("Sleep score", "", 3.0, False, True, 0),
}
HABIT_LABELS = {"smoke": "Cigarettes", "alcohol": "Drinks", "sugar": "Sugar servings",
                "private": "Private"}
HABIT_NOUNS = {"smoke": "cigarettes", "alcohol": "drinks", "sugar": "sugar servings",
               "private": "Private"}


def _mean(values, digits):
    values = [v for v in values if v is not None]
    if len(values) < MIN_VALUES:
        return None
    value = sum(values) / len(values)
    return round(value) if digits == 0 else round(value, digits)


def wellness_rows(this_week: dict[str, list], previous_week: dict[str, list]) -> list[dict]:
    rows = []
    for key, (label, unit, threshold, relative, higher_better, digits) in WELLNESS.items():
        now = _mean(this_week.get(key, []), digits)
        before = _mean(previous_week.get(key, []), digits)
        delta = better = None
        if now is not None and before is not None:
            delta = round(now - before, digits) if digits else round(now - before)
            limit = threshold * abs(before) if relative else threshold
            if abs(now - before) >= limit and limit > 0:
                better = (now > before) if higher_better else (now < before)
        rows.append({"metric": key, "label": label, "unit": unit, "this_week": now,
                     "previous_week": before, "delta": delta, "better": better})
    return rows


def habit_rows(this_week: dict[str, float], previous_week: dict[str, float],
               kinds: list[str]) -> list[dict]:
    rows = []
    for kind in kinds:
        now = round(this_week.get(kind, 0.0), 1)
        before = round(previous_week.get(kind, 0.0), 1)
        delta = round(now - before, 1)
        rows.append({"habit": kind, "label": HABIT_LABELS[kind], "this_week": now,
                     "previous_week": before, "delta": delta,
                     "better": None if delta == 0 else delta < 0})
    return rows


def _km(value: float) -> str:
    return f"{value:.1f} km"


def bullets(*, runs: dict, wellness: list[dict], habits: list[dict], prs: list[dict],
            zones: dict, ai_safe: bool = False) -> tuple[list[str], list[str], str]:
    """(went_well, to_improve, goal). `ai_safe` drops the private habit's lines."""
    good: list[str] = []
    bad: list[str] = []
    done, planned = runs["done"], runs["planned"]
    if planned:
        line = f"{runs['planned_done']} of {planned} planned runs done"
        (good if runs["planned_done"] >= planned else bad).append(line)
    elif done:
        good.append(f"{done} run{'s' if done != 1 else ''} logged")
    if runs["previous_km"] and runs["km"]:
        diff = runs["km"] - runs["previous_km"]
        if diff >= 0.5:
            good.append(f"Distance up to {_km(runs['km'])} from {_km(runs['previous_km'])}")
        elif diff <= -0.5 and not planned:
            bad.append(f"Distance down to {_km(runs['km'])} from {_km(runs['previous_km'])}")
    for pr in prs[:1]:
        good.append(f"New personal record: {pr['label']} {pr['display']}")
    total = sum(v for k, v in zones.items() if k != "below") if zones else 0
    if total:
        easy = (zones.get("Z1", 0) + zones.get("Z2", 0)) / total
        if easy >= 0.7:
            good.append(f"{round(easy * 100)}% of running time in the easy zones")
        elif easy < 0.5:
            bad.append(f"Only {round(easy * 100)}% of running time in the easy zones")
    for row in wellness:
        if row["better"] is None:
            continue
        unit = f" {row['unit']}" if row["unit"] else ""
        text = f"{row['label']} {row['previous_week']:g} → {row['this_week']:g}{unit}"
        (good if row["better"] else bad).append(text)
    for row in habits:
        if row["better"] is None or (ai_safe and row["habit"] == "private"):
            continue
        noun = HABIT_NOUNS[row["habit"]]
        text = f"{row['this_week']:g} {noun} vs {row['previous_week']:g} the week before"
        (good if row["better"] else bad).append(text.capitalize() if noun[0].islower()
                                                else text)
    if not done:
        bad.insert(0, "No runs logged last week")
    return good[:MAX_BULLETS], bad[:MAX_BULLETS], goal(runs, wellness, habits, zones, ai_safe)


def goal(runs: dict, wellness: list[dict], habits: list[dict], zones: dict,
         ai_safe: bool = False) -> str:
    """One goal for the coming week, from the first rule that fires."""
    done, planned = runs["done"], runs["planned"]
    if planned and runs["planned_done"] < planned:
        return f"Get all of this week's planned runs done (last week {runs['planned_done']} of {planned})."
    if not done:
        return "Get two easy runs in this week — short is fine."
    total = sum(v for k, v in zones.items() if k != "below") if zones else 0
    if total and (zones.get("Z1", 0) + zones.get("Z2", 0)) / total < 0.5:
        return "Keep easy runs easy: walk when your heart rate passes the top of zone 2."
    sleep = next((r for r in wellness if r["metric"] == "sleep"), None)
    if sleep and sleep["this_week"] is not None and sleep["this_week"] < 7:
        return f"Aim for 7 hours of sleep a night (last week {sleep['this_week']:g} h)."
    worse = [h for h in habits if h["better"] is False
             and not (ai_safe and h["habit"] == "private") and h["habit"] != "private"]
    if worse:
        return f"Bring {HABIT_NOUNS[worse[0]['habit']]} back below {worse[0]['previous_week']:g} this week."
    return f"Repeat last week: {done} run{'s' if done != 1 else ''} at an easy effort."
