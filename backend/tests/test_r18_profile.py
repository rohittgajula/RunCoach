"""R18 §B: memory facts are the live source of profile parameters; one effective-value
helper; the workout distance estimate. AI is always mocked."""

import datetime as dt

import pytest

from analysis import fact_params
from apps.athletes import profile_params as pp
from apps.athletes.effective import sleep_need
from apps.coaching.models import FactParameter, MemoryFact
from tests.r10_helpers import night


def days_ago(athlete, n):
    return athlete.local_today - dt.timedelta(days=n)


@pytest.fixture
def short_nights(athlete):
    """Six nights of 6.5 h; Garmin says 8 h is needed."""
    for n in range(0, 6):
        night(athlete, days_ago(athlete, n), hours=6.5, need_h=8.0)
    return athlete


def debt_s(api):
    return api.get("/api/health/sleep/", {"range": "7d"}).json()["debt"]["debt_s"]


def add(api, text):
    r = api.post("/api/memory/", {"text": text}, format="json")
    assert r.status_code == 201, r.json()
    return r.json()


# --- the parser (pure) ----------------------------------------------------------------------------

@pytest.mark.parametrize("text,key,value,review", [
    ("I need 7 hours of sleep", "sleep_need_minutes", 420, False),
    ("7h30 sleep is ideal for me", "sleep_need_minutes", 450, False),
    ("I slept 5 hours last night", "sleep_need_minutes", 300, True),
    ("I usually run at 6:30 am", "usual_run_time", "06:30", False),
    ("I run at 6", "usual_run_time", "06:00", True),
    ("Evening runs around 7", "usual_run_time", "19:00", False),
    ("My loop is 1.2 km", "loop_distance_km", 1.2, False),
    ("I run an 800 m loop in the park", "loop_distance_km", 0.8, False),
    ("I can run 4 times a week", "runs_per_week", 4, False),
    ("Long runs on Sunday", "long_run_day", 6, False),
])
def test_parser(text, key, value, review):
    [param] = [p for p in fact_params.parse(text) if p.key == key]
    assert param.value == value and param.needs_review is review


def test_parser_days_and_nothing():
    [p] = fact_params.parse("I can only run on Tuesday, Thursday and Saturday")
    assert p.key == "available_days" and [k for k, v in p.value.items() if v] == ["1", "3", "5"]
    assert fact_params.parse("I like trail running") == []
    assert not fact_params.looks_parameter_like("I like trail running")
    assert fact_params.looks_parameter_like("My usual jog starts around half six")


# --- memory edits move the effective value at once -------------------------------------------------

def test_sleep_need_follows_memory_edits_7_8_6(api, short_nights):
    garmin_debt = debt_s(api)                     # 6 × 1.5 h vs Garmin's 8 h
    fact = add(api, "I need 7 hours of sleep")
    [param] = fact["parameters"]
    assert param["key"] == "sleep_need_minutes" and param["value_display"] == "7 h"
    assert param["applied"] is True and param["source"] == "parser"
    assert sleep_need(short_nights)["source"] == "memory"
    debt_7 = debt_s(api)
    assert debt_7 < garmin_debt
    body = api.get("/api/health/sleep/", {"range": "7d"}).json()
    assert body["need"]["minutes"] == 420 and body["need"]["label"] == "7 h (from memory)"
    assert body["nights"][0]["need_s"] == 420 * 60 and body["nights"][0]["garmin_need_s"] == 8 * 3600

    api.patch(f"/api/memory/{fact['id']}/", {"text": "I need 8 hours of sleep"}, format="json")
    assert sleep_need(short_nights)["minutes"] == 480 and debt_s(api) > debt_7
    api.patch(f"/api/memory/{fact['id']}/", {"text": "I need 6 hours of sleep"}, format="json")
    assert sleep_need(short_nights)["minutes"] == 360 and debt_s(api) == 0

    # Delete → back to Garmin's.
    assert api.delete(f"/api/memory/{fact['id']}/").status_code == 204
    need = sleep_need(short_nights)
    assert need["source"] == "garmin" and need["minutes"] == 480 and debt_s(api) == garmin_debt


def test_setting_newer_than_fact_wins_until_the_fact_changes(api, athlete, short_nights,
                                                             monkeypatch):
    t0 = dt.datetime(2026, 10, 1, 8, tzinfo=dt.timezone.utc)
    now = {"t": t0}
    monkeypatch.setattr("apps.athletes.profile_params.timezone.now", lambda: now["t"])
    fact = add(api, "I need 7 hours of sleep")
    now["t"] = t0 + dt.timedelta(hours=1)
    r = api.patch("/api/athlete/", {"sleep_need_minutes": 480}, format="json")
    assert r.json()["sleep_need"]["source"] == "user"
    athlete.refresh_from_db()        # the test client reuses the fixture's user.athlete
    eff = api.get("/api/profile/effective/").json()
    sleep = next(p for p in eff["parameters"] if p["key"] == "sleep_need_minutes")
    assert sleep["source"] == "setting" and sleep["value"] == 480 and eff["data_version"]
    now["t"] = t0 + dt.timedelta(hours=2)
    api.patch(f"/api/memory/{fact['id']}/", {"text": "I need 6.5 hours of sleep"}, format="json")
    sleep = next(p for p in api.get("/api/profile/effective/").json()["parameters"]
                 if p["key"] == "sleep_need_minutes")
    assert sleep["source"] == "memory" and sleep["value"] == 390
    assert sleep["fact_id"] == fact["id"] and sleep["setting_value"] == 480


def test_ambiguous_parse_is_not_applied_until_confirmed(api, athlete, short_nights):
    fact = add(api, "I slept 5 hours last night")
    [param] = fact["parameters"]
    assert param["needs_review"] is True and param["status"] == "needs_review"
    assert param["applied"] is False and sleep_need(athlete)["source"] == "garmin"
    url = f"/api/memory/{fact['id']}/parameters/{param['id']}/"
    assert api.patch(url, {"action": "nope"}, format="json").status_code == 400
    r = api.patch(url, {"action": "confirm"}, format="json")
    assert r.status_code == 200 and r.json()["parameter"]["applied"] is True
    assert r.json()["effective"]["value"] == 300 and r.json()["data_version"]
    assert sleep_need(athlete)["minutes"] == 300
    r = api.patch(url, {"action": "reject"}, format="json")
    assert r.json()["parameter"]["status"] == "rejected"
    assert sleep_need(athlete)["source"] == "garmin"


def test_memory_parameters_are_tenant_scoped(api, other_api, athlete, other_athlete):
    fact = add(api, "I usually run at 6:30 am")
    pid = fact["parameters"][0]["id"]
    assert other_api.patch(f"/api/memory/{fact['id']}/parameters/{pid}/",
                           {"action": "reject"}, format="json").status_code == 404
    mine = {p["key"]: p for p in api.get("/api/profile/effective/").json()["parameters"]}
    theirs = {p["key"]: p for p in other_api.get("/api/profile/effective/").json()["parameters"]}
    assert mine["usual_run_time"]["value"] == "06:30" and mine["usual_run_time"]["source"] == "memory"
    assert theirs["usual_run_time"]["value"] is None


def test_existing_facts_are_parsed_lazily(api, athlete):
    MemoryFact.objects.bulk_create([MemoryFact(athlete=athlete, text="My loop is 1.5 km")])
    assert not FactParameter.objects.exists()                # bulk_create: no signal
    facts = api.get("/api/memory/").json()
    assert facts[0]["parameters"][0]["key"] == "loop_distance_km"


# --- available days: conflict check + re-flow ------------------------------------------------------

def test_available_days_from_memory_conflict_then_reflow_and_fallback(api, athlete):
    from tests.r7_helpers import make_workout

    original = dict(athlete.available_days)                 # Tue, Thu, Sat, Sun; long run Sun
    fact = add(api, "I can only run on Tuesday, Thursday and Saturday")
    [param] = fact["parameters"]
    assert param["status"] == "needs_review" and "long-run day" in param["conflict"]
    athlete.refresh_from_db()
    assert athlete.available_days == original               # not applied

    api.delete(f"/api/memory/{fact['id']}/")
    monday = athlete.local_today + dt.timedelta(days=7 - athlete.local_today.weekday())
    workout = make_workout(athlete, monday + dt.timedelta(days=3))      # a Thursday
    fact = add(api, "I can only run on Monday, Wednesday and Sunday")
    athlete.refresh_from_db()
    assert [k for k, v in athlete.available_days.items() if v] == ["0", "2", "6"]
    workout.refresh_from_db()
    assert workout.date.weekday() in (0, 2, 6)                # the normal re-flow ran
    assert athlete.profile_settings["available_days"]["value"] == original

    api.delete(f"/api/memory/{fact['id']}/")                  # falls back to the setting
    athlete.refresh_from_db()
    assert athlete.available_days == original


# --- AI fallback ---------------------------------------------------------------------------------

def test_ai_fallback_only_when_parser_finds_nothing_and_is_cached(api, athlete, monkeypatch,
                                                                 isolated_r18_cache):
    from apps.coaching import tasks
    from apps.coaching.schemas import FactParamItem, FactParams

    seen = []

    def fake_complete(*, operation, schema, user, **kw):
        seen.append(operation)
        return FactParams(parameters=[FactParamItem(key="usual_run_time", number=None,
                                                    time="06:30", days=None, confidence=0.9)]), {
            "model": "test-model", "input_tokens": 1, "output_tokens": 1, "latency_ms": 1,
            "retry_count": 0, "estimated_cost_usd": 0}

    monkeypatch.setattr("apps.coaching.services.complete", fake_complete)
    add(api, "I like trail running")                          # not parameter-like
    fact = add(api, "My usual jog starts around half six")
    assert fact["parameters"] == [] and fact["parse_pending"] is True
    queue = isolated_r18_cache.r18_ai_queue
    assert queue == [(fact["id"], "My usual jog starts around half six")]
    tasks.parse_fact_params_ai.run(*queue[0])
    [param] = api.get("/api/memory/").json()[0]["parameters"]
    assert param["source"] == "ai" and param["value"] == "06:30" and param["applied"] is True
    tasks.parse_fact_params_ai.run(*queue[0])                 # same text: cached, no 2nd call
    assert seen == ["memory_params"]


# --- explicit settings + the one helper ---------------------------------------------------------

def test_athlete_settings_fields_and_validation(api, athlete):
    body = api.patch("/api/athlete/", {"sleep_need_minutes": 420, "usual_run_time": "06:15",
                                       "loop_distance_km": 1.6, "injury_note": "Left knee"},
                     format="json").json()
    assert body["sleep_need"] == {"seconds": 25200, "minutes": 420, "source": "user",
                                  "garmin_minutes": None, "label": "7 h (set by you)",
                                  "fact_id": None}
    assert body["usual_run_time"] == "06:15" and body["effective"]["loop_distance_km"] == 1.6
    assert api.patch("/api/athlete/", {"sleep_need_minutes": 100},
                     format="json").status_code == 400
    athlete.refresh_from_db()        # the test client reuses the fixture's user.athlete
    assert api.get("/api/health/injury/").json()["athlete_note"] == "Left knee"
    wake = api.get("/api/health/wake-plan/").json()
    assert wake["need_s"] == 420 * 60 and wake["need_source"] == "user"
    assert wake["run"]["run_time"] == "06:15" and wake["run"]["run_time_source"] == "usual"


def test_one_helper_drives_forecast_and_briefing(api, athlete, short_nights):
    from apps.health import briefing

    api.patch("/api/athlete/", {"sleep_need_minutes": 690}, format="json")    # 11.5 h
    athlete.refresh_from_db()
    notes = [n["text"] for n in briefing.compute(athlete).get("notes", []) if n["kind"] == "sleep"]
    assert any("11.5 h" in t for t in notes)
    fc = api.get("/api/health/readiness-forecast/").json()
    assert "30.0 h short of your need" in str(fc)          # 6 nights × (11.5 − 6.5) h


def test_workout_distance_estimate_uses_loop(api, athlete):
    from tests.r7_helpers import make_workout

    w = make_workout(athlete)                     # 12 min easy running + 11 min walking
    est = api.get(f"/api/workouts/{w.pk}/").json()["distance_estimate"]
    assert est["km"] > 0 and est["loops"] is None
    add(api, "My loop is 0.5 km")
    est = api.get(f"/api/workouts/{w.pk}/").json()["distance_estimate"]
    assert est["loop_km"] == 0.5 and est["loops"] == round(est["km"] / 0.5, 1)
