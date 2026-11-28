"""`/weather/today/` for one athlete, the check-in's weather inputs, and location.

Location: the athlete's typed city wins (geocoded on save, source "city"); otherwise
the GPS start of their most recent run with a position (source "runs"), rounded to 2
decimals before it is ever stored.
"""

from __future__ import annotations

import datetime as dt

from analysis.weather_advice import advise, condition

from . import weather


def location_from_runs(athlete) -> tuple[float, float] | None:
    from apps.activities.models import ActivityRecord

    record = (ActivityRecord.objects
              .filter(activity__athlete=athlete, activity__sport__icontains="run",
                      latitude__isnull=False, longitude__isnull=False)
              .order_by("-activity__started_at", "offset_s")
              .values_list("latitude", "longitude").first())
    if record is None:
        return None
    return weather.round_coord(record[0]), weather.round_coord(record[1])


def refresh_location(athlete) -> None:
    """Auto location from runs, unless the athlete set a city. Saves only on change."""
    # Re-read first: a long-lived Athlete object must never overwrite a city saved since.
    athlete.refresh_from_db(fields=["location_lat", "location_lon", "location_name",
                                    "location_source", "location_city"])
    if athlete.location_source == "city":
        return
    found = location_from_runs(athlete)
    if found is None:
        fields = {"location_lat": None, "location_lon": None, "location_source": "none"}
        if athlete.location_source == "none":
            return
        fields["location_name"] = ""
    else:
        fields = {"location_lat": found[0], "location_lon": found[1],
                  "location_source": "runs"}
        if (athlete.location_lat, athlete.location_lon) != found:
            fields["location_name"] = "Near your recent runs"
    if all(getattr(athlete, k) == v for k, v in fields.items()):
        return
    for key, value in fields.items():
        setattr(athlete, key, value)
    athlete.save(update_fields=[*fields, "updated_at"])


def _series(block: dict | None, key: str) -> dict:
    block = block or {}
    return dict(zip(block.get("time") or [], block.get(key) or []))


def _hourly(fc: dict, aq: dict | None, local_now: dt.datetime) -> list[dict]:
    hourly = fc.get("hourly") or {}
    aq_hourly = (aq or {}).get("hourly")
    aqi, pm = _series(aq_hourly, "us_aqi"), _series(aq_hourly, "pm2_5")
    start = local_now.replace(tzinfo=None, minute=0, second=0, microsecond=0)
    out = []
    for i, time in enumerate(hourly.get("time") or []):
        try:
            at = dt.datetime.fromisoformat(time)
        except ValueError:
            continue
        if not start <= at < start + dt.timedelta(hours=24):
            continue

        def get(key):
            values = hourly.get(key) or []
            return values[i] if i < len(values) else None

        out.append({"time": time, "temp": get("temperature_2m"),
                    "feels_like": get("apparent_temperature"),
                    "humidity": get("relative_humidity_2m"), "dew_point": get("dew_point_2m"),
                    "precip_prob": get("precipitation_probability"),
                    "wind": get("wind_speed_10m"), "uv": get("uv_index"),
                    "weather_code": get("weather_code"), "condition": condition(get("weather_code")),
                    "aqi": aqi.get(time), "pm25": pm.get(time)})
    return out


def _now(fc: dict, aq: dict | None, hourly: list[dict]) -> dict:
    cur = fc.get("current") or {}
    first = hourly[0] if hourly else {}
    aq_cur = (aq or {}).get("current") or {}
    code = cur.get("weather_code", first.get("weather_code"))
    return {"temp": cur.get("temperature_2m", first.get("temp")),
            "feels_like": cur.get("apparent_temperature", first.get("feels_like")),
            "humidity": cur.get("relative_humidity_2m", first.get("humidity")),
            "dew_point": cur.get("dew_point_2m", first.get("dew_point")),
            "aqi": aq_cur.get("us_aqi", first.get("aqi")),
            "pm25": aq_cur.get("pm2_5", first.get("pm25")),
            "condition": condition(code)}


def _empty(athlete, reason: str) -> dict:
    return {"available": False, "reason": reason, "location_name": athlete.location_name or None,
            "source": athlete.location_source, "now": None, "hourly": [],
            "best_window": None, "advisories": [], "hydration": None, "food": [],
            "daily_water_bonus_ml": 0, "heat": None, "pace_slowdown_pct": 0}


def _today_run_minutes(athlete) -> float | None:
    from apps.planning.checkin_services import today_workout

    workout = today_workout(athlete)
    if workout is None or workout.kind in ("REST", "WALK") or not workout.duration_s:
        return None
    return workout.duration_s / 60


def weather_today(athlete, *, run_minutes: float | None = None,
                  include_run: bool = True) -> dict:
    """The /weather/today/ body. Never raises for weather reasons: no location or an
    outage gives `available: false` with a `reason`."""
    refresh_location(athlete)
    lat, lon = athlete.location_lat, athlete.location_lon
    if lat is None or lon is None:
        return _empty(athlete, "no_location")
    tz = athlete.timezone or "UTC"
    fc = weather.forecast(lat, lon, tz)
    if not fc:
        return _empty(athlete, "unavailable")
    aq = weather.air_quality(lat, lon, tz)
    local_now = athlete.local_now
    hourly = _hourly(fc, aq, local_now)
    now = _now(fc, aq, hourly)
    daily = fc.get("daily") or {}
    today_key = local_now.date().isoformat()
    max_feels = _series(daily, "apparent_temperature_max").get(today_key)
    if run_minutes is None and include_run:
        run_minutes = _today_run_minutes(athlete)
    advice = advise(now, hourly, local_now, max_feels_like=max_feels,
                    run_minutes=run_minutes,
                    measured_l_h=_measured_sweat_rate(athlete, now))
    advice.pop("checkin")
    return {"available": True, "reason": None, "location_name": athlete.location_name or None,
            "source": athlete.location_source, "now": now, "hourly": hourly,
            "daily": {"temp_max": _series(daily, "temperature_2m_max").get(today_key),
                      "temp_min": _series(daily, "temperature_2m_min").get(today_key),
                      "feels_like_max": max_feels},
            **advice}


def checkin_weather(athlete) -> dict:
    """{feels_like, dew_point, aqi, hot} for the morning check-in, or {} without weather."""
    try:
        refresh_location(athlete)
        if athlete.location_lat is None or athlete.location_lon is None:
            return {}
        tz = athlete.timezone or "UTC"
        fc = weather.forecast(athlete.location_lat, athlete.location_lon, tz)
        if not fc:
            return {}
        aq = weather.air_quality(athlete.location_lat, athlete.location_lon, tz)
        local_now = athlete.local_now
        hourly = _hourly(fc, aq, local_now)
        return advise(_now(fc, aq, hourly), hourly, local_now)["checkin"]
    except Exception:  # noqa: BLE001 — weather must never break the check-in
        return {}



def _measured_sweat_rate(athlete, now: dict) -> float | None:
    """His own litres per hour for the band it is now, when he has tested. None
    falls the hydration figures back to the population table, exactly as before.

    Imported late and guarded: hydration advice is not worth a 500 if the health
    app moves, and no sweat test is the normal case, not an error.
    """
    try:
        from analysis.weather_advice import _base, heat_band
        from apps.health.sweat_service import measured_rate

        band = _base(heat_band(now.get("feels_like"), now.get("dew_point")))
        return measured_rate(athlete, band)
    except Exception:  # noqa: BLE001
        return None

def water_bonus_ml(athlete, day: dt.date | None = None) -> tuple[int, list[str]]:
    """(+ml for the daily water target, hot-day food tips) — today only, else (0, [])."""
    if day is not None and day != athlete.local_today:
        return 0, []
    try:
        body = weather_today(athlete, include_run=False)
    except Exception:  # noqa: BLE001
        return 0, []
    if not body["available"]:
        return 0, []
    return body["daily_water_bonus_ml"], body["food"]


def fueling_note(body: dict) -> str | None:
    """One line of forecast-aware drinking advice for a workout."""
    hyd = body.get("hydration")
    if not body.get("available") or not hyd:
        return None
    feels = (body.get("now") or {}).get("feels_like")
    text = f"Feels like {feels:.0f}°C. " if feels is not None else ""
    text += f"Drink about {hyd['before_ml']} ml in the 2 hours before"
    if hyd["during_ml_per_h"]:
        text += f", ~{hyd['during_ml_per_h']} ml per hour while running"
    if hyd["electrolytes"]:
        text += ", with electrolytes (a pinch of salt or an ORS sachet)"
    return text + "."


def workout_weather(athlete, workout) -> dict | None:
    """The workout sheet's "Weather & hydration" block — today's workouts only."""
    if workout.date != athlete.local_today:
        return None
    minutes = workout.duration_s / 60 if workout.duration_s else None
    body = weather_today(athlete, run_minutes=minutes, include_run=False)
    if not body["available"]:
        return {"available": False, "reason": body["reason"]}
    return {"available": True, "location_name": body["location_name"],
            "now": body["now"], "best_window": body["best_window"],
            "advisories": body["advisories"], "hydration": body["hydration"],
            "heat": body["heat"], "pace_slowdown_pct": body["pace_slowdown_pct"],
            "fueling_note": fueling_note(body)}
