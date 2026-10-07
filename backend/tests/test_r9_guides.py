"""R9 §E: GET /guides/ — pure rules, then the API (weather from the cache only, no
location / outage, tenant isolation)."""

import datetime as dt

from analysis import guides as g
from apps.activities.models import ActivityRecord
from apps.habits.models import HabitLog
from apps.ingest import weather
from tests.r6_helpers import make_activity
from tests.r7_helpers import make_workout, run_walk_steps


def keys(out):
    return [p["key"] for p in out]


# --- pure ---------------------------------------------------------------------

def test_only_warmup_without_data():
    out = g.for_you(g.GuideInputs())
    assert out == [{"key": "warmup", "reason": out[0]["reason"], "priority": 5}]


def test_cadence_rule():
    out = g.for_you(g.GuideInputs(cadences=[150, 154]))
    assert out[0] == {"key": "form", "reason": "Your cadence averages 152 spm", "priority": 2}
    assert "form" not in keys(g.for_you(g.GuideInputs(cadences=[160, 162])))


def test_drift_rule_needs_two_runs():
    assert keys(g.for_you(g.GuideInputs(hr_drifts=[6.0, 4.0]))) == ["warmup"]
    out = g.for_you(g.GuideInputs(hr_drifts=[6.0, 7.5, 2.0]))
    assert keys(out)[:2] == ["breathing", "fueling"]
    assert out[0]["priority"] == 1 and "2 recent runs" in out[0]["reason"]


def test_smoking_rule():
    assert "breathing" in keys(g.for_you(g.GuideInputs(smoke_goal="quit")))
    assert "breathing" in keys(g.for_you(g.GuideInputs(smoke_goal="reduce")))
    assert "breathing" in keys(g.for_you(g.GuideInputs(smoked_recently=True)))
    assert "breathing" not in keys(g.for_you(g.GuideInputs(smoke_goal="none")))


def test_run_fraction_rule_and_merge():
    out = g.for_you(g.GuideInputs(run_fractions=[0.6, 0.7], smoke_goal="quit"))
    by = {p["key"]: p for p in out}
    assert by["strength"]["reason"] == "You run 65% of the time on run/walk days"
    # breathing from both rules: merged reasons, best priority, listed once
    assert keys(out).count("breathing") == 1
    assert by["breathing"]["priority"] == 2
    assert " · " in by["breathing"]["reason"] and "smoking" in by["breathing"]["reason"]
    assert "strength" not in keys(g.for_you(g.GuideInputs(run_fractions=[0.9])))


def test_fueling_heat_and_long_run():
    assert "fueling" in keys(g.for_you(g.GuideInputs(feels_like_max=28.0)))
    assert "fueling" not in keys(g.for_you(g.GuideInputs(feels_like_max=27.9)))
    out = g.for_you(g.GuideInputs(feels_like_max=33.0, longest_upcoming_run_min=75))
    fueling = next(p for p in out if p["key"] == "fueling")
    assert fueling["reason"] == ("Hot forecast — feels like 33°C · A 75-minute run is coming "
                                 "up this week")
    assert "fueling" not in keys(g.for_you(g.GuideInputs(longest_upcoming_run_min=59)))


def test_sorted_by_priority_then_guide_order():
    out = g.for_you(g.GuideInputs(cadences=[150], hr_drifts=[6, 6], run_fractions=[0.5],
                                  smoke_goal="quit", feels_like_max=30))
    priorities = [p["priority"] for p in out]
    assert priorities == sorted(priorities)
    assert keys(out) == ["breathing", "fueling", "form", "strength", "warmup"]


def test_context_and_metronome():
    ctx = g.context(g.GuideInputs(cadences=[150, 160], run_fractions=[0.8], runs=2))
    assert ctx["cadence_avg"] == 155.0 and ctx["metronome_bpm"] == 163
    assert ctx["run_fraction_pct"] == 80.0 and ctx["runs"] == 2
    assert g.metronome_bpm(None) == g.DEFAULT_METRONOME_BPM
    assert g.metronome_bpm(100) == g.METRONOME_MIN


# --- API ----------------------------------------------------------------------

def test_guides_endpoint_without_location_or_weather(api, athlete):
    body = api.get("/api/guides/").json()
    assert set(body) == {"for_you", "context"}
    assert keys(body["for_you"]) == ["warmup"]
    assert body["context"]["weather_available"] is False
    assert body["context"]["hydration"] is None and body["context"]["feels_like_max"] is None


def test_guides_from_runs_and_habits(api, athlete):
    today = athlete.local_today
    for d in (2, 5, 9):
        make_activity(athlete, today - dt.timedelta(days=d), cadence=150, run_s=600,
                      walk_s=600)
    make_activity(athlete, today - dt.timedelta(days=40), cadence=150)   # too old
    HabitLog.objects.create(athlete=athlete, kind="smoke", quantity=1, at=athlete.local_now)
    body = api.get("/api/guides/").json()
    by = {p["key"]: p for p in body["for_you"]}
    assert {"form", "breathing", "strength", "warmup"} <= set(by)
    assert by["form"]["reason"] == "Your cadence averages 150 spm"
    assert body["context"]["runs"] == 3 and body["context"]["smoking"] is True


def test_long_planned_run_this_week(api, athlete):
    steps = run_walk_steps(blocks=12)                     # 12 × 6 min + 5 = 77 min
    today = athlete.local_today
    make_workout(athlete, today + dt.timedelta(days=min(1, 6 - today.weekday())), steps=steps)
    body = api.get("/api/guides/").json()
    assert "fueling" in keys(body["for_you"])
    assert body["context"]["longest_upcoming_run_min"] == 77


def gps_run(athlete):
    a = make_activity(athlete, athlete.local_today - dt.timedelta(days=1))
    ActivityRecord.objects.create(activity=a, offset_s=0, latitude=17.384, longitude=78.456)


def forecast_body(athlete, feels):
    day = athlete.local_today
    t = [f"{day + dt.timedelta(days=h // 24)}T{h % 24:02d}:00" for h in range(48)]
    return {"hourly": {"time": t, "temperature_2m": [30.0] * 48,
                       "apparent_temperature": [feels] * 48,
                       "relative_humidity_2m": [60] * 48, "dew_point_2m": [20.0] * 48,
                       "precipitation_probability": [0] * 48, "wind_speed_10m": [5] * 48,
                       "uv_index": [3] * 48, "weather_code": [1] * 48},
            "current": {"temperature_2m": 30.0, "apparent_temperature": feels,
                        "relative_humidity_2m": 60, "dew_point_2m": 20.0, "weather_code": 1},
            "daily": {"time": [t[0][:10], t[24][:10]], "temperature_2m_max": [32.0, 32.0],
                      "temperature_2m_min": [24.0, 24.0],
                      "apparent_temperature_max": [feels, feels]}}


def test_hot_forecast_from_cache_only(api, athlete, monkeypatch):
    calls = []

    def network(url, params):
        calls.append(url)
        raise weather.WeatherUnavailable("must not be called")
    monkeypatch.setattr(weather, "_get_json", network)
    gps_run(athlete)
    # Nothing cached yet: no heat reason and no network call.
    body = api.get("/api/guides/").json()
    assert body["context"]["weather_available"] is False and calls == []
    athlete.refresh_from_db()
    weather.cache.set(weather._key("fc", athlete.location_lat, athlete.location_lon,
                                   athlete.timezone), forecast_body(athlete, 31.0), 600)
    body = api.get("/api/guides/").json()
    assert calls == []
    assert body["context"]["weather_available"] is True
    assert body["context"]["feels_like_max"] == 31.0 and body["context"]["hydration"]
    fueling = next(p for p in body["for_you"] if p["key"] == "fueling")
    assert "feels like 31°C" in fueling["reason"]


def test_broken_cache_entry_does_not_fail(api, athlete):
    gps_run(athlete)
    api.get("/api/guides/")
    athlete.refresh_from_db()
    weather.cache.set(weather._key("fc", athlete.location_lat, athlete.location_lon,
                                   athlete.timezone), {"hourly": "garbage"}, 600)
    r = api.get("/api/guides/")
    assert r.status_code == 200 and "warmup" in keys(r.json()["for_you"])


def test_guides_tenant_isolation(other_api, athlete):
    today = athlete.local_today
    for d in (1, 2, 3):
        make_activity(athlete, today - dt.timedelta(days=d), cadence=140, run_s=300,
                      walk_s=900)
    HabitLog.objects.create(athlete=athlete, kind="smoke", quantity=1, at=athlete.local_now)
    body = other_api.get("/api/guides/").json()
    assert keys(body["for_you"]) == ["warmup"]
    assert body["context"]["runs"] == 0 and body["context"]["smoking"] is False


def test_guides_requires_auth(client, db):
    assert client.get("/api/guides/").status_code == 401
