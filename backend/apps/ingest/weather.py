"""Open-Meteo forecast, air quality and geocoding (R8 §D). Keyless, public.

Every call has a 5 s timeout and every failure becomes "no weather" (None) — weather
is a nice-to-have and must never turn a page into an error. Responses are cached per
rounded location per hour, so the app makes at most a couple of calls an hour per
place however many people open it.

Location is stored rounded to 2 decimals (~1 km): enough for a forecast, not enough
to find someone's front door.
"""

from __future__ import annotations

import logging

import httpx
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

TIMEOUT_S = 5.0
CACHE_S = 60 * 60
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
HOURLY = ("temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,"
          "precipitation_probability,wind_speed_10m,uv_index,weather_code")
CURRENT = ("temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,"
           "weather_code,wind_speed_10m")
DAILY = "temperature_2m_max,temperature_2m_min,apparent_temperature_max"


class WeatherUnavailable(Exception):
    """Open-Meteo could not be reached or answered badly."""


def round_coord(value) -> float | None:
    return None if value is None else round(float(value), 2)


def _get_json(url: str, params: dict) -> dict:
    """The one place that talks to the network (patched in tests)."""
    try:
        response = httpx.get(url, params=params, timeout=TIMEOUT_S)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise WeatherUnavailable(str(exc)) from exc


def _key(kind: str, lat: float, lon: float, tz: str) -> str:
    hour = timezone.now().strftime("%Y%m%d%H")
    return f"wx:{kind}:{lat:.2f}:{lon:.2f}:{tz}:{hour}"


def cached_only(kind: str, lat: float, lon: float, tz: str) -> dict | None:
    """R9 §E: this hour's cached response ("fc" or "aq"), never a network call."""
    try:
        return cache.get(_key(kind, lat, lon, tz))
    except Exception:  # noqa: BLE001 — a cache outage is just "no weather"
        return None


def _cached(kind: str, lat: float, lon: float, tz: str, fetch):
    key = _key(kind, lat, lon, tz)
    data = cache.get(key)
    if data is not None:
        return data
    try:
        data = fetch()
    except WeatherUnavailable as exc:
        logger.info("weather %s unavailable for %.2f,%.2f: %s", kind, lat, lon, exc)
        return None
    cache.set(key, data, CACHE_S)
    return data


def forecast(lat: float, lon: float, tz: str) -> dict | None:
    params = {"latitude": lat, "longitude": lon, "hourly": HOURLY, "current": CURRENT,
              "daily": DAILY, "timezone": tz, "forecast_days": 2}
    return _cached("fc", lat, lon, tz, lambda: _get_json(FORECAST_URL, params))


def air_quality(lat: float, lon: float, tz: str) -> dict | None:
    params = {"latitude": lat, "longitude": lon, "hourly": "pm2_5,us_aqi",
              "current": "pm2_5,us_aqi", "timezone": tz, "forecast_days": 2}
    return _cached("aq", lat, lon, tz, lambda: _get_json(AIR_URL, params))


def geocode(query: str) -> dict | None:
    """'Hyderabad, India' -> {lat, lon, name}. None when nothing matches.
    Raises WeatherUnavailable on an outage (the caller tells the athlete to retry)."""
    parts = [p.strip() for p in (query or "").split(",") if p.strip()]
    if not parts:
        return None
    data = _get_json(GEOCODE_URL, {"name": parts[0], "count": 10, "language": "en",
                                   "format": "json"})
    results = data.get("results") or []
    hint = " ".join(parts[1:]).lower()
    if hint:
        narrowed = [r for r in results if hint in " ".join(
            str(r.get(k) or "") for k in ("country", "country_code", "admin1")).lower()]
        results = narrowed or results
    if not results:
        return None
    top = results[0]
    name = ", ".join(str(x) for x in (top.get("name"), top.get("admin1") or None,
                                      top.get("country")) if x)
    return {"lat": round_coord(top["latitude"]), "lon": round_coord(top["longitude"]),
            "name": name[:120]}


def forecast_week(lat: float, lon: float, tz: str) -> dict | None:
    """R13 §2: hourly forecast for the next 8 days (race-day planner), cached like the rest."""
    params = {"latitude": lat, "longitude": lon, "hourly": HOURLY, "timezone": tz,
              "forecast_days": 8}
    return _cached("fc8", lat, lon, tz, lambda: _get_json(FORECAST_URL, params))


def hour_at(fc: dict | None, day, hour: int) -> dict | None:
    """The hourly entry for local `day` at `hour` from a forecast_week response."""
    if not fc:
        return None
    hourly = fc.get("hourly") or {}
    wanted = f"{day.isoformat()}T{hour:02d}:00"
    times = hourly.get("time") or []
    if wanted not in times:
        return None
    i = times.index(wanted)

    def get(key):
        values = hourly.get(key) or []
        return values[i] if i < len(values) else None

    return {"time": wanted, "temp": get("temperature_2m"), "feels_like": get("apparent_temperature"),
            "humidity": get("relative_humidity_2m"), "dew_point": get("dew_point_2m"),
            "precip_prob": get("precipitation_probability"), "wind": get("wind_speed_10m")}


# --- R14 §3: the Weather report (7-day forecast + 5-day air quality) --------------------
REPORT_DAILY = ("temperature_2m_max,temperature_2m_min,apparent_temperature_max,"
                "precipitation_probability_max,precipitation_sum,weather_code,uv_index_max,"
                "sunrise,sunset")
REPORT_CURRENT = CURRENT + ",uv_index"


def forecast_report(lat: float, lon: float, tz: str) -> dict | None:
    params = {"latitude": lat, "longitude": lon, "hourly": HOURLY, "current": REPORT_CURRENT,
              "daily": REPORT_DAILY, "timezone": tz, "forecast_days": 7}
    return _cached("fc7", lat, lon, tz, lambda: _get_json(FORECAST_URL, params))


def air_quality_report(lat: float, lon: float, tz: str) -> dict | None:
    params = {"latitude": lat, "longitude": lon, "hourly": "pm2_5,us_aqi",
              "current": "pm2_5,us_aqi", "timezone": tz, "forecast_days": 5}
    return _cached("aq5", lat, lon, tz, lambda: _get_json(AIR_URL, params))
