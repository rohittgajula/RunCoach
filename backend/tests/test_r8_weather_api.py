"""R8 §D through the API, with Open-Meteo mocked: location from GPS, city override,
cache, outage degradation, check-in heat/air signals and the diet water bonus."""

import datetime as dt

import pytest

from apps.activities.models import ActivityRecord
from apps.athletes.models import Athlete
from apps.ingest import weather
from tests.r6_helpers import make_activity
from tests.r7_helpers import make_workout

KEYS = {"location_name", "source", "now", "hourly", "best_window", "advisories",
        "hydration", "food", "daily_water_bonus_ml"}


class FakeMeteo:
    def __init__(self, athlete, feels=34.0, dew=25.0, aqi=60):
        self.calls, self.athlete, self.feels, self.dew, self.aqi = [], athlete, feels, dew, aqi
        self.down = False

    def times(self):
        day = self.athlete.local_today
        return [f"{day + dt.timedelta(days=h // 24)}T{h % 24:02d}:00" for h in range(48)]

    def __call__(self, url, params):
        self.calls.append((url, dict(params)))
        if self.down:
            raise weather.WeatherUnavailable("timeout")
        t = self.times()
        if url == weather.GEOCODE_URL:
            return {"results": [
                {"name": "Hyderabad", "latitude": 25.37, "longitude": 68.35,
                 "country": "Pakistan", "admin1": "Sindh"},
                {"name": "Hyderabad", "latitude": 17.38405, "longitude": 78.45636,
                 "country": "India", "admin1": "Telangana"}]} if params["name"] != "Nowhere" \
                else {}
        if url == weather.AIR_URL:
            return {"hourly": {"time": t, "us_aqi": [self.aqi] * 48, "pm2_5": [20.0] * 48},
                    "current": {"us_aqi": self.aqi, "pm2_5": 20.0}}
        feels = [self.feels - (4 if t_[11:13] in ("06", "07") else 0) for t_ in t]
        return {"hourly": {"time": t, "temperature_2m": [30.0] * 48, "apparent_temperature": feels,
                           "relative_humidity_2m": [70] * 48, "dew_point_2m": [self.dew] * 48,
                           "precipitation_probability": [10] * 48, "wind_speed_10m": [5] * 48,
                           "uv_index": [3] * 48, "weather_code": [1] * 48},
                "current": {"temperature_2m": 30.0, "apparent_temperature": self.feels,
                            "relative_humidity_2m": 70, "dew_point_2m": self.dew,
                            "weather_code": 1},
                "daily": {"time": [t[0][:10], t[24][:10]],
                          "temperature_2m_max": [33.0, 33.0], "temperature_2m_min": [24.0, 24.0],
                          "apparent_temperature_max": [self.feels, self.feels]}}


@pytest.fixture
def meteo(monkeypatch, athlete):
    fake = FakeMeteo(athlete)
    monkeypatch.setattr(weather, "_get_json", fake)
    return fake


def with_gps(athlete, lat=17.384567, lon=78.456789, days_ago=1):
    a = make_activity(athlete, athlete.local_today - dt.timedelta(days=days_ago))
    ActivityRecord.objects.create(activity=a, offset_s=0, latitude=lat, longitude=lon)
    return a


def test_no_location_is_not_an_error(api, meteo):
    body = api.get("/api/weather/today/").json()
    assert body["available"] is False and body["reason"] == "no_location"
    assert KEYS <= set(body) and meteo.calls == []


def test_location_auto_from_latest_run_gps_rounded(api, athlete, meteo):
    with_gps(athlete, 12.0, 77.0, days_ago=5)
    with_gps(athlete)
    body = api.get("/api/weather/today/").json()
    athlete.refresh_from_db()
    assert (athlete.location_lat, athlete.location_lon) == (17.38, 78.46)
    assert athlete.location_source == "runs" and body["source"] == "runs"
    assert body["available"] and KEYS <= set(body)
    assert set(body["now"]) == {"temp", "feels_like", "humidity", "dew_point", "aqi", "pm25",
                                "condition"}
    assert body["now"]["aqi"] == 60 and body["now"]["condition"] == "Partly cloudy"
    assert 1 <= len(body["hourly"]) <= 24
    assert set(body["hydration"]) == {"before_ml", "during_ml_per_h", "after_note", "electrolytes",
                                    "sweat_l_h", "measured"}
    assert body["daily_water_bonus_ml"] == 500 and body["food"]
    params = meteo.calls[0][1]
    assert params["latitude"] == 17.38 and params["longitude"] == 78.46   # never finer


def test_city_overrides_runs(api, athlete, meteo):
    with_gps(athlete)
    r = api.patch("/api/athlete/", {"location_city": "Hyderabad, India"}, format="json")
    assert r.status_code == 200, r.json()
    body = r.json()
    assert (body["location_lat"], body["location_lon"]) == (17.38, 78.46)
    assert body["location_source"] == "city" and "India" in body["location_name"]
    assert api.get("/api/weather/today/").json()["source"] == "city"
    body = api.patch("/api/athlete/", {"location_city": ""}, format="json").json()
    assert body["location_source"] == "runs" and body["location_city"] == ""


def test_city_errors(api, athlete, meteo):
    r = api.patch("/api/athlete/", {"location_city": "Nowhere"}, format="json")
    assert r.status_code == 400 and "location_city" in r.json()
    meteo.down = True
    r = api.patch("/api/athlete/", {"location_city": "Hyderabad"}, format="json")
    assert r.status_code == 400 and "try again" in r.json()["location_city"][0]


def test_cached_per_location_per_hour(api, athlete, meteo):
    with_gps(athlete)
    api.get("/api/weather/today/")
    api.get("/api/weather/today/")
    assert len(meteo.calls) == 2                       # forecast + air quality, once each


def test_outage_degrades(api, athlete, meteo):
    with_gps(athlete)
    meteo.down = True
    r = api.get("/api/weather/today/")
    assert r.status_code == 200 and r.json()["available"] is False
    assert r.json()["reason"] == "unavailable"
    assert api.get("/api/today/").status_code == 200
    assert api.get("/api/diet/day/").json()["targets"]["water_bonus_ml"] == 0


def test_checkin_heat_and_air_signals(api, athlete, meteo):
    with_gps(athlete)
    make_workout(athlete)
    meteo.aqi = 220
    body = api.get("/api/today/").json()
    signals = {r["signal"]: r for r in body["reasons"]}
    assert signals["heat"]["status"] == "watch" and "feels like" in signals["heat"]["label"]
    assert signals["air"]["status"] == "bad" and signals["air"]["label"] == "Air quality AQI 220"
    assert body["verdict"] == "easy"                    # 1 bad -> easier, never harder
    assert "heat" not in body["signals_missing"] and "air" not in body["signals_missing"]


def test_cool_clean_day_adds_no_signal(api, athlete, monkeypatch):
    fake = FakeMeteo(athlete, feels=18, dew=10, aqi=40)
    monkeypatch.setattr(weather, "_get_json", fake)
    with_gps(athlete)
    make_workout(athlete)
    body = api.get("/api/today/").json()
    assert not {"heat", "air"} & {r["signal"] for r in body["reasons"]}
    assert body["verdict"] == "go"


def test_diet_water_bonus_and_workout_block(api, athlete, meteo):
    with_gps(athlete)
    workout = make_workout(athlete)
    plain = Athlete.objects.get(pk=athlete.pk)
    body = api.get("/api/diet/day/").json()
    assert body["targets"]["water_bonus_ml"] == 500 and body["weather_tips"]
    assert "+500 ml" in body["targets"]["rationale"]
    assert body["fueling"][0]["weather_note"].startswith("Feels like")
    other_day = (plain.local_today + dt.timedelta(days=1)).isoformat()
    assert api.get("/api/diet/day/", {"date": other_day}).json()["targets"]["water_bonus_ml"] == 0
    block = api.get(f"/api/workouts/{workout.pk}/").json()["weather"]
    assert block["available"] and block["hydration"]["before_ml"] == 600
    assert "electrolytes" in block["fueling_note"]
