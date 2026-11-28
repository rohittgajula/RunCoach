"""Race-day planner (R13 §2). Pure — no Django.

Pacing, fueling, warm-up, the taper checklist for the last 10 days and the race-morning
timeline. Every number is a conservative rule of thumb, written so a beginner finishes
strong rather than blowing up at halfway:

* **Target**: the athlete's goal when it is within 5 % of the prediction (or there is
  no prediction); a goal more than 5 % faster than predicted is shown but the pacing
  uses the prediction. Hot forecast → the R8 heat slowdown is added to the target.
* **Splits**: even (same pace every km) or negative (first half 2 % slower, second half
  makes up exactly the difference). The last split may be a partial km.
* **Fueling**: carbs by expected duration (none under an hour, then 30 / 45 / 60 g per
  hour), one item every 30 min; fluid by heat band (R8 weather hydration) once the race
  is 45 min or longer; electrolytes when hot or over 90 min.
"""

from __future__ import annotations

import datetime as dt
import math

from analysis.weather_advice import SLOWDOWN_PCT, heat_band, hydration

GOAL_TOLERANCE = 0.05
NEGATIVE_FIRST_HALF = 1.02
TAPER_DAYS = 10
DEFAULT_START_MIN = 6 * 60 + 30
SHOE_MAX_KM = 600.0
SHOE_WORN_IN_KM = 20.0
SLEEP_TARGET_H = 7.0
FUEL_EVERY_S = 30 * 60


def clock(minutes: int) -> str:
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def fmt_time(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def target(distance_km: float, goal_s: int | None, predicted_s: float | None,
           garmin_s: float | None, slowdown_pct: int = 0) -> dict | None:
    predicted = predicted_s or garmin_s
    source_pred = "prediction" if predicted_s else "garmin"
    note = None
    if goal_s and predicted:
        if goal_s < predicted * (1 - GOAL_TOLERANCE):
            time_s, source = predicted, source_pred
            note = (f"Your goal ({fmt_time(goal_s)}) is more than 5% faster than predicted "
                    f"({fmt_time(predicted)}). Pacing uses the prediction — if you feel "
                    "strong after halfway, speed up then.")
        else:
            time_s, source = goal_s, "goal"
    elif goal_s:
        time_s, source = goal_s, "goal"
    elif predicted:
        time_s, source = predicted, source_pred
    else:
        return None
    if slowdown_pct:
        time_s = time_s * (1 + slowdown_pct / 100)
        heat = f"Heat forecast: the target is {slowdown_pct}% slower than usual."
        note = f"{note} {heat}" if note else heat
    time_s = int(round(time_s))
    return {"time_s": time_s, "pace_s_per_km": int(round(time_s / distance_km)),
            "source": source, "goal_time_s": goal_s,
            "predicted_time_s": int(round(predicted)) if predicted else None, "note": note}


def splits(distance_km: float, time_s: int, strategy: str = "even") -> list[dict]:
    """Per-km splits summing exactly to `time_s` (rounding goes into the last one)."""
    if distance_km <= 0 or time_s <= 0:
        return []
    full = int(math.floor(distance_km + 1e-9))
    marks = [float(k) for k in range(1, full + 1)]
    if distance_km - full > 0.05:
        marks.append(round(distance_km, 2))
    elif marks:
        marks[-1] = round(distance_km, 2) if abs(distance_km - full) > 1e-9 else marks[-1]
    avg = time_s / distance_km
    half = distance_km / 2
    if strategy == "negative":
        first = avg * NEGATIVE_FIRST_HALF
        second = (time_s - first * half) / (distance_km - half)
    else:
        first = second = avg
    out = []
    elapsed = 0.0
    previous = 0.0
    shown = 0
    for index, mark in enumerate(marks):
        length = mark - previous
        # Portion of this km in each half.
        in_first = max(0.0, min(mark, half) - previous)
        in_second = length - in_first
        seconds = in_first * first + in_second * second
        elapsed += seconds
        # Splits are differences of rounded elapsed times, so they always add up.
        at = time_s if index == len(marks) - 1 else int(round(elapsed))
        out.append({"km": mark, "split_s": at - shown,
                    "pace_s_per_km": int(round(seconds / length)) if length else 0,
                    "elapsed_s": at})
        shown = at
        previous = mark
    return out


def carbs_per_hour(duration_s: float | None) -> int:
    if not duration_s or duration_s < 60 * 60:
        return 0
    if duration_s < 90 * 60:
        return 30
    if duration_s < 150 * 60:
        return 45
    return 60


def fueling(duration_s: int | None, pace_s_per_km: int | None, feels_like: float | None,
            dew_point: float | None, distance_km: float,
            measured_l_h: float | None = None) -> dict:
    """`measured_l_h` is his own sweat rate from a sweat test, when he has one. On
    race day the band average is the weakest number in the whole plan: it decides
    how much he carries and how often he stops, and it is the one figure here that
    a single weigh-in replaces outright."""
    band = heat_band(feels_like, dew_point)
    minutes = duration_s / 60 if duration_s else None
    water = hydration(band, minutes, measured_l_h)
    carbs = carbs_per_hour(duration_s)
    items = [{"at_s": -180 * 60, "at_km": None, "what": "Breakfast you have tried before",
              "amount": "Mostly carbs, 2–3 h before the start (e.g. toast, banana, rice)"},
             {"at_s": -30 * 60, "at_km": None, "what": "Water",
              "amount": f"{water['before_ml']} ml over the last hour, then stop"}]
    if carbs and duration_s:
        per_item = round(carbs / 2)
        at = FUEL_EVERY_S
        while at < duration_s - 10 * 60:
            items.append({"at_s": at,
                          "at_km": round(at / pace_s_per_km, 1) if pace_s_per_km else None,
                          "what": "Gel or sports drink",
                          "amount": f"About {per_item} g carbs with a few sips of water"})
            at += FUEL_EVERY_S
    if water["during_ml_per_h"] and duration_s:
        items.append({"at_s": 15 * 60, "at_km": round(15 * 60 / pace_s_per_km, 1)
                      if pace_s_per_km else None, "what": "Drink at every aid station",
                      "amount": f"About {water['during_ml_per_h']} ml per hour in small sips"})
    items.append({"at_s": (duration_s or 0) + 30 * 60, "at_km": None,
                  "what": "Recovery", "amount": "Carbs + protein and 500 ml fluid within 30 min"})
    items.sort(key=lambda i: i["at_s"])
    notes = ["Use only what you have tried in training — nothing new on race day."]
    if not carbs:
        notes.append("Under an hour: no gels needed; breakfast is enough.")
    if water["electrolytes"] or (duration_s and duration_s > 90 * 60):
        notes.append("Add electrolytes (a tab in your bottle or a sports drink).")
    if band in ("hot", "very_hot"):
        notes.append("Hot forecast: drink early, pour water over your head, slow down.")
    return {"duration_s": duration_s, "carbs_g_per_h": carbs,
            "fluid_ml_per_h": water["during_ml_per_h"],
            "electrolytes": bool(water["electrolytes"] or (duration_s and duration_s > 90 * 60)),
            "items": items, "notes": notes}


def weather_block(hour: dict | None, race_date: dt.date, hour_label: str) -> dict | None:
    if not hour:
        return None
    feels, dew = hour.get("feels_like"), hour.get("dew_point")
    band = heat_band(feels, dew)
    advice = []
    if band in ("hot", "very_hot"):
        advice.append("Start slower than planned and walk the aid stations.")
    if band == "warm":
        advice.append("Warm: drink a little at every aid station.")
    if (hour.get("precip_prob") or 0) >= 60:
        advice.append("Rain likely: bring a bin bag for the start and anti-chafe.")
    if feels is not None and feels < 8:
        advice.append("Cold start: wear an old top you can throw away after 2 km.")
    return {"date": race_date, "hour": hour_label, "temp_c": hour.get("temp"),
            "feels_like_c": feels, "humidity": hour.get("humidity"), "dew_point": dew,
            "precip_prob": hour.get("precip_prob"), "wind_kmh": hour.get("wind"),
            "heat": band, "pace_slowdown_pct": SLOWDOWN_PCT[band], "advice": advice}


def warmup(distance_km: float) -> list[dict]:
    steps = [{"label": "Brisk walk", "duration_s": 300,
              "detail": "Loosen up; get the heart rate up a little."}]
    if distance_km <= 21.1:
        steps.append({"label": "Easy jog", "duration_s": 300 if distance_km <= 10 else 180,
                      "detail": "Very easy — you should be able to chat."})
    steps.append({"label": "Leg swings and drills", "duration_s": 180,
                  "detail": "10 leg swings each way per leg, a few A-skips."})
    if distance_km <= 10:
        steps.append({"label": "2–3 relaxed strides", "duration_s": 60,
                      "detail": "20 s quick and light, walk back. Not a sprint."})
    steps.append({"label": "Walk to the start", "duration_s": 300,
                  "detail": "Finish warming up 10 minutes before the gun; keep moving."})
    return steps


def taper(race_date: dt.date, today: dt.date, distance_km: float,
          sleep_avg_h: float | None, shoe: dict | None) -> dict:
    starts = race_date - dt.timedelta(days=TAPER_DAYS)
    items = []
    if sleep_avg_h is None:
        status, detail = "todo", "Aim for 7–9 hours a night this week; the night before matters least."
    elif sleep_avg_h >= SLEEP_TARGET_H:
        status, detail = "ok", f"Averaging {sleep_avg_h:.1f} h a night — keep it up."
    else:
        status, detail = "warn", (f"Averaging {sleep_avg_h:.1f} h a night — try to bank more "
                                  "sleep before race week ends.")
    items.append({"key": "sleep", "label": "Sleep", "detail": detail, "due_on": None,
                  "status": status})
    if distance_km >= 21:
        items.append({"key": "carbs", "label": "Carbs up", "detail":
                      "For the 2 days before: more rice, bread, pasta, potatoes; less fibre and fat.",
                      "due_on": race_date - dt.timedelta(days=2), "status": "info"})
    else:
        items.append({"key": "carbs", "label": "Normal meals, carb-rich dinner",
                      "detail": "No carb-loading needed for this distance — a normal, "
                      "familiar dinner the night before.",
                      "due_on": race_date - dt.timedelta(days=1), "status": "info"})
    items.append({"key": "kit", "label": "Kit laid out", "detail":
                  "Clothes you've run in, socks, watch charged, gels, bib pins.",
                  "due_on": race_date - dt.timedelta(days=1), "status": "todo"})
    items.append({"key": "route", "label": "Route and start", "detail":
                  "Check the course map, aid stations, start time and how you'll get there.",
                  "due_on": race_date - dt.timedelta(days=3), "status": "todo"})
    items.append({"key": "bib", "label": "Bib collected", "detail":
                  "Collect your bib and timing chip (expo / post).",
                  "due_on": race_date - dt.timedelta(days=1), "status": "todo"})
    if shoe is None:
        items.append({"key": "shoes", "label": "Shoes", "detail":
                      "Race in shoes you've already run in (at least 20 km), not new ones.",
                      "due_on": None, "status": "todo"})
    else:
        km = shoe["distance_km"]
        if km > SHOE_MAX_KM:
            status, detail = "warn", (f"{shoe['name']} has {km:.0f} km — past 600 km. "
                                      "Consider a pair with fewer km that you've run in.")
        elif km < SHOE_WORN_IN_KM:
            status, detail = "warn", (f"{shoe['name']} has only {km:.0f} km — wear them on "
                                      "a few easy runs first.")
        else:
            status, detail = "ok", f"{shoe['name']}: {km:.0f} km — worn in, not worn out."
        items.append({"key": "shoes", "label": "Shoes", "detail": detail, "due_on": None,
                      "status": status})
    return {"starts_on": starts, "in_taper": starts <= today <= race_date, "items": items}


def morning(start_min: int, distance_km: float) -> list[dict]:
    warm = sum(s["duration_s"] for s in warmup(distance_km)) // 60
    return [
        {"time": clock(start_min - 180), "label": "Wake up",
         "detail": "Glass of water, bathroom, check the weather."},
        {"time": clock(start_min - 165), "label": "Breakfast",
         "detail": "The breakfast you practised: mostly carbs, little fibre or fat."},
        {"time": clock(start_min - 90), "label": "Leave",
         "detail": "Bib pinned, gels packed. Arrive about an hour early."},
        {"time": clock(start_min - 60), "label": "Arrive",
         "detail": "Bag drop, bathroom queue, find your start corral."},
        {"time": clock(start_min - 10 - warm), "label": "Warm-up",
         "detail": f"About {warm} min, finishing 10 min before the start."},
        {"time": clock(start_min - 10), "label": "Line up",
         "detail": "Start at the back of your group; the first km should feel easy."},
        {"time": clock(start_min), "label": "Start", "detail": "Run your plan, not the crowd."},
    ]
