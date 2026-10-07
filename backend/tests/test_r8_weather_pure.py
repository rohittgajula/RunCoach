"""R8 §D, pure: heat bands, hydration, water bonus, AQI levels and the best window."""

import datetime as dt

import pytest

from analysis import weather_advice as w


@pytest.mark.parametrize("feels,dew,band", [(20, 10, "cool"), (25, 12, "warm"), (22, 19, "warm"),
                                            (33, 15, "hot"), (28, 24, "hot"), (39, 20, "very_hot"),
                                            (None, None, "cool")])
def test_heat_bands(feels, dew, band):
    assert w.heat_band(feels, dew) == band


@pytest.mark.parametrize("band,during", [("cool", 350), ("warm", 600), ("hot", 800),
                                         ("very_hot", 800)])
def test_hydration_during_scales_with_heat(band, during):
    out = w.hydration(band, 60)
    assert out["during_ml_per_h"] == during
    assert 300 <= during <= 900 and 400 <= out["before_ml"] <= 600
    assert set(out) == {"before_ml", "during_ml_per_h", "after_note", "electrolytes"}


def test_hydration_short_runs_and_electrolytes():
    assert w.hydration("warm", 30)["during_ml_per_h"] == 0          # < 45 min
    assert w.hydration("warm", 30)["electrolytes"] is False
    assert w.hydration("cool", 75)["electrolytes"] is True          # > 60 min
    assert w.hydration("hot", 30)["electrolytes"] is True           # hot
    assert "1.5×" in w.hydration("hot", 60)["after_note"]
    assert "1800 ml" in w.hydration("hot", 60)["after_note"]        # 1.2 L × 1.5


@pytest.mark.parametrize("feels,bonus", [(None, 0), (27.9, 0), (28, 250), (31.9, 250),
                                         (32, 500), (40, 500)])
def test_water_bonus(feels, bonus):
    assert w.daily_water_bonus_ml(feels) == bonus


@pytest.mark.parametrize("aqi,level", [(None, None), (100, None), (101, "caution"),
                                       (151, "shorten"), (201, "bad")])
def test_aqi_levels(aqi, level):
    assert w.air_level(aqi) == level


def test_advisories():
    hot = w.advisories({"aqi": 160}, [{"weather_code": 95}], "hot")
    levels = [(a["level"], a["text"][:12]) for a in hot]
    assert any("slower" in a["text"] and "heart rate" in a["text"] for a in hot)
    assert any("AQI 160" in a["text"] for a in hot) and any("Thunder" in t for _, t in levels)
    rain = w.advisories({"aqi": 20}, [{"precip_prob": 80}], "cool")
    assert rain == [{"level": "caution", "text": rain[0]["text"]}] and "Rain" in rain[0]["text"]
    assert w.advisories({}, [], "cool") == []


def hours(day, temps, aqis=None):
    return [{"time": f"{day}T{h:02d}:00", "feels_like": t, "temp": t,
             "aqi": (aqis or {}).get(h)} for h, t in temps.items()]


def test_best_window_is_coolest_cleanest_in_run_hours():
    day = "2026-10-07"
    temps = {h: 30 for h in range(24)}
    temps.update({3: 20, 6: 26, 7: 27, 18: 25, 13: 22})            # 03:00/13:00 not allowed
    now = dt.datetime(2026, 10, 7, 5, 10)
    window = w.best_window(hours(day, temps, {18: 180}), now)
    assert window["start"] == "2026-10-07T06:00" and window["end"] == "2026-10-07T07:00"
    assert "AQI" not in window["reason"] and "26" in window["reason"]
    window = w.best_window(hours(day, temps), now)
    assert window["start"] == "2026-10-07T18:00"
    late = dt.datetime(2026, 10, 7, 21, 0)                         # nothing left today
    assert w.best_window(hours(day, temps), late) is None


def test_advise_and_checkin_signals():
    day = "2026-10-07"
    temps = {h: 34 for h in range(24)}
    out = w.advise({"feels_like": 34, "dew_point": 25, "aqi": 120}, hours(day, temps),
                   dt.datetime(2026, 10, 7, 5), run_minutes=50)
    assert out["heat"] == "hot" and out["daily_water_bonus_ml"] == 500
    assert out["hydration"]["during_ml_per_h"] == 800 and out["food"]
    assert out["checkin"]["hot"] is True and out["checkin"]["aqi"] == 120
    cool = w.advise({"feels_like": 15, "aqi": 20}, hours(day, {h: 15 for h in range(24)}),
                    dt.datetime(2026, 10, 7, 5))
    assert cool["food"] == [] and cool["daily_water_bonus_ml"] == 0
    assert cool["checkin"]["hot"] is False
