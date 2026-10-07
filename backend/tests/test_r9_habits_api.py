"""R9 §B/§C through the API: the private habit (enable/disable, bulk delete, never to
the AI), the habit health report and tenant isolation."""

import datetime as dt
import json

import pytest

from apps.coaching import services as coaching
from apps.habits.models import HabitLog
from tests.r7_helpers import make_workout, wellness

REPORT_HABIT_KEYS = {"habit", "status", "headline", "amount", "findings"}


def log(athlete, kind="smoke", qty=1, days_ago=0, hour=9):
    local = athlete.local_now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return HabitLog.objects.create(athlete=athlete, kind=kind, quantity=qty,
                                   at=local - dt.timedelta(days=days_ago))


def enable(athlete, on_today=False, goal="none"):
    athlete.private_habit_enabled = True
    athlete.private_on_today = on_today
    athlete.private_goal = goal
    athlete.save()


def fake_ai(monkeypatch, seen):
    def fake_complete(*, operation, schema, user, **kw):
        seen.append(user)
        fields = {"markdown": "Fine."}
        if "went_well" in schema.model_fields:
            fields.update(went_well=["a"], improve=["b"], check=[])
        return schema(**fields), {"model": "m", "input_tokens": 1, "output_tokens": 1,
                                  "latency_ms": 1, "retry_count": 0, "estimated_cost_usd": 0}
    monkeypatch.setattr(coaching, "complete", fake_complete)


# --- athlete fields ---------------------------------------------------------------

def test_athlete_fields_default_and_patch(api):
    body = api.get("/api/athlete/").json()
    assert body["private_habit_enabled"] is False and body["private_on_today"] is False
    assert body["private_goal"] == "none"
    r = api.patch("/api/athlete/", {"private_habit_enabled": True, "private_on_today": True,
                                    "private_goal": "reduce"}, format="json")
    assert r.status_code == 200, r.json()
    assert r.json()["private_goal"] == "reduce" and r.json()["private_on_today"] is True
    assert api.patch("/api/athlete/", {"private_goal": "quit"},
                     format="json").status_code == 400
    assert api.patch("/api/athlete/", {"daily_limits": {"private": 2}},
                     format="json").status_code == 200


# --- disabled ---------------------------------------------------------------------

def test_disabled_omits_private_and_rejects_post(api, athlete):
    log(athlete, "private", 2)                     # e.g. logged while it was enabled
    log(athlete, "smoke", 1)
    today = api.get("/api/habits/today/").json()
    assert "private" not in today["counts"] and "private" not in today["last_at"]
    summary = api.get("/api/habits/summary/").json()
    assert "private" not in summary and "private" not in summary["goals"]
    assert all(r["habit"] != "private" for r in summary["impact"])
    assert all(c["habit"] != "private" for c in summary["report"]["habits"])
    r = api.post("/api/habits/logs/", {"kind": "private"}, format="json")
    assert r.status_code == 400 and "kind" in r.json()
    assert all(x["kind"] != "private" for x in api.get("/api/habits/logs/").json())
    # Still listable by kind so the user can see what "Delete private logs" removes.
    assert len(api.get("/api/habits/logs/", {"kind": "private"}).json()) == 1


def test_disabled_private_log_cannot_be_edited_but_can_be_deleted(api, athlete):
    entry = log(athlete, "private", 1)
    assert api.patch(f"/api/habits/logs/{entry.pk}/", {"quantity": 3},
                     format="json").status_code == 400
    assert api.delete(f"/api/habits/logs/{entry.pk}/").status_code == 204


# --- enabled ----------------------------------------------------------------------

def test_enabled_today_and_summary_include_private(api, athlete):
    enable(athlete, goal="reduce")
    assert api.post("/api/habits/logs/", {"kind": "private", "quantity": 1},
                    format="json").status_code == 201
    today = api.get("/api/habits/today/").json()
    assert today["counts"] == {"smoke": 0, "alcohol": 0, "sugar": 0, "private": 1}
    assert today["last_at"]["private"]
    summary = api.get("/api/habits/summary/").json()
    assert set(summary["private"]) == {"series", "total", "per_day_avg"}
    assert summary["private"]["total"] == 1 and summary["goals"]["private"] == "reduce"
    cards = {c["habit"]: c for c in summary["report"]["habits"]}
    assert "private" in cards and set(cards["private"]) == REPORT_HABIT_KEYS
    for item in [cards["private"]["headline"], *[f["text"] for f in
                                                 cards["private"]["findings"]]]:
        assert "private" not in item.replace("Private", "")


def test_bulk_delete_private_only_own(api, other_api, athlete, other_athlete):
    enable(athlete)
    enable(other_athlete)
    for _ in range(3):
        log(athlete, "private")
    keep = log(athlete, "smoke")
    theirs = log(other_athlete, "private")
    assert api.delete("/api/habits/logs/").status_code == 400          # kind required
    assert api.delete("/api/habits/logs/?kind=nope").status_code == 400
    r = api.delete("/api/habits/logs/?kind=private")
    assert r.status_code == 200 and r.json() == {"deleted": 3}
    assert not HabitLog.objects.filter(athlete=athlete, kind="private").exists()
    assert HabitLog.objects.filter(pk=keep.pk).exists()
    assert HabitLog.objects.filter(pk=theirs.pk).exists()
    # Works with the habit switched off too.
    log(athlete, "private")
    athlete.private_habit_enabled = False
    athlete.save()
    assert api.delete("/api/habits/logs/?kind=private").json() == {"deleted": 1}


def test_private_tenant_isolation(api, other_api, athlete, other_athlete):
    enable(athlete)
    enable(other_athlete)
    mine = log(athlete, "private", 4)
    assert other_api.get("/api/habits/today/").json()["counts"]["private"] == 0
    assert other_api.get("/api/habits/summary/").json()["private"]["total"] == 0
    assert other_api.get("/api/habits/logs/", {"kind": "private"}).json() == []
    assert other_api.delete(f"/api/habits/logs/{mine.pk}/").status_code == 404
    assert other_api.delete("/api/habits/logs/?kind=private").json() == {"deleted": 0}
    assert HabitLog.objects.filter(pk=mine.pk).exists()


# --- never to the AI --------------------------------------------------------------

def test_chat_tool_cannot_log_private(athlete):
    from apps.coaching.tools import TOOLS, ToolRunner

    enable(athlete)
    tool = next(t for t in TOOLS if t["function"]["name"] == "log_habit")
    assert "private" not in json.dumps(tool).lower()
    out = ToolRunner(athlete)("log_habit", {"kind": "private", "quantity": 1})
    assert "error" in out and "private" not in out["error"]
    assert not HabitLog.objects.filter(kind="private").exists()
    ok = ToolRunner(athlete)("log_habit", {"kind": "smoke", "quantity": 1})
    assert "private" not in ok["today"]


def test_chat_system_prompt_never_has_private(athlete):
    from apps.coaching.chat import system_prompt

    enable(athlete, on_today=True, goal="reduce")
    log(athlete, "private", 3)
    log(athlete, "private", 2, days_ago=1)
    assert "private" not in system_prompt(athlete).lower()       # no habits block at all
    log(athlete, "alcohol", 2, days_ago=1)
    prompt = system_prompt(athlete)
    assert '"habits"' in prompt and "private" not in prompt.lower()


def test_ai_summary_input_has_no_private(api, athlete, monkeypatch):
    enable(athlete, goal="reduce")
    today = athlete.local_today
    for i in range(1, 40):
        if i % 2:
            log(athlete, "private", 1, days_ago=i, hour=22)
        log(athlete, "smoke", 3 if i > 28 else 1, days_ago=i)
        wellness(athlete, today - dt.timedelta(days=i - 1), hrv_overnight_avg=40 + i % 3,
                 resting_hr=58, sleep_score=75)
    body = api.get("/api/habits/summary/").json()
    assert any(c["habit"] == "private" for c in body["report"]["habits"])
    seen = []
    fake_ai(monkeypatch, seen)
    assert api.post("/api/habits/summary/?refresh=1").status_code == 200
    assert seen and "private" not in seen[0].lower()
    assert '"report"' in seen[0] and '"smoke"' in seen[0]


def test_ai_payload_overall_recomputed_without_private(athlete):
    from apps.habits.ai import ai_payload
    from apps.habits.services import summary_payload

    enable(athlete)
    for i in range(1, 57):     # private: down (improving); smoke: up (worsening)
        log(athlete, "private", 1 if i <= 28 else 3, days_ago=i)
    log(athlete, "smoke", 1, days_ago=50)
    for i in range(0, 28):
        log(athlete, "smoke", 2, days_ago=i)
    payload = summary_payload(athlete, "4w")
    assert payload["report"]["overall"]["status"] == "steady"     # 1 up, 1 down
    clean = ai_payload(payload)
    assert [c["habit"] for c in clean["report"]["habits"]] == ["smoke"]
    assert clean["report"]["overall"]["status"] == "worsening"
    assert "of 2" not in json.dumps(clean) and "private" not in json.dumps(clean).lower()


def test_checkin_ignores_private(api, athlete):
    enable(athlete)
    make_workout(athlete)
    log(athlete, "private", 9, days_ago=1, hour=23)
    body = api.get("/api/today/").json()
    assert "private" not in json.dumps(body).lower()
    assert body["verdict"] == "go"


# --- the report through the API ---------------------------------------------------

def test_summary_report_shape(api, athlete):
    athlete.smoke_goal = "reduce"
    athlete.save()
    today = athlete.local_today
    for i in range(0, 56):
        log(athlete, "smoke", 6 if i >= 28 else 3, days_ago=i)
        wellness(athlete, today - dt.timedelta(days=i), hrv_overnight_avg=50 if i < 28 else 45,
                 resting_hr=56 if i < 28 else 58, sleep_score=80)
    body = api.get("/api/habits/summary/", {"range": "4w"}).json()
    report = body["report"]
    assert set(report) == {"overall", "garmin", "habits"}
    assert set(report["overall"]) == {"status", "headline"}
    assert [g["metric"] for g in report["garmin"]] == [
        "hrv", "rhr", "sleep_score", "stress", "body_battery_high", "respiration",
        "easy_pace_hr", "efficiency"]
    smoke = next(c for c in report["habits"] if c["habit"] == "smoke")
    assert smoke["status"] == "improving" and smoke["headline"] == \
        "Down 50% vs the previous 4 weeks"
    assert smoke["amount"]["now_per_day"] == 3 and smoke["amount"]["before_per_day"] == 6
    assert report["overall"]["status"] == "improving"
    # Habits never logged and without a goal are left out.
    assert {c["habit"] for c in report["habits"]} == {"smoke"}


@pytest.mark.parametrize("range_key", ["4w", "12w", "6m"])
def test_report_every_range(api, athlete, range_key):
    log(athlete, "alcohol", 2, days_ago=3, hour=22)
    body = api.get("/api/habits/summary/", {"range": range_key}).json()
    card = body["report"]["habits"][0]
    assert card["habit"] == "alcohol" and card["status"] == "not_enough_data"
    assert card["findings"][-1]["kind"] == "keep_logging"


def test_report_tenant_isolation(other_api, athlete):
    for i in range(0, 56):
        log(athlete, "smoke", 5, days_ago=i)
        wellness(athlete, athlete.local_today - dt.timedelta(days=i), hrv_overnight_avg=50)
    report = other_api.get("/api/habits/summary/").json()["report"]
    assert report["habits"] == []
    assert all(g["now"] is None and g["before"] is None for g in report["garmin"])
    assert report["overall"]["status"] == "not_enough_data"
