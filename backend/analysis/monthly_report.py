"""Monthly health report (R13 §11): one calendar month against the month before, three
things that went well, three to improve and one goal. Deterministic. Pure.

Built on the weekly report's maths (analysis.weekly_report): the same wellness
thresholds and habit rows, with month labels.
"""

from __future__ import annotations

from . import weekly_report as weekly

MAX_BULLETS = 3
HABIT_LABELS = {**weekly.HABIT_LABELS, "caffeine": "Caffeine (cups)"}
HABIT_NOUNS = {**weekly.HABIT_NOUNS, "caffeine": "cups of caffeine"}
MOOD_DELTA = 0.3
VO2_DELTA = 0.5
AGE_DELTA = 0.5


def wellness_rows(this_month: dict[str, list], previous_month: dict[str, list]) -> list[dict]:
    return [{"metric": r["metric"], "label": r["label"], "unit": r["unit"],
             "this_month": r["this_week"], "previous_month": r["previous_week"],
             "delta": r["delta"], "better": r["better"]}
            for r in weekly.wellness_rows(this_month, previous_month)]


def habit_rows(this_month: dict[str, float], previous_month: dict[str, float],
               kinds: list[str]) -> list[dict]:
    rows = []
    for kind in kinds:
        now = round(this_month.get(kind, 0.0), 1)
        before = round(previous_month.get(kind, 0.0), 1)
        delta = round(now - before, 1)
        rows.append({"habit": kind, "label": HABIT_LABELS[kind], "this_month": now,
                     "previous_month": before, "delta": delta,
                     "better": None if delta == 0 else delta < 0})
    return rows


def change(start, end, digits: int = 1) -> dict:
    delta = round(end - start, digits) if start is not None and end is not None else None
    return {"start": start, "end": end, "change": delta}


def mood_block(this: list[tuple[int, int]], before: list[tuple[int, int]]) -> dict:
    def avg(rows, i):
        return round(sum(r[i] for r in rows) / len(rows), 1) if rows else None

    return {"mood_avg": avg(this, 0), "energy_avg": avg(this, 1), "days": len(this),
            "previous_mood_avg": avg(before, 0), "previous_energy_avg": avg(before, 1)}


def _km(value: float) -> str:
    return f"{value:.1f} km"


def bullets(*, runs: dict, prs: list[dict], fitness: dict, wellness: list[dict],
            habits: list[dict], smoke_free_days: int | None, mood: dict,
            weight: dict | None, diet_goal: str, injury: dict,
            ai_safe: bool = False) -> tuple[list[str], list[str], str]:
    good: list[str] = []
    bad: list[str] = []
    count, previous = runs["count"], runs["previous_count"]
    if runs.get("planned"):
        line = f"{runs['planned_done']} of {runs['planned']} planned runs done"
        (good if runs["planned_done"] >= runs["planned"] * 0.8 else bad).append(line)
    if count and previous and count != previous:
        line = f"{count} runs this month vs {previous} the month before"
        (good if count > previous else bad).append(line)
    elif count and not previous:
        good.append(f"{count} run{'s' if count != 1 else ''} logged")
    if runs["km"] and runs["previous_km"] and abs(runs["km"] - runs["previous_km"]) >= 1:
        if runs["km"] > runs["previous_km"]:
            good.append(f"Distance up to {_km(runs['km'])} from {_km(runs['previous_km'])}")
    for pr in prs[:1]:
        good.append(f"New personal record: {pr['label']} {pr['display']}")
    vo2 = fitness.get("vo2max") or {}
    if vo2.get("change") is not None and abs(vo2["change"]) >= VO2_DELTA:
        line = f"VO2max {vo2['start']:g} → {vo2['end']:g}"
        (good if vo2["change"] > 0 else bad).append(line)
    age = fitness.get("fitness_age") or {}
    if age.get("change") is not None and abs(age["change"]) >= AGE_DELTA:
        line = f"Fitness age {age['start']:g} → {age['end']:g}"
        (good if age["change"] < 0 else bad).append(line)
    for row in wellness:
        if row["better"] is None:
            continue
        unit = f" {row['unit']}" if row["unit"] else ""
        text = f"{row['label']} {row['previous_month']:g} → {row['this_month']:g}{unit}"
        (good if row["better"] else bad).append(text)
    if smoke_free_days:
        good.append(f"{smoke_free_days} smoke-free day{'s' if smoke_free_days != 1 else ''}")
    for row in habits:
        if row["better"] is None or row["habit"] == "private" and ai_safe:
            continue
        noun = HABIT_NOUNS[row["habit"]]
        text = f"{row['this_month']:g} {noun} vs {row['previous_month']:g} the month before"
        (good if row["better"] else bad).append(text[0].upper() + text[1:]
                                                if noun[0].islower() else text)
    if mood.get("mood_avg") is not None and mood.get("previous_mood_avg") is not None:
        diff = mood["mood_avg"] - mood["previous_mood_avg"]
        if abs(diff) >= MOOD_DELTA:
            line = f"Mood {mood['previous_mood_avg']:g} → {mood['mood_avg']:g} (of 5)"
            (good if diff > 0 else bad).append(line)
    if weight and weight.get("change") is not None:
        delta = weight["change"]
        text = f"Weight {weight['start']:g} → {weight['end']:g} kg"
        if diet_goal == "lose":
            if delta <= -0.3:
                good.append(text)
            elif delta >= 0.5:
                bad.append(text)
        elif diet_goal == "gain":
            if delta >= 0.3:
                good.append(text)
            elif delta <= -0.5:
                bad.append(text)
        elif abs(delta) >= 1.5:
            bad.append(text)
    if injury.get("flags"):
        bad.append(f"{injury['flags']} injury-watch flag{'s' if injury['flags'] != 1 else ''} "
                   "this month")
    elif injury.get("pain_days"):
        bad.append(f"Pain reported on {injury['pain_days']} day"
                   f"{'s' if injury['pain_days'] != 1 else ''}")
    if not count:
        bad.insert(0, "No runs logged this month")
    return good[:MAX_BULLETS], bad[:MAX_BULLETS], goal(runs, wellness, habits, injury, ai_safe)


def goal(runs: dict, wellness: list[dict], habits: list[dict], injury: dict,
         ai_safe: bool = False) -> str:
    if runs.get("planned") and runs["planned_done"] < runs["planned"] * 0.8:
        return (f"Get more of the planned runs done next month (this month "
                f"{runs['planned_done']} of {runs['planned']}).")
    if not runs["count"]:
        return "Two easy runs a week next month — short is fine."
    if injury.get("flags") or injury.get("pain_days"):
        return "Keep easy days truly easy and ease off at the first niggle."
    sleep = next((r for r in wellness if r["metric"] == "sleep"), None)
    if sleep and sleep["this_month"] is not None and sleep["this_month"] < 7:
        return f"Aim for 7 hours of sleep a night (this month {sleep['this_month']:g} h)."
    worse = [h for h in habits if h["better"] is False and h["habit"] != "private"]
    if worse:
        return (f"Bring {HABIT_NOUNS[worse[0]['habit']]} back below "
                f"{worse[0]['previous_month']:g} next month.")
    return f"Keep the rhythm: about {runs['count']} easy runs again next month."
