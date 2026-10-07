"""R8 §B through the API: logs CRUD, tenant isolation, today, summary, AI summary,
chat tool, check-in alcohol signal and the Insights focus items."""

import datetime as dt

import pytest
from django.utils import timezone

from apps.coaching import services as coaching
from apps.coaching.client import AIUnavailable
from apps.habits.models import HabitLog
from tests.r7_helpers import make_workout, wellness

SUMMARY_KEYS = {"range", "today", "smoke", "alcohol", "sugar", "impact", "weekly", "goals",
                "summary", "report",     # R9 §C added `report`
                "start", "end", "period"}    # R12 §A


def log(athlete, kind="smoke", qty=1, days_ago=0, hour=9):
    local = athlete.local_now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return HabitLog.objects.create(athlete=athlete, kind=kind, quantity=qty,
                                   at=local - dt.timedelta(days=days_ago))


def test_create_list_patch_delete(api, athlete):
    r = api.post("/api/habits/logs/", {"kind": "alcohol", "quantity": 2, "note": "beer"},
                 format="json")
    assert r.status_code == 201, r.json()
    body = r.json()
    assert set(body) == {"id", "kind", "quantity", "at", "local_date", "note", "created_at",
                         "subtype"}   # R13 §9 (null except for caffeine)
    assert body["subtype"] is None
    assert body["local_date"] == athlete.local_today.isoformat()
    assert api.post("/api/habits/logs/", {"kind": "smoke"}, format="json").json()["quantity"] == 1
    listed = api.get("/api/habits/logs/", {"kind": "alcohol"}).json()
    assert [x["id"] for x in listed] == [body["id"]]
    r = api.patch(f"/api/habits/logs/{body['id']}/", {"quantity": 3}, format="json")
    assert r.status_code == 200 and r.json()["quantity"] == 3 and r.json()["kind"] == "alcohol"
    assert api.delete(f"/api/habits/logs/{body['id']}/").status_code == 204
    assert not HabitLog.objects.filter(pk=body["id"]).exists()


@pytest.mark.parametrize("payload", [{"kind": "coffee"}, {"kind": "smoke", "quantity": 0},
                                     {"kind": "smoke", "quantity": 500},
                                     {"kind": "smoke", "at": "2099-01-01T00:00:00Z"}])
def test_validation(api, payload):
    assert api.post("/api/habits/logs/", payload, format="json").status_code == 400


def test_range_filters(api, athlete):
    log(athlete, days_ago=10)
    log(athlete, days_ago=1)
    start = (athlete.local_today - dt.timedelta(days=3)).isoformat()
    assert len(api.get("/api/habits/logs/", {"start": start}).json()) == 1
    assert api.get("/api/habits/logs/", {"start": "bad"}).status_code == 400


def test_tenant_isolation(api, other_api, athlete, other_athlete):
    mine = log(athlete)
    assert other_api.get("/api/habits/logs/").json() == []
    assert other_api.patch(f"/api/habits/logs/{mine.pk}/", {"quantity": 9},
                           format="json").status_code == 404
    assert other_api.delete(f"/api/habits/logs/{mine.pk}/").status_code == 404
    assert other_api.get("/api/habits/today/").json()["counts"]["smoke"] == 0
    assert other_api.get("/api/habits/summary/").json()["smoke"]["total"] == 0
    assert HabitLog.objects.get(pk=mine.pk).quantity == 1


def test_today(api, athlete):
    log(athlete, "smoke", 2)
    log(athlete, "smoke", 1)
    log(athlete, "sugar", 1, days_ago=1)
    body = api.get("/api/habits/today/").json()
    assert body["counts"] == {"smoke": 3, "alcohol": 0, "sugar": 0}
    assert set(body["last_at"]) == {"smoke", "alcohol", "sugar"}
    assert body["last_at"]["alcohol"] is None and body["last_at"]["sugar"]


def test_summary_shapes(api, athlete):
    athlete.smoke_goal, athlete.smoke_quit_date = "quit", athlete.local_today - dt.timedelta(days=5)
    athlete.smoke_baseline_per_day, athlete.cigarette_price = 10, 17.5
    athlete.save()
    log(athlete, "smoke", 2, days_ago=8)
    log(athlete, "smoke", 1, days_ago=2)
    log(athlete, "alcohol", 3, days_ago=1)
    body = api.get("/api/habits/summary/", {"range": "4w"}).json()
    assert set(body) == SUMMARY_KEYS
    smoke = body["smoke"]
    assert set(smoke) == {"series", "total", "per_day_avg", "trend_per_week", "streak",
                          "since_quit", "milestones"}
    assert len(smoke["series"]) == 28 and smoke["total"] == 3
    assert smoke["streak"] == {"current_days": 2, "best_days": 5}
    assert smoke["since_quit"] == {"days": 5, "cigarettes_avoided": 49.0, "money_saved": 857.5}
    assert len(smoke["milestones"]) == 8
    assert set(body["alcohol"]) == {"series", "total", "per_week_avg", "drink_days"}
    assert body["alcohol"]["drink_days"] == 1
    assert set(body["sugar"]) == {"series", "total", "per_day_avg"}
    assert body["impact"] and set(body["impact"][0]) == {
        "habit", "metric", "dose", "label", "with_avg", "without_avg", "diff", "diff_pct",
        "n_with", "n_without", "direction", "enough_data"}
    assert body["weekly"] and body["summary"]["status"] == "none"
    # R12: 1y is a preset everywhere now; anything else is still a 400.
    assert api.get("/api/habits/summary/", {"range": "2y"}).status_code == 400


def test_impact_from_real_rows(api, athlete):
    today = athlete.local_today
    for i in range(1, 13):
        d = today - dt.timedelta(days=i)
        drank = i % 2 == 0
        if drank:
            log(athlete, "alcohol", 2, days_ago=i, hour=21)
        wellness(athlete, d + dt.timedelta(days=1), hrv_overnight_avg=40 if drank else 50)
    rows = api.get("/api/habits/summary/").json()["impact"]
    hrv = next(r for r in rows if r["habit"] == "alcohol" and r["metric"] == "hrv"
               and r["dose"] is None)
    assert hrv["enough_data"] and hrv["direction"] == "worse" and hrv["diff"] == -10


def test_ai_summary_aggregates_only_and_cached(api, athlete, monkeypatch):
    seen = []

    def fake_complete(*, operation, schema, user, **kw):
        seen.append(user)
        return schema(markdown="Steady week."), {"model": "m", "input_tokens": 1,
                                                 "output_tokens": 1, "latency_ms": 1,
                                                 "retry_count": 0, "estimated_cost_usd": 0}
    monkeypatch.setattr(coaching, "complete", fake_complete)
    entry = log(athlete, "smoke", 1)
    entry.note = "SECRET-NOTE"
    entry.save()
    r = api.post("/api/habits/summary/?range=4w")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert r.json()["markdown"] == "Steady week." and len(seen) == 1
    assert "SECRET-NOTE" not in seen[0] and '"series"' not in seen[0]
    assert api.post("/api/habits/summary/").json()["status"] == "ready" and len(seen) == 1
    api.post("/api/habits/summary/?refresh=1")
    assert len(seen) == 2
    assert api.get("/api/habits/summary/").json()["summary"]["status"] == "ready"


def test_ai_summary_503(api, monkeypatch):
    def boom(**kw):
        raise AIUnavailable("down")
    monkeypatch.setattr(coaching, "complete", boom)
    r = api.post("/api/habits/summary/")
    assert r.status_code == 503 and "detail" in r.json()


def test_chat_log_habit_tool(athlete):
    from apps.coaching.tools import TOOLS, ToolRunner

    assert any(t["function"]["name"] == "log_habit" for t in TOOLS)
    run = ToolRunner(athlete)
    nine = athlete.local_now.replace(hour=0, minute=5).strftime("%Y-%m-%dT%H:%M")
    out = run("log_habit", {"kind": "alcohol", "quantity": 2, "at": nine})
    assert out["logged"]["quantity"] == 2 and out["today"]["alcohol"] == 2
    assert run("log_habit", {"kind": "weed", "quantity": 1})["error"]
    assert run("log_habit", {"kind": "smoke", "quantity": 0})["error"]
    future = run("log_habit", {"kind": "smoke", "quantity": 3, "at": "2099-01-01T09:00"})
    assert HabitLog.objects.get(pk=future["logged"]["id"]).at <= timezone.now()


def test_chat_context_has_counts_and_streak(athlete):
    from apps.coaching.chat import system_prompt

    athlete.smoke_goal = "quit"
    athlete.smoke_quit_date = athlete.local_today - dt.timedelta(days=3)
    athlete.save()
    log(athlete, "alcohol", 2, days_ago=1)
    prompt = system_prompt(athlete)
    assert '"habits"' in prompt and '"smoke_free_streak_days": 4' in prompt
    assert '"yesterday": {"smoke": 0, "alcohol": 2.0, "sugar": 0}' in prompt


@pytest.mark.parametrize("drinks,status,verdict", [(2, None, "go"), (3, "watch", "go"),
                                                   (5, "bad", "easy")])
def test_checkin_alcohol_signal(api, athlete, drinks, status, verdict):
    make_workout(athlete)
    log(athlete, "alcohol", drinks, days_ago=1, hour=21)
    body = api.get("/api/today/").json()
    reason = next((r for r in body["reasons"] if r["signal"] == "alcohol"), None)
    assert (reason or {}).get("status") == status
    if reason:
        assert reason["label"] == f"{drinks} drinks last night"
    assert body["verdict"] == verdict
    assert "alcohol" not in body["signals_missing"]


def test_insights_focus_smoke_free_streak(api, athlete):
    for i in (1, 2, 3, 5):
        log(athlete, "smoke", 2, days_ago=i)
    log(athlete, "smoke", 1, days_ago=20)
    focus = api.get("/api/insights/").json()["focus"]
    item = next(f for f in focus if f["key"] == "smoke_free")
    assert "4 of the last 14 days" in item["why"]


def test_averages_divide_by_the_window_not_days_with_data(api, athlete):
    """One 2-drink day today: 2 per week (at least a week counted), never 14."""
    log(athlete, "alcohol", 2)
    log(athlete, "sugar", 7)
    log(athlete, "smoke", 14)
    body = api.get("/api/habits/summary/", {"range": "4w"}).json()
    assert body["alcohol"]["per_week_avg"] == 2.0
    assert body["sugar"]["per_day_avg"] == 1.0
    assert body["smoke"]["per_day_avg"] == 2.0


def test_averages_use_the_whole_range_once_history_is_longer(api, athlete):
    log(athlete, "alcohol", 4, days_ago=60)      # first ever log, outside the 4w range
    log(athlete, "alcohol", 4, days_ago=3)
    log(athlete, "sugar", 2, days_ago=60)
    log(athlete, "sugar", 28, days_ago=10)
    body = api.get("/api/habits/summary/", {"range": "4w"}).json()
    assert body["alcohol"]["per_week_avg"] == 1.0           # 4 drinks / 4 weeks
    assert body["sugar"]["per_day_avg"] == 1.0              # 28 / 28 days
    assert body["alcohol"]["drink_days"] == 1


def test_ai_payload_money_has_units(athlete):
    from apps.habits.ai import HABITS_USER, ai_payload, rupees
    from apps.habits.services import summary_payload

    assert rupees(2448.0) == "₹2,448" and rupees(17.5) == "₹17.50" and rupees(None) is None
    athlete.smoke_goal, athlete.smoke_quit_date = "quit", athlete.local_today - dt.timedelta(days=12)
    athlete.smoke_baseline_per_day, athlete.cigarette_price = 12, 17
    athlete.save()
    clean = ai_payload(summary_payload(athlete, "4w"))
    assert clean["smoke"]["since_quit"]["money_saved"] == "₹2,448"
    assert clean["units"]["money"].startswith("INR") and "keep their units" in HABITS_USER
