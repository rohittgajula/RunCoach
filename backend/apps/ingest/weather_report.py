"""`GET /weather/report/` (R14 §3): now, 48 h hourly with run ratings and best windows,
7 days, sun times, hydration/food advice and this week's runs vs the weather.

Never an error for weather reasons: no location or an Open-Meteo outage gives
`available: false` with a `reason` (same as /weather/today/)."""

from __future__ import annotations

import datetime as dt

from django.utils import timezone

from analysis import weather_plan as wp
from analysis.weather_advice import advise, condition

from . import weather
from .weather_services import _series, refresh_location

REPORT_HOURS = 48


def all_hourly(fc: dict | None, aq: dict | None) -> list[dict]:
    """Every forecast hour (7 days) in the /weather/today/ hourly shape."""
    hourly = (fc or {}).get("hourly") or {}
    aq_hourly = (aq or {}).get("hourly")
    aqi, pm = _series(aq_hourly, "us_aqi"), _series(aq_hourly, "pm2_5")
    out = []
    for i, time in enumerate(hourly.get("time") or []):
        def get(key):
            values = hourly.get(key) or []
            return values[i] if i < len(values) else None

        out.append({"time": time, "temp": get("temperature_2m"),
                    "feels_like": get("apparent_temperature"),
                    "humidity": get("relative_humidity_2m"), "dew_point": get("dew_point_2m"),
                    "precip_prob": get("precipitation_probability"),
                    "wind": get("wind_speed_10m"), "uv": get("uv_index"),
                    "weather_code": get("weather_code"),
                    "condition": condition(get("weather_code")),
                    "aqi": aqi.get(time), "pm25": pm.get(time)})
    return out


def forecast_for(athlete) -> tuple[list[dict], dict | None, dict | None] | None:
    """(hourly for 7 days, raw forecast, raw air quality), or None (no location/outage)."""
    refresh_location(athlete)
    lat, lon = athlete.location_lat, athlete.location_lon
    if lat is None or lon is None:
        return None
    tz = athlete.timezone or "UTC"
    fc = weather.forecast_report(lat, lon, tz)
    if not fc:
        return None
    aq = weather.air_quality_report(lat, lon, tz)
    return all_hourly(fc, aq), fc, aq


def day_checks(hourly: list[dict], start: dt.date, days: int = 7) -> dict[dt.date, wp.DayCheck]:
    return {start + dt.timedelta(days=i): wp.check_day(hourly, start + dt.timedelta(days=i))
            for i in range(days)}


def _clock(value) -> str | None:
    if not value or "T" not in str(value):
        return None
    return str(value)[11:16]


def _empty(athlete, reason: str) -> dict:
    return {"available": False, "reason": reason,
            "location_name": athlete.location_name or None, "source": athlete.location_source,
            "generated_at": timezone.now(), "now": None, "hourly": [], "best_windows": [],
            "daily": [], "sun": {"sunrise": None, "sunset": None}, "heat": None,
            "pace_slowdown_pct": 0, "advisories": [], "hydration": None, "food": [],
            "daily_water_bonus_ml": 0, "runs": [], "suggestions": []}


def _daily(fc: dict, hourly: list[dict], checks: dict) -> list[dict]:
    daily = fc.get("daily") or {}
    out = []
    for i, day in enumerate(daily.get("time") or []):
        def get(key):
            values = daily.get(key) or []
            return values[i] if i < len(values) else None

        try:
            date = dt.date.fromisoformat(day)
        except ValueError:
            continue
        aqis = [h["aqi"] for h in hourly if h["time"][:10] == day and h.get("aqi") is not None]
        check = checks.get(date) or wp.check_day(hourly, date)
        prob = get("precipitation_probability_max")
        out.append({"date": day, "temp_min": get("temperature_2m_min"),
                    "temp_max": get("temperature_2m_max"),
                    "feels_like_max": get("apparent_temperature_max"),
                    "precip_prob_max": int(prob) if prob is not None else None,
                    "precip_mm": get("precipitation_sum"),
                    "weather_code": get("weather_code"), "condition": condition(get("weather_code")),
                    "uv_max": get("uv_index_max"), "aqi_max": max(aqis) if aqis else None,
                    "sunrise": _clock(get("sunrise")), "sunset": _clock(get("sunset")),
                    "run_verdict": check.verdict, "reasons": wp.day_reasons(check)})
    return out


def report(athlete) -> dict:
    from apps.planning import weather_swap

    found = forecast_for(athlete)
    if found is None:
        reason = "no_location" if athlete.location_lat is None else "unavailable"
        return _empty(athlete, reason)
    hourly_all, fc, aq = found
    local_now = athlete.local_now
    today = local_now.date()
    start = local_now.replace(tzinfo=None, minute=0, second=0, microsecond=0)
    hourly = [h for h in hourly_all
              if start <= dt.datetime.fromisoformat(h["time"]) < start + dt.timedelta(
                  hours=REPORT_HOURS)]
    windows = wp.best_windows(hourly, local_now, REPORT_HOURS)
    window_starts = {w["start"] for w in windows}
    for h in hourly:
        h["run"] = wp.hour_rating(h)
        h["best"] = h["time"][:16] in window_starts

    cur = fc.get("current") or {}
    first = hourly[0] if hourly else {}
    aq_cur = (aq or {}).get("current") or {}
    aqi = aq_cur.get("us_aqi", first.get("aqi"))
    level, meaning = wp.aqi_level(aqi)
    uv = cur.get("uv_index", first.get("uv"))
    code = cur.get("weather_code", first.get("weather_code"))
    now = {"time": cur.get("time") or first.get("time"),
           "temp": cur.get("temperature_2m", first.get("temp")),
           "feels_like": cur.get("apparent_temperature", first.get("feels_like")),
           "humidity": cur.get("relative_humidity_2m", first.get("humidity")),
           "dew_point": cur.get("dew_point_2m", first.get("dew_point")),
           "wind": cur.get("wind_speed_10m", first.get("wind")), "uv": uv,
           "weather_code": code, "condition": condition(code),
           "aqi": aqi, "pm25": aq_cur.get("pm2_5", first.get("pm25")),
           "aqi_level": level, "aqi_meaning": meaning, "uv_level": wp.uv_level(uv)}

    checks = day_checks(hourly_all, today)
    daily = _daily(fc, hourly_all, checks)
    today_row = next((d for d in daily if d["date"] == today.isoformat()), None)
    run_minutes = None
    try:
        from .weather_services import _today_run_minutes

        run_minutes = _today_run_minutes(athlete)
    except Exception:  # noqa: BLE001
        run_minutes = None
    advice = advise(now, hourly[:24], local_now,
                    max_feels_like=(today_row or {}).get("feels_like_max"),
                    run_minutes=run_minutes)
    advice.pop("checkin")
    advice.pop("best_window", None)

    try:
        weather_swap.check(athlete, hourly=hourly_all)
    except Exception:  # noqa: BLE001 — the report never fails because of the check
        import logging

        logging.getLogger(__name__).exception("weather swap check failed for %s", athlete.pk)
    pending = weather_swap.pending(athlete)
    runs = weather_swap.runs_vs_weather(athlete, checks, pending)
    return {"available": True, "reason": None, "location_name": athlete.location_name or None,
            "source": athlete.location_source, "generated_at": timezone.now(), "now": now,
            "hourly": hourly, "best_windows": windows, "daily": daily,
            "sun": {"sunrise": (today_row or {}).get("sunrise"),
                    "sunset": (today_row or {}).get("sunset")},
            **advice, "runs": runs,
            "suggestions": [weather_swap.suggestion_json(s) for s in pending]}
