"""Weather -> run timing, hydration and food advice (R8 §D). Pure — no Django, no HTTP.

Inputs are plain hourly dicts (local time "YYYY-MM-DDTHH:MM") with temp, feels_like,
humidity, dew_point, precip_prob, wind, uv, weather_code, aqi, pm25 — any may be None.
Every rule can only make running easier or more careful; nothing here raises a target.
"""

from __future__ import annotations

import datetime as dt

HOT_FEELS_C, HOT_DEW_C = 32.0, 24.0
WARM_FEELS_C, WARM_DEW_C = 24.0, 18.0
VERY_HOT_FEELS_C, VERY_HOT_DEW_C = 38.0, 26.0
WINDOW_HOURS = (5, 6, 7, 8, 17, 18, 19)          # start hours: 05-09 and 17-20 local
AQI_CAUTION, AQI_SHORTEN, AQI_BAD = 100, 150, 200
LONG_RUN_FOR_DRINKING_MIN = 45
ELECTROLYTE_MIN = 60
# ml per hour while running, by band: cool 300-400, warm 500-700, hot 700-900.
DURING_ML_H = {"cool": 350, "warm": 600, "hot": 800}
BEFORE_ML = {"cool": 400, "warm": 500, "hot": 600}
SWEAT_L_H = {"cool": 0.5, "warm": 0.8, "hot": 1.2}
SLOWDOWN_PCT = {"cool": 0, "warm": 3, "hot": 8, "very_hot": 12}
THUNDER_CODES = frozenset({95, 96, 99})
RAIN_CODES = frozenset({51, 53, 55, 61, 63, 65, 80, 81, 82})
RAIN_PROB = 60

CONDITIONS = [  # WMO weather codes -> words
    ({0}, "Clear"), ({1, 2}, "Partly cloudy"), ({3}, "Cloudy"), ({45, 48}, "Fog"),
    ({51, 53, 55, 56, 57}, "Drizzle"), ({61, 63, 65, 66, 67}, "Rain"),
    ({71, 73, 75, 77, 85, 86}, "Snow"), ({80, 81, 82}, "Showers"),
    ({95, 96, 99}, "Thunderstorm"),
]


def condition(code) -> str | None:
    if code is None:
        return None
    return next((name for codes, name in CONDITIONS if int(code) in codes), None)


def heat_band(feels_like, dew_point) -> str:
    """cool | warm | hot | very_hot. Dew point counts as much as temperature: sweat
    stops cooling when the air is already wet."""
    f = feels_like if feels_like is not None else -99
    d = dew_point if dew_point is not None else -99
    if f >= VERY_HOT_FEELS_C or d >= VERY_HOT_DEW_C:
        return "very_hot"
    if f >= HOT_FEELS_C or d >= HOT_DEW_C:
        return "hot"
    if f >= WARM_FEELS_C or d >= WARM_DEW_C:
        return "warm"
    return "cool"


def _base(band: str) -> str:
    return "hot" if band == "very_hot" else band


def hydration(band: str, run_minutes: float | None = None) -> dict:
    """Before / during / after. During applies to runs >= 45 min (0 below that);
    electrolytes when hot or the run is over an hour."""
    b = _base(band)
    long_enough = run_minutes is None or run_minutes >= LONG_RUN_FOR_DRINKING_MIN
    during = DURING_ML_H[b] if long_enough else 0
    electrolytes = b == "hot" or (run_minutes is not None and run_minutes > ELECTROLYTE_MIN)
    if run_minutes:
        loss = SWEAT_L_H[b] * run_minutes / 60 * 1000
        after = (f"Afterwards drink about {round(loss * 1.5 / 50) * 50:.0f} ml over the next "
                 "few hours — roughly 1.5× what you sweat out.")
    else:
        after = ("Afterwards replace about 1.5× what you lost: every kg lighter after the "
                 "run is about 1.5 L to drink over the next few hours.")
    return {"before_ml": BEFORE_ML[b], "during_ml_per_h": during, "after_note": after,
            "electrolytes": electrolytes}


def daily_water_bonus_ml(max_feels_like) -> int:
    if max_feels_like is None:
        return 0
    if max_feels_like >= 32:
        return 500
    if max_feels_like >= 28:
        return 250
    return 0


def food_tips(band: str) -> list[str]:
    if _base(band) == "hot":
        return ["Hot day: drink with every meal and add a salty snack (buttermilk with salt, "
                "nimbu pani, salted nuts).",
                "Keep the pre-run meal light — fruit or toast 60–90 min before, not a full "
                "meal."]
    if band == "warm":
        return ["Warm day: a glass of water with each meal and a pinch of salt after a "
                "sweaty run."]
    return []


def _hour(entry) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(entry["time"])
    except (KeyError, TypeError, ValueError):
        return None


def best_window(hourly: list[dict], now: dt.datetime) -> dict | None:
    """Coolest, cleanest-air hour starting within 05:00-09:00 or 17:00-20:00 local, from
    now on (next 24 h). Score = feels-like + an AQI penalty above 50."""
    now = now.replace(tzinfo=None, minute=0, second=0, microsecond=0)
    best = None
    for entry in hourly:
        start = _hour(entry)
        if start is None or not now <= start < now + dt.timedelta(hours=24):
            continue
        if start.hour not in WINDOW_HOURS:
            continue
        feels = entry.get("feels_like")
        if feels is None:
            feels = entry.get("temp")
        if feels is None:
            continue
        aqi = entry.get("aqi")
        score = feels + (max(aqi - 50, 0) / 10 if aqi is not None else 0)
        if best is None or score < best[0]:
            best = (score, start, feels, aqi)
    if best is None:
        return None
    _, start, feels, aqi = best
    reason = f"Coolest slot: feels like {feels:.0f}°C"
    if aqi is not None:
        reason += f", AQI {aqi:.0f}"
    return {"start": start.isoformat(timespec="minutes"),
            "end": (start + dt.timedelta(hours=1)).isoformat(timespec="minutes"),
            "reason": reason}


def air_level(aqi) -> str | None:
    """None (fine) | caution | shorten | bad."""
    if aqi is None:
        return None
    if aqi > AQI_BAD:
        return "bad"
    if aqi > AQI_SHORTEN:
        return "shorten"
    if aqi > AQI_CAUTION:
        return "caution"
    return None


def advisories(now: dict, hourly: list[dict], band: str) -> list[dict]:
    """[{level: info|caution|warning, text}] — heat, air, rain/thunder."""
    out: list[dict] = []
    pct = SLOWDOWN_PCT[band]
    if band in ("hot", "very_hot"):
        out.append({"level": "warning" if band == "very_hot" else "caution",
                    "text": f"Hot and humid: expect to run about {pct}% slower at the same "
                            "effort. Run by heart rate, not pace."})
    elif band == "warm":
        out.append({"level": "info",
                    "text": f"Warm: easy pace may be ~{pct}% slower — let heart rate decide."})
    aqi = now.get("aqi")
    level = air_level(aqi)
    if level == "bad":
        out.append({"level": "warning", "text": f"Air quality is very unhealthy (AQI "
                    f"{aqi:.0f}). Run indoors or take a rest day."})
    elif level == "shorten":
        out.append({"level": "warning", "text": f"Unhealthy air (AQI {aqi:.0f}): shorten "
                    "the run or move it indoors."})
    elif level == "caution":
        out.append({"level": "caution", "text": f"Air quality is poor for exercise (AQI "
                    f"{aqi:.0f}): keep today easy."})
    upcoming = hourly[:12]
    if any(e.get("weather_code") in THUNDER_CODES for e in upcoming):
        out.append({"level": "warning", "text": "Thunderstorms forecast — avoid running "
                    "outside while there is lightning."})
    elif any((e.get("precip_prob") or 0) >= RAIN_PROB or e.get("weather_code") in RAIN_CODES
             for e in upcoming):
        out.append({"level": "caution", "text": "Rain likely: watch your footing, wear "
                    "something you don't mind getting wet."})
    return out


def checkin_signals(now: dict, window: dict | None) -> dict:
    """Weather inputs for the morning check-in: is even the best slot hot, and the AQI."""
    feels = (window or now).get("feels_like")
    dew = (window or now).get("dew_point")
    return {"feels_like": feels, "dew_point": dew, "aqi": now.get("aqi"),
            "hot": heat_band(feels, dew) in ("hot", "very_hot")}


def advise(now: dict, hourly: list[dict], local_now: dt.datetime, *,
           max_feels_like=None, run_minutes: float | None = None) -> dict:
    """Everything `/weather/today/` shows besides location and raw numbers."""
    window = best_window(hourly, local_now)
    window_entry = None
    if window:
        window_entry = next((e for e in hourly if e.get("time", "")[:16] == window["start"]),
                            None)
    band = heat_band((window_entry or now).get("feels_like"),
                     (window_entry or now).get("dew_point"))
    if max_feels_like is None:
        values = [e.get("feels_like") for e in hourly[:24] if e.get("feels_like") is not None]
        max_feels_like = max(values) if values else now.get("feels_like")
    return {
        "best_window": window,
        "heat": band,
        "pace_slowdown_pct": SLOWDOWN_PCT[band],
        "advisories": advisories(now, hourly, heat_band(now.get("feels_like"),
                                                         now.get("dew_point"))),
        "hydration": hydration(band, run_minutes),
        "food": food_tips(heat_band(max_feels_like, None)),
        "daily_water_bonus_ml": daily_water_bonus_ml(max_feels_like),
        "checkin": checkin_signals(now, window_entry),
    }
